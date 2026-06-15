import logging
import re
from typing import Sequence
from concurrent.futures import ThreadPoolExecutor
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

import config
from agent.tools import (
    get_repository_dna_summary,
    list_github_directory,
    read_github_source_file,
    search_repo_issues_and_prs
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Intent classifier — runs a single cheap LLM call BEFORE entering the
# ReAct loop.  Returns one of:
#   "direct"  → answer immediately from conversation context, no tools
#   "tool"    → needs tool calls, enter the ReAct loop
# ──────────────────────────────────────────────────────────────────────
INTENT_SYSTEM_PROMPT = (
    "You are a classifier for an open-source onboarding assistant. "
    "Given the conversation so far and the latest user message, "
    "decide whether the user's question can be answered directly from the conversation "
    "context (including any tool results already present), or whether new tool calls are needed.\n\n"
    "Respond with EXACTLY one word:\n"
    "- DIRECT  — if the question is conversational, a follow-up, or can be answered from context already available.\n"
    "- TOOL    — if new repository data (files, directories, issues, DNA summary) must be fetched.\n\n"
    "Examples of DIRECT: greetings, clarifications, opinions, summaries of prior answers, thank-you messages, "
    "'which issue should I start with?', 'explain the last answer differently', 'what did you recommend?'.\n"
    "Examples of TOOL: 'show me the code in X', 'what issues mention Y', 'list the files in Z', "
    "'read the file at path/to/file.py'."
)

def classify_intent(messages: list, llm: ChatOpenAI) -> str:
    """Lightweight LLM call to decide direct-answer vs tool-use."""
    try:
        payload = [SystemMessage(content=INTENT_SYSTEM_PROMPT)] + messages[-4:]  # last 4 msgs for speed
        response = llm.invoke(payload)
        verdict = response.content.strip().upper()
        if "DIRECT" in verdict:
            return "direct"
        return "tool"
    except Exception as e:
        logger.warning(f"Intent classification failed ({e}), defaulting to tool mode")
        return "tool"


# ──────────────────────────────────────────────────────────────────────
# Context window management
# ──────────────────────────────────────────────────────────────────────
def prune_old_tool_results(messages: list, keep_last_n: int = 1) -> list:
    """Prunes older TOOL RESULT messages in place to prevent context window inflation, 
    keeping only the N most recent tool results fully intact.
    """
    tool_indices = []
    for idx, msg in enumerate(messages):
        if isinstance(msg, HumanMessage) and msg.content.startswith("TOOL RESULT:"):
            tool_indices.append(idx)
            
    if len(tool_indices) > keep_last_n:
        for idx in tool_indices[:-keep_last_n]:
            orig_content = messages[idx].content
            # Keep first 300 characters of the tool result and add a truncation warning
            if len(orig_content) > 300:
                messages[idx] = HumanMessage(
                    content=orig_content[:300] + "\n\n... [Remaining tool result content truncated to save context window space. Refer to your previous thoughts for details.]"
                )
    return messages


def compress_conversation_for_loop(messages: list, max_messages: int = 12) -> list:
    """If the in-loop message list grows too long, keep only the most
    recent messages to stop context-window inflation from killing quality.
    We always preserve the original user question (first HumanMessage).
    """
    if len(messages) <= max_messages:
        return messages

    # Always keep the first human message (the original question)
    first_human_idx = next(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not m.content.startswith("TOOL RESULT:")),
        None,
    )
    preserved = [messages[first_human_idx]] if first_human_idx is not None else []
    
    # Then keep the tail
    tail_size = max_messages - len(preserved)
    preserved += messages[-tail_size:]
    return preserved


# ──────────────────────────────────────────────────────────────────────
# XML tool-call parsing
# ──────────────────────────────────────────────────────────────────────
def parse_all_tool_calls(content: str) -> list:
    """Parses all XML tool call blocks in the LLM response text, returning a list of dicts:
    [{'name': 'tool_name', 'arg': 'parameter_value'}]
    """
    tool_calls = []
    # Try finding explicit <tool_call> blocks first
    blocks = re.findall(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL | re.IGNORECASE)
    if blocks:
        for block in blocks:
            name_match = re.search(r"<(tool_name|tool_call_name|name)>(\w+)</\1>", block, re.IGNORECASE)
            if name_match:
                tool_name = name_match.group(2).strip()
                arg_match = re.search(r"<(tool_arg|arg)>(.*?)</\1>", block, re.DOTALL | re.IGNORECASE)
                tool_arg = arg_match.group(2).strip().strip('"').strip("'") if arg_match else ""
                tool_calls.append({"name": tool_name, "arg": tool_arg})
    else:
        # Fallback: if no outer <tool_call> tag is present, search the entire content for name-arg pairs
        name_matches = list(re.finditer(r"<(tool_name|tool_call_name|name)>(\w+)</\1>", content, re.IGNORECASE))
        for i, match in enumerate(name_matches):
            tool_name = match.group(2).strip()
            # Search for the next arg tag after this name tag but before the next name tag
            start_pos = match.end()
            end_pos = name_matches[i+1].start() if i + 1 < len(name_matches) else len(content)
            subcontent = content[start_pos:end_pos]
            arg_match = re.search(r"<(tool_arg|arg)>(.*?)</\1>", subcontent, re.DOTALL | re.IGNORECASE)
            tool_arg = arg_match.group(2).strip().strip('"').strip("'") if arg_match else ""
            tool_calls.append({"name": tool_name, "arg": tool_arg})
            
    return tool_calls


def has_final_answer(content: str) -> bool:
    """Robust check for whether the LLM response is a final answer (not a tool call).
    Returns True when the response contains NO tool call XML AND contains
    substantive text (not just whitespace or a stray closing tag).
    """
    tool_calls = parse_all_tool_calls(content)
    if tool_calls:
        return False
    # Also guard against partial / malformed XML that didn't parse
    if re.search(r"<tool_call>|<tool_name>|<tool_call_name>", content, re.IGNORECASE):
        return False
    # Must have some real content
    cleaned = re.sub(r"<[^>]+>", "", content).strip()
    return len(cleaned) > 10


# ──────────────────────────────────────────────────────────────────────
# Parallel tool execution
# ──────────────────────────────────────────────────────────────────────
def run_tools_parallel(tool_calls: list, repo_id: str) -> list:
    """Runs all requested tool calls in parallel using a ThreadPoolExecutor."""
    def execute_single_tool(call):
        tool_name = call["name"]
        tool_arg = call["arg"]
        logger.info(f"Parallel worker executing: {tool_name} with arg: {tool_arg}")
        
        try:
            if tool_name == "get_repository_dna_summary":
                result = get_repository_dna_summary.invoke({"repo_id": repo_id})
            elif tool_name == "list_github_directory":
                result = list_github_directory.invoke({"repo_id": repo_id, "path": tool_arg})
            elif tool_name == "read_github_source_file":
                result = read_github_source_file.invoke({"repo_id": repo_id, "file_path": tool_arg})
            elif tool_name == "search_repo_issues_and_prs":
                result = search_repo_issues_and_prs.invoke({"repo_id": repo_id, "query": tool_arg})
            else:
                result = f"Error: Tool '{tool_name}' is not recognized."
        except Exception as err:
            logger.error(f"Error executing tool {tool_name}: {err}")
            result = f"Error executing tool: {str(err)}"
            
        return {"name": tool_name, "arg": tool_arg, "result": result}

    with ThreadPoolExecutor(max_workers=max(1, len(tool_calls))) as executor:
        results = list(executor.map(execute_single_tool, tool_calls))
    return results


# ──────────────────────────────────────────────────────────────────────
# Session state tracking — extracts structured data from tool results
# for handoff to the orchestrator / coding agent.
# ──────────────────────────────────────────────────────────────────────
def _extract_issue_numbers(text: str) -> list:
    """Extract issue/PR numbers mentioned in text (e.g., '#42', 'Issue #7')."""
    matches = re.findall(r"#(\d+)", text)
    return [int(m) for m in matches]


# ──────────────────────────────────────────────────────────────────────
# Onboarding Agent — system prompts
# ──────────────────────────────────────────────────────────────────────
TOOL_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert open-source onboarding mentor.\n"
    "Your sole purpose is to help a new contributor get started with the repository '{repo_id}'.\n"
    "The contributor's background is: '{user_background}'.\n\n"
    "Your responsibilities:\n"
    "- Explain what the repository does, its architecture, and key modules\n"
    "- Help the contributor understand the codebase by browsing files and directories\n"
    "- Recommend specific issues or PRs that match their skills\n"
    "- Suggest a learning order: which files to read first, which modules to understand before tackling an issue\n"
    "- Answer setup and contribution workflow questions\n\n"
    "To retrieve codebase details dynamically, you must call a tool by outputting a tool call block using the following XML tags at the end of your response:\n"
    "<tool_call>\n"
    "<tool_name>tool_name</tool_name>\n"
    "<tool_arg>parameter_value</tool_arg>\n"
    "</tool_call>\n\n"
    "Available tools:\n"
    "- get_repository_dna_summary\n"
    "  Retrieve repository conventions, entry points, setup, and description. Parameter is the repo_id (e.g. <tool_call><tool_name>get_repository_dna_summary</tool_name><tool_arg>tiangolo/fastapi</tool_arg></tool_call>)\n"
    "- list_github_directory\n"
    "  List contents of a directory. Parameter is relative path or empty for root (e.g. <tool_call><tool_name>list_github_directory</tool_name><tool_arg>src/api</tool_arg></tool_call>)\n"
    "- read_github_source_file\n"
    "  Read raw code in a file. Parameter is relative path (e.g. <tool_call><tool_name>read_github_source_file</tool_name><tool_arg>api/server.py</tool_arg></tool_call>)\n"
    "- search_repo_issues_and_prs\n"
    "  Search issues and PRs. Parameter is the search term (e.g. <tool_call><tool_name>search_repo_issues_and_prs</tool_name><tool_arg>PostgreSQL connection pool</tool_arg></tool_call>)\n\n"
    "Rules:\n"
    "1. You can request MULTIPLE tool actions at a time to check several files in parallel. Output them as separate <tool_call> blocks.\n"
    "2. When you have enough context to answer the user's question, DO NOT output any <tool_call> block. Just write your final response directly.\n"
    "3. Be technical, accurate, and reference specific file names.\n"
    "4. IMPORTANT: You MUST produce a final answer within 4 tool-use rounds. After receiving tool results, synthesise what you have and respond — do NOT keep calling tools.\n"
    "5. Stay strictly within onboarding scope. Do NOT write code, generate patches, or solve issues. Only guide the contributor."
)

DIRECT_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert open-source onboarding mentor.\n"
    "You are helping a new contributor get started with the repository '{repo_id}'.\n"
    "The contributor's background is: '{user_background}'.\n\n"
    "Answer the user's onboarding question directly using the conversation context. "
    "Suggest learning paths, explain architecture, recommend issues, and clarify setup steps. "
    "Be concise, technical, and helpful. Do NOT output any XML tool tags. "
    "Do NOT write code or generate patches — only guide the contributor."
)

MAX_TOOL_ROUNDS = 5


class OnboardingAgent:
    """A dedicated onboarding ReAct agent that helps new contributors understand
    a repository, explore its structure, and find suitable first issues.
    
    Emits a structured session_summary for orchestrator handoff.
    """
    
    def __init__(self):
        # Session-level state accumulated across tool rounds
        self._dna_summary_seen = ""
        self._files_explored = []
        self._issues_mentioned = []
    
    def _track_tool_results(self, results: list):
        """Extract structured session data from tool execution results."""
        for res in results:
            tool_name = res["name"]
            result_text = str(res.get("result", ""))
            
            if tool_name == "get_repository_dna_summary" and not result_text.startswith("Error"):
                self._dna_summary_seen = result_text[:2000]  # cap for handoff payload
            elif tool_name == "read_github_source_file":
                self._files_explored.append(res["arg"])
            elif tool_name == "list_github_directory":
                self._files_explored.append(res["arg"] or "/")
            elif tool_name == "search_repo_issues_and_prs":
                # Extract issue numbers from search results
                self._issues_mentioned.extend(_extract_issue_numbers(result_text))
    
    def _extract_selected_issue(self, messages: list) -> int | None:
        """Scan recent messages for explicit issue selection by the user or recommendation by the agent."""
        # Look at last few messages for explicit issue references
        for msg in reversed(messages[-6:]):
            if isinstance(msg, (HumanMessage, AIMessage)):
                numbers = _extract_issue_numbers(msg.content)
                if numbers:
                    return numbers[0]  # most recent mention
        return None
    
    def _build_session_summary(self, repo_id: str, user_background: str, messages: list) -> dict:
        """Build the structured handoff payload for the orchestrator."""
        selected_issue = self._extract_selected_issue(messages)
        
        return {
            "repo_id": repo_id,
            "user_background": user_background,
            "dna_summary": self._dna_summary_seen,
            "selected_issue": selected_issue,
            "files_explored": list(set(self._files_explored)),  # deduplicate
            "issues_mentioned": list(set(self._issues_mentioned)),
        }

    def _stream_final_answer(self, llm, payload, messages):
        """Stream the final answer token-by-token, yielding 'token' events, 
        then a 'final_answer' event with the complete text."""
        full_content = ""
        for chunk in llm.stream(payload):
            token = chunk.content
            if token:
                full_content += token
                yield {"type": "token", "content": token}
        
        full_content = full_content.strip()
        yield {"type": "final_answer", "content": full_content}
        messages.append(AIMessage(content=full_content))

    def invoke_stream(self, state: dict):
        """Yields progress events (thought, tool_end, token, final_answer, session_summary, final_state) in real-time."""
        messages = list(state.get("messages", []))
        repo_id = state.get("repo_id", "unknown/repo")
        user_background = state.get("user_background", "not provided")
        
        llm = ChatOpenAI(
            model=config.LLM_MODEL,
            base_url=config.LLM_BASE_URL,
            api_key=config.NEBIUS_API_KEY,
            temperature=0.1,
            max_completion_tokens=2048,
        )
        
        # ── Step 1: Intent classification ──
        intent = classify_intent(messages, llm)
        logger.info(f"[OnboardingAgent] Intent classified as: {intent}")
        
        if intent == "direct":
            # Fast path — stream answer directly without entering the tool loop
            direct_prompt = DIRECT_SYSTEM_PROMPT_TEMPLATE.format(
                repo_id=repo_id, user_background=user_background
            )
            payload = [SystemMessage(content=direct_prompt)] + messages[-8:]
            yield from self._stream_final_answer(llm, payload, messages)
            
            # Emit session summary for orchestrator
            yield {
                "type": "session_summary",
                "payload": self._build_session_summary(repo_id, user_background, messages)
            }
            yield {"type": "final_state", "messages": messages}
            return
        
        # ── Step 2: Tool-use ReAct loop (buffered llm.invoke) ──
        tool_prompt = TOOL_SYSTEM_PROMPT_TEMPLATE.format(
            repo_id=repo_id, user_background=user_background
        )
        
        # Working message list for the loop (separate from the full conversation)
        loop_messages = list(messages)
        
        for loop_idx in range(MAX_TOOL_ROUNDS):
            # Compress context if it's growing too large
            loop_messages = compress_conversation_for_loop(loop_messages, max_messages=14)
            loop_messages = prune_old_tool_results(loop_messages, keep_last_n=2)
            
            payload = [SystemMessage(content=tool_prompt)] + loop_messages
            
            # Tool-calling rounds use buffered invoke (need full text to parse XML)
            response = llm.invoke(payload)
            content = response.content.strip()
            
            # ── Check for final answer (robust detection) ──
            if has_final_answer(content):
                # Re-stream the final answer for token-by-token UX
                # We already have the content, so emit it as tokens in chunks
                for i in range(0, len(content), 6):
                    yield {"type": "token", "content": content[i:i+6]}
                yield {"type": "final_answer", "content": content}
                messages.append(AIMessage(content=content))
                break
            
            tool_calls = parse_all_tool_calls(content)
            
            if not tool_calls:
                # Edge case: XML detected but didn't parse → treat as final answer
                cleaned = re.sub(r"<[^>]+>", "", content).strip()
                if cleaned:
                    for i in range(0, len(cleaned), 6):
                        yield {"type": "token", "content": cleaned[i:i+6]}
                    yield {"type": "final_answer", "content": cleaned}
                    messages.append(AIMessage(content=cleaned))
                else:
                    # Truly empty — force a synthesis round
                    loop_messages.append(AIMessage(content=content))
                    loop_messages.append(HumanMessage(
                        content="Please provide your final answer now based on the information you have gathered so far. Do NOT call any tools."
                    ))
                    continue
                break
            
            # Extract clean thought text by removing XML blocks
            thought = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
            yield {"type": "thought", "content": thought, "tool_calls": tool_calls}
            
            # Execute tools in parallel
            results = run_tools_parallel(tool_calls, repo_id)
            self._track_tool_results(results)  # Track for session summary
            yield {"type": "tool_end", "results": results}
            
            loop_messages.append(AIMessage(content=content))
            for res in results:
                # Truncate very large tool results at injection time
                result_text = str(res['result'])
                if len(result_text) > 3000:
                    result_text = result_text[:3000] + "\n\n... [truncated to 3000 chars]"
                loop_messages.append(HumanMessage(content=f"TOOL RESULT: {result_text}"))
            
            # On the penultimate round, nudge the LLM to wrap up
            if loop_idx == MAX_TOOL_ROUNDS - 2:
                loop_messages.append(HumanMessage(
                    content="[SYSTEM] You have used most of your tool rounds. Please synthesise your findings and give a final answer NOW. Do NOT call any more tools."
                ))
        else:
            # Exhausted all rounds — force one last streamed synthesis attempt
            loop_messages = compress_conversation_for_loop(loop_messages, max_messages=10)
            loop_messages.append(HumanMessage(
                content="[SYSTEM] Tool rounds exhausted. Provide your best final answer using the information gathered so far. Do NOT output any tool call XML."
            ))
            payload = [SystemMessage(content=tool_prompt)] + loop_messages
            
            full_content = ""
            for chunk in llm.stream(payload):
                token = chunk.content
                if token:
                    # Filter out stray XML tags from the stream
                    full_content += token
                    yield {"type": "token", "content": token}
            
            final_content = re.sub(r"<[^>]+>", "", full_content).strip()
            if not final_content or len(final_content) < 10:
                final_content = "I'm sorry, I reached my reasoning limit without finding a complete response. Please try asking a more specific question."
            yield {"type": "final_answer", "content": final_content}
            messages.append(AIMessage(content=final_content))
        
        # Emit session summary for orchestrator handoff
        yield {
            "type": "session_summary",
            "payload": self._build_session_summary(repo_id, user_background, messages)
        }
        yield {"type": "final_state", "messages": messages}

    def invoke(self, state: dict) -> dict:
        """Run the stream to completion for backward compatibility with the test suite."""
        messages = list(state.get("messages", []))
        final_messages = messages
        session_summary = None
        
        stream = self.invoke_stream(state)
        for event in stream:
            if event["type"] == "final_state":
                final_messages = event["messages"]
            elif event["type"] == "session_summary":
                session_summary = event["payload"]
                
        result = {"messages": final_messages}
        if session_summary:
            result["session_summary"] = session_summary
        return result


def get_onboarding_agent():
    """Factory function to create a new OnboardingAgent instance."""
    return OnboardingAgent()

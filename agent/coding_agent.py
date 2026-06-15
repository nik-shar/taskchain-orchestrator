import time
import logging
import json
import re
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

import config
from utils.db import SessionLocal, HandoffSession

logger = logging.getLogger(__name__)

def append_log(session_id: str, message: str, progress: int = None, status: str = None):
    """Utility to append logs and update progress/status of a handoff session."""
    db = SessionLocal()
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if handoff:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            handoff.logs = (handoff.logs or "") + f"[{timestamp}] {message}\n"
            if progress is not None:
                handoff.progress_pct = progress
            if status is not None:
                handoff.status = status
            db.commit()
    except Exception as e:
        logger.error(f"Failed to append log: {e}")
    finally:
        db.close()

def parse_coding_tool_call(content: str) -> Optional[dict]:
    """Parses XML tool call format from Coding Agent LLM output."""
    name_match = re.search(r"<name>(\w+)</name>", content, re.IGNORECASE)
    if not name_match:
        return None
    name = name_match.group(1).strip()
    
    arg_match = re.search(r"<arg>(.*?)</arg>", content, re.DOTALL | re.IGNORECASE)
    arg = arg_match.group(1).strip() if arg_match else ""
    
    extra_content = ""
    if name == "write_file":
        content_match = re.search(r"<content>(.*?)</content>", content, re.DOTALL | re.IGNORECASE)
        if content_match:
            extra_content = content_match.group(1)
            # Trim leading and trailing newlines to keep block indent clean
            if extra_content.startswith("\n"):
                extra_content = extra_content[1:]
            if extra_content.endswith("\n"):
                extra_content = extra_content[:-1]
                
    return {"name": name, "arg": arg, "content": extra_content}

def run_coding_loop(session_id: str):
    """Background task running the autonomous coding agent workflow."""
    logger.info(f"Background coding agent loop started for session {session_id}")
    
    db = SessionLocal()
    try:
        handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
        if not handoff:
            logger.error(f"HandoffSession {session_id} not found in database.")
            return
        
        repo_id = handoff.repo_id
        issue_id = handoff.selected_issue
        user_background = handoff.user_background
        steering_instructions = handoff.steering_instructions
        dna_summary = handoff.dna_summary or ""
        
        owner, repo = repo_id.split("/")
        clone_path = config.REPOS_CLONE_DIR / owner / repo
        
        # Verify clone path exists
        if not clone_path.exists():
            append_log(session_id, "Clone workspace missing. Attempting to clone repository on the fly...", progress=7)
            from ingestion.ingestion_pipeline import clone_repository_locally
            clone_repository_locally(owner, repo)
            
        if not clone_path.exists():
            append_log(session_id, f"[ERROR] Git clone workspace directory not found at {clone_path}", status="failed")
            return
            
        # Clean and reset git repository workspace for a fresh start
        append_log(session_id, "Resetting sandbox workspace to pristine clone state...", progress=5, status="environment_setup")
        subprocess.run(["git", "reset", "--hard"], cwd=str(clone_path), capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=str(clone_path), capture_output=True)
        
    except Exception as e:
        logger.error(f"Failed initializing workspace: {e}")
        append_log(session_id, f"[ERROR] Sandbox workspace reset failed: {str(e)}", status="failed")
        return
    finally:
        db.close()

    try:
        # Load LLM client
        llm = ChatOpenAI(
            model=config.LLM_MODEL,
            base_url=config.LLM_BASE_URL,
            api_key=config.NEBIUS_API_KEY,
            temperature=0.1,
            max_completion_tokens=2048,
        )
        
        # Formulate ReAct Coding prompt
        system_prompt = (
            f"You are an expert autonomous Coding Agent.\n"
            f"Your task is to solve issue #{issue_id} in the repository '{repo_id}'.\n\n"
            f"Developer Profile context: '{user_background}'.\n"
        )
        if steering_instructions:
            system_prompt += f"User steering constraints (MUST FOLLOW STRICTLY):\n{steering_instructions}\n\n"
            
        system_prompt += (
            f"Repository DNA conventions summary:\n{dna_summary}\n\n"
            f"To call a tool, output a tool call XML block at the end of your response:\n"
            f"<tool_call>\n"
            f"<name>tool_name</name>\n"
            f"<arg>relative_path_or_command</arg>\n"
            f"</tool_call>\n\n"
            f"For write_file, provide file content inside a <content> block like so:\n"
            f"<tool_call>\n"
            f"<name>write_file</name>\n"
            f"<arg>src/main.py</arg>\n"
            f"</tool_call>\n"
            f"<content>\n"
            f"def new_code():\n"
            f"    pass\n"
            f"</content>\n\n"
            f"Available tools:\n"
            f"1. list_directory\n"
            f"   List files/folders. Arg is relative folder path or empty for root.\n"
            f"2. read_file\n"
            f"   Read code files. Arg is relative file path.\n"
            f"3. write_file\n"
            f"   Overwrite file content. Arg is relative path. You MUST supply the <content> tag.\n"
            f"4. run_tests\n"
            f"   Execute test runner in container. Arg is command (e.g. 'pytest tests/' or 'npm test').\n\n"
            f"Rules:\n"
            f"- Explore the repository structure and read relevant files before editing.\n"
            f"- Make edits, and run the sandbox test suites to verify your logic.\n"
            f"- When complete and verified, write your final explanation without calling any tools.\n"
            f"- You must finish within 150 tool execution rounds."
        )
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=f"Please solve issue #{issue_id}.")]
        max_rounds = 150
        
        append_log(session_id, "Coding Agent initialized. Starting ReAct solving loop...", progress=15, status="coding")
        
        for round_idx in range(max_rounds):
            response = llm.invoke(messages)
            content = response.content.strip()
            
            # Extract clean thought by omitting tool_call tags
            thought = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL | re.IGNORECASE)
            thought = re.sub(r"<content>.*?</content>", "", thought, flags=re.DOTALL | re.IGNORECASE).strip()
            
            if thought:
                append_log(session_id, f"[THOUGHT] {thought}", progress=15 + int((round_idx / max_rounds) * 60))
                
            tool_call = parse_coding_tool_call(content)
            
            # If no tool call was emitted, LLM decided it is finished
            if not tool_call:
                append_log(session_id, "[AGENT] Done! Wrapping up sandbox execution...", progress=90, status="verification")
                break
                
            tool_name = tool_call["name"]
            tool_arg = tool_call["arg"]
            tool_content = tool_call["content"]
            
            append_log(session_id, f"[TOOL CALL] Running: {tool_name} with target: '{tool_arg}'")
            
            # Tool dispatcher
            result_text = ""
            try:
                if tool_name == "list_directory":
                    dir_path = clone_path / tool_arg.strip("/")
                    if not dir_path.exists():
                        result_text = f"Error: Folder '{tool_arg}' does not exist."
                    elif not dir_path.is_dir():
                        result_text = f"Error: '{tool_arg}' is a file, not a directory."
                    else:
                        items = os.listdir(dir_path)
                        result_text = "\n".join(items) if items else "(Empty folder)"
                        
                elif tool_name == "read_file":
                    file_path = clone_path / tool_arg.strip("/")
                    if not file_path.exists():
                        result_text = f"Error: File '{tool_arg}' not found."
                    elif file_path.is_dir():
                        result_text = f"Error: '{tool_arg}' is a directory."
                    else:
                        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                            result_text = f.read()
                            
                elif tool_name == "write_file":
                    file_path = clone_path / tool_arg.strip("/")
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(tool_content)
                    result_text = f"Successfully wrote {len(tool_content)} chars to '{tool_arg}'."
                    
                elif tool_name == "run_tests":
                    from utils.sandbox import run_sandbox_command
                    exit_code, stdout, stderr = run_sandbox_command(repo_id, tool_arg)
                    result_text = f"Sandbox Test Suite exit code: {exit_code}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                    
                else:
                    result_text = f"Error: Unrecognized tool name '{tool_name}'."
            except Exception as tool_err:
                logger.error(f"Error running coding agent tool {tool_name}: {tool_err}")
                result_text = f"Error executing tool: {str(tool_err)}"
                
            # Truncate very large tool results to protect context window
            if len(result_text) > 3000:
                result_text = result_text[:3000] + "\n\n... [tool result truncated]"
                
            messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=f"TOOL RESULT:\n{result_text}"))
            
            # Penultimate round nudge
            if round_idx == max_rounds - 2:
                messages.append(HumanMessage(
                    content="[SYSTEM] Sandbox execution time limit approaching. Verify code edits, run final tests, and complete your response now."
                ))
                
            time.sleep(1) # safe pacing
            
        # ── Verification & Completion ──
        # Generate git diff
        diff_res = subprocess.run(["git", "diff"], cwd=str(clone_path), capture_output=True, text=True)
        patch_diff = diff_res.stdout if diff_res.returncode == 0 else ""
        
        db = SessionLocal()
        try:
            handoff = db.query(HandoffSession).filter_by(session_id=session_id).first()
            if handoff:
                handoff.patch_diff = patch_diff
                handoff.status = "completed"
                handoff.progress_pct = 100
                timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                if patch_diff:
                    handoff.logs = (handoff.logs or "") + f"[{timestamp}] [SUCCESS] Task completed. Generated git patch successfully!\n"
                else:
                    handoff.logs = (handoff.logs or "") + f"[{timestamp}] [SUCCESS] Task completed. No changes were made to the files.\n"
                db.commit()
        finally:
            db.close()
            
    except Exception as e:
        logger.exception(f"Coding Agent loop failed: {e}")
        append_log(session_id, f"[ERROR] Coding Agent execution failed: {str(e)}", status="failed")

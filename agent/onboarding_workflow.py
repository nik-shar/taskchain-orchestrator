import os
import re
import sqlite3
import logging
import hashlib
import json
import time
from typing import TypedDict, Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import chromadb
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

import config
from utils.db import SessionLocal, RepoIngestion, OnboardingGuide
from ingestion.ingestion_pipeline import get_collection_name, embed_texts

logger = logging.getLogger(__name__)

class OnboardingState(TypedDict):
    repo_id: str
    user_background: str
    dna_summary: str
    background_hash: str
    search_queries: List[str]
    retrieved_issues: List[dict]
    guide: str
    error: Optional[str]
    latency_info: Optional[dict]


def build_llm():
    """Build the ChatOpenAI client with credentials from configuration."""
    return ChatOpenAI(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        api_key=config.NEBIUS_API_KEY,
        temperature=0.1,
        max_completion_tokens=2048,
    )


def clean_fts_query(query: str) -> str:
    """Prepare a search query for SQLite FTS5 MATCH syntax."""
    # Find all words/numbers
    words = re.findall(r"\w+", query)
    if not words:
        return ""
    # Join with OR operator for FTS5 keyword matching
    return " OR ".join(words)


def load_repo_context(state: OnboardingState) -> OnboardingState:
    """Node 1: Load repo DNA summary from PostgreSQL."""
    start_time = time.time()
    try:
        repo_id = state["repo_id"]
        try:
            owner, repo = repo_id.split("/")
        except ValueError:
            state["error"] = "Invalid repository format. Must be 'owner/repo'."
            return state
            
        db: Session = SessionLocal()
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        
        if not ingestion or ingestion.status != "complete":
            state["error"] = "Repo not indexed yet"
            db.close()
            return state
            
        # Check if ingestion is older than 7 days
        ingested_naive = ingestion.ingested_at.replace(tzinfo=None) if ingestion.ingested_at.tzinfo is not None else ingestion.ingested_at
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if ingested_naive < now_naive - timedelta(days=config.INGESTION_REFRESH_DAYS):
            logger.warning(f"Ingestion for {repo_id} is stale (older than {config.INGESTION_REFRESH_DAYS} days).")
            
        state["dna_summary"] = ingestion.dna_summary or ""
        db.close()
    finally:
        if "latency_info" not in state or state["latency_info"] is None:
            state["latency_info"] = {}
        state["latency_info"]["load_repo_context"] = time.time() - start_time
    return state


def build_search_query(state: OnboardingState) -> OnboardingState:
    """Node 2: Call LLM to generate search queries based on user background."""
    start_time = time.time()
    try:
        if state.get("error"):
            return state
            
        llm = build_llm()
        system_prompt = (
            "You are an expert developer assistant. Given a new contributor's background description, "
            "generate 2 to 3 search queries that can be used to retrieve relevant issues or pull requests "
            "from a repository index. Return a raw JSON array of strings only. "
            'Example response format: ["query 1", "query 2"]'
        )
        
        try:
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Contributor Background: {state['user_background']}")
            ])
            content = response.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n|```$", "", content, flags=re.MULTILINE).strip()
            queries = json.loads(content)
            if not isinstance(queries, list):
                queries = [state["user_background"]]
        except Exception as e:
            logger.error(f"Failed to generate queries via LLM: {e}")
            queries = [state["user_background"]]
            
        state["search_queries"] = queries
    finally:
        if "latency_info" not in state or state["latency_info"] is None:
            state["latency_info"] = {}
        state["latency_info"]["build_search_query"] = time.time() - start_time
    return state


def hybrid_search_issues(state: OnboardingState) -> OnboardingState:
    """Node 3: Search SQLite FTS5 and Chroma for issues/PRs using RRF and apply boosts."""
    start_time = time.time()
    try:
        if state.get("error"):
            return state
            
        repo_id = state["repo_id"]
        try:
            owner, repo = repo_id.split("/")
        except ValueError:
            state["error"] = "Invalid repository format."
            return state
            
        queries = state.get("search_queries", [state["user_background"]])
        
        con = sqlite3.connect(config.SQLITE_PATH)
        cur = con.cursor()
        
        # Initialize Chroma client
        chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
        collection_name = get_collection_name(owner, repo)
        
        try:
            collection = chroma_client.get_collection(name=collection_name)
        except Exception:
            logger.warning(f"Chroma collection not found: {collection_name}")
            collection = None
            
        RRF_K = 60
        fused_scores = {}
        doc_map = {}
        
        for query in queries:
            # 1. Lexical Search via SQLite FTS5
            lexical_results = []
            clean_q = clean_fts_query(query)
            if clean_q:
                try:
                    cur.execute("""
                        SELECT issue_number, title, body, labels, state, is_good_first_issue, type
                        FROM issues_fts
                        WHERE repo_id = ? AND issues_fts MATCH ?
                        LIMIT 20
                    """, (repo_id, clean_q))
                    rows = cur.fetchall()
                except sqlite3.OperationalError:
                    # Fallback to simple LIKE search if MATCH query syntax is invalid
                    like_pattern = f"%{query}%"
                    cur.execute("""
                        SELECT issue_number, title, body, labels, state, is_good_first_issue, type
                        FROM issues_fts
                        WHERE repo_id = ? AND (title LIKE ? OR body LIKE ?)
                        LIMIT 20
                    """, (repo_id, like_pattern, like_pattern))
                    rows = cur.fetchall()
                    
                for rank, row in enumerate(rows):
                    doc_id = f"{row[6]}_{row[0]}"
                    lexical_results.append({
                        "doc_id": doc_id,
                        "number": int(row[0]),
                        "title": row[1],
                        "body": row[2],
                        "labels": row[3].split(", ") if row[3] else [],
                        "state": row[4],
                        "is_good_first_issue": bool(row[5]),
                        "type": row[6],
                        "rank": rank
                    })
                    
            # 2. Semantic Search via Chroma DB
            semantic_results = []
            if collection:
                try:
                    query_vec = embed_texts([query])[0]
                    results = collection.query(
                        query_embeddings=[query_vec],
                        n_results=config.SEMANTIC_TOP_K,
                        where={"repo_id": repo_id}
                    )
                    
                    for rank, (meta, doc_text) in enumerate(zip(
                        results["metadatas"][0],
                        results["documents"][0]
                    )):
                        issue_num = int(meta["number"])
                        issue_type = meta["type"]
                        
                        # Retrieve the full structured issue info from SQLite FTS5 database
                        cur.execute("""
                            SELECT title, body, labels, state, is_good_first_issue
                            FROM issues_fts
                            WHERE repo_id = ? AND issue_number = ? AND type = ?
                            LIMIT 1
                        """, (repo_id, issue_num, issue_type))
                        row = cur.fetchone()
                        if row:
                            doc_id = f"{issue_type}_{issue_num}"
                            semantic_results.append({
                                "doc_id": doc_id,
                                "number": issue_num,
                                "title": row[0],
                                "body": row[1],
                                "labels": row[2].split(", ") if row[2] else [],
                                "state": row[3],
                                "is_good_first_issue": bool(row[4]),
                                "type": issue_type,
                                "rank": rank
                            })
                except Exception as e:
                    logger.warning(f"Semantic search query failed for '{query}': {e}")
                    
            # 3. Fuse Lexical and Semantic ranks with RRF
            for rank_list in [lexical_results, semantic_results]:
                for item in rank_list:
                    doc_id = item["doc_id"]
                    rank = item["rank"]
                    doc_map[doc_id] = item
                    
                    contribution = 1.0 / (RRF_K + rank + 1)
                    fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + contribution

        con.close()
        
        # 4. Apply boosts (Good First Issues and Open Issues)
        boosted_scores = {}
        for doc_id, score in fused_scores.items():
            item = doc_map[doc_id]
            boost = 1.0
            if item["is_good_first_issue"]:
                boost *= 1.5
            if item["state"] == "open":
                boost *= 1.2
            boosted_scores[doc_id] = score * boost
            
        # Sort and take top 5
        sorted_docs = sorted(boosted_scores.items(), key=lambda x: x[1], reverse=True)[:5]
        state["retrieved_issues"] = [doc_map[doc_id] for doc_id, _ in sorted_docs]
    finally:
        if "latency_info" not in state or state["latency_info"] is None:
            state["latency_info"] = {}
        state["latency_info"]["hybrid_search_issues"] = time.time() - start_time
    return state


def synthesize_guide(state: OnboardingState) -> OnboardingState:
    """Node 4: Synthesize the onboarding guide matching background and retrieved issues."""
    start_time = time.time()
    try:
        if state.get("error"):
            return state
            
        repo_id = state["repo_id"]
        try:
            _, repo_name = repo_id.split("/")
        except ValueError:
            repo_name = repo_id
            
        llm = build_llm()
        
        # Format issues to pass to prompt context
        issues_str = ""
        for idx, issue in enumerate(state["retrieved_issues"]):
            labels = ", ".join(issue["labels"])
            issues_str += (
                f"Candidate {idx+1}:\n"
                f"  - Issue #{issue['number']}: {issue['title']}\n"
                f"  - Type: {issue['type']}\n"
                f"  - State: {issue['state']}\n"
                f"  - Labels: {labels}\n"
                f"  - Description: {issue['body'][:600]}\n\n"
            )
            
        system_prompt = (
            f"You are a senior engineer/maintainer helping a new contributor onboarding to {repo_name}.\n"
            f"Here is the repository DNA summary:\n"
            f"{state['dna_summary']}\n\n"
            f"Please write a structured onboarding guide customized for the contributor. "
            f"You must strictly reference specific issue numbers, file names, and repo-specific details. "
            f"Never give generic advice. Every sentence must reference something specific to this repo."
        )
        
        user_prompt = f"""Write a structured onboarding guide for this developer:
Background: {state['user_background']}

Here are the retrieved recommended issues/PRs from the repository:
{issues_str}

You must strictly output the guide using this exact Markdown template:

## Welcome to {repo_name}

### What this repo does
{{2-3 sentences max summarizing the repo purpose}}

### Your setup steps
{{numbered list of setup steps extracted from DNA summary}}

### Recommended issues for you
For each of 3 issues (choose the best 3 matches from the retrieved issues/PRs above):
  - Issue #{{number}}: {{title}}
  - Why it matches your background: {{1 sentence explaining connection}}
  - Context: {{what has been tried, or relevant comments from comments/PR description}}
  - Where to start: {{specific file or function in the repo where they should look}}

### First file to read
{{filename and explanation of why it is the best starting point}}
"""
        
        try:
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            state["guide"] = response.content
        except Exception as e:
            logger.error(f"Failed to generate onboarding guide: {e}")
            state["error"] = f"Failed to synthesize guide: {str(e)}"
    finally:
        if "latency_info" not in state or state["latency_info"] is None:
            state["latency_info"] = {}
        state["latency_info"]["synthesize_guide"] = time.time() - start_time
    return state


def collect_feedback(state: OnboardingState) -> OnboardingState:
    """Node 5: Generate user background hash to track feedback session."""
    start_time = time.time()
    try:
        if state.get("error"):
            return state
            
        bg_hash = hashlib.sha256(state["user_background"].encode("utf-8")).hexdigest()
        state["background_hash"] = bg_hash
    finally:
        if "latency_info" not in state or state["latency_info"] is None:
            state["latency_info"] = {}
        state["latency_info"]["collect_feedback"] = time.time() - start_time
    return state


# Build LangGraph workflow
workflow = StateGraph(OnboardingState)

workflow.add_node("load_repo_context", load_repo_context)
workflow.add_node("build_search_query", build_search_query)
workflow.add_node("hybrid_search_issues", hybrid_search_issues)
workflow.add_node("synthesize_guide", synthesize_guide)
workflow.add_node("collect_feedback", collect_feedback)

workflow.set_entry_point("load_repo_context")

# Connect workflow nodes sequentially
workflow.add_edge("load_repo_context", "build_search_query")
workflow.add_edge("build_search_query", "hybrid_search_issues")
workflow.add_edge("hybrid_search_issues", "synthesize_guide")
workflow.add_edge("synthesize_guide", "collect_feedback")
workflow.add_edge("collect_feedback", END)

# Compile LangGraph
compiled_graph = workflow.compile()


def run_onboarding_workflow(repo_id: str, user_background: str) -> dict:
    """Run the contributor onboarding LangGraph workflow."""
    initial_state = {
        "repo_id": repo_id,
        "user_background": user_background,
        "dna_summary": "",
        "background_hash": "",
        "search_queries": [],
        "retrieved_issues": [],
        "guide": "",
        "error": None,
        "latency_info": {}
    }
    
    # Execute the graph
    result = compiled_graph.invoke(initial_state)
    return result

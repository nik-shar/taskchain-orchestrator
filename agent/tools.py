import logging
import re
import sqlite3
import base64
import httpx
import chromadb
from langchain_core.tools import tool
from sqlalchemy.orm import Session

import config
from utils.db import SessionLocal, RepoIngestion
from ingestion.github_fetcher import GitHubFetcher, parse_github_url
from ingestion.ingestion_pipeline import get_collection_name, embed_texts

logger = logging.getLogger(__name__)

@tool
def get_repository_dna_summary(repo_id: str) -> str:
    """
    Retrieve the high-level Repo DNA summary for a given repository.
    This summary includes the repository description, detected tech stack, local setup steps, 
    key code entry points, and contribution conventions.
    
    Args:
        repo_id (str): The repository identifier in 'owner/repo' format (e.g. 'tiangolo/fastapi').
    """
    try:
        owner, repo = repo_id.split("/")
    except ValueError:
        return "Error: repo_id must be in the format 'owner/repo'."
        
    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if not ingestion:
            return f"No ingestion record found for repository {repo_id}."
        if ingestion.status != "complete":
            return f"Ingestion status is '{ingestion.status}'. It is not fully connected/indexed yet."
        return ingestion.dna_summary or "No DNA summary available."
    except Exception as e:
        logger.error(f"Error reading repository DNA: {e}")
        return f"Error loading DNA summary: {str(e)}"
    finally:
        db.close()

@tool
def list_github_directory(repo_id: str, path: str = "") -> str:
    """
    List files and directories in a specific path inside the GitHub repository.
    Use this tool to browse the repository file tree structure.
    
    Args:
        repo_id (str): The repository identifier in 'owner/repo' format (e.g. 'tiangolo/fastapi').
        path (str): The relative directory path to list (e.g. 'src/api' or '' for the root directory).
    """
    try:
        owner, repo = repo_id.split("/")
    except ValueError:
        return "Error: repo_id must be in the format 'owner/repo'."
        
    try:
        fetcher = GitHubFetcher()
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path.strip('/')}"
        with httpx.Client() as client:
            res = fetcher._request(client, url)
            if res.status_code == 404:
                return f"Path '{path}' not found in the repository."
            items = res.json()
            if not isinstance(items, list):
                return f"'{path}' is a file, not a directory. Use read_github_source_file to read it."
                
            formatted_items = []
            for item in items:
                item_type = item.get("type", "file")
                item_path = item.get("path", "")
                formatted_items.append(f"[{item_type.upper()}] {item_path}")
            return "\n".join(formatted_items) if formatted_items else "Empty directory."
    except Exception as e:
        logger.error(f"Error listing directory {path}: {e}")
        return f"Error listing directory '{path}': {str(e)}"

@tool
def read_github_source_file(repo_id: str, file_path: str) -> str:
    """
    Fetch and return the raw text contents of a source code or markdown file in the GitHub repository.
    
    Args:
        repo_id (str): The repository identifier in 'owner/repo' format (e.g. 'tiangolo/fastapi').
        file_path (str): The relative path to the file (e.g. 'api/server.py' or 'README.md').
    """
    try:
        owner, repo = repo_id.split("/")
    except ValueError:
        return "Error: repo_id must be in the format 'owner/repo'."
        
    fetcher = GitHubFetcher()
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    try:
        with httpx.Client() as client:
            res = fetcher._request(client, url)
            if res.status_code == 404:
                return f"File '{file_path}' not found in the repository."
            file_data = res.json()
            if isinstance(file_data, list):
                return f"'{file_path}' is a directory, not a file. Use list_github_directory to view its contents."
            
            # Decode base64 content
            content_b64 = file_data.get("content", "")
            content = base64.b64decode(content_b64).decode("utf-8")
            
            lines = content.splitlines()
            if len(lines) > 800:
                truncated = "\n".join(lines[:800])
                return f"{truncated}\n\n[Warning: File truncated from {len(lines)} lines to 800 lines to preserve context space]"
            return content
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return f"Error reading file '{file_path}': {str(e)}"

@tool
def search_repo_issues_and_prs(repo_id: str, query: str) -> str:
    """
    Perform a hybrid keyword and semantic search over the ingested issues and pull requests of the repository.
    Returns the top 5 most relevant issues or pull requests matching the query.
    
    Args:
        repo_id (str): The repository identifier in 'owner/repo' format (e.g. 'tiangolo/fastapi').
        query (str): The search term or semantic query (e.g. 'database connection pool error').
    """
    try:
        owner, repo = repo_id.split("/")
    except ValueError:
        return "Error: repo_id must be in the format 'owner/repo'."
        
    con = sqlite3.connect(config.SQLITE_PATH)
    cur = con.cursor()
    
    # Initialize Chroma client
    chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    collection_name = get_collection_name(owner, repo)
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
    except Exception:
        collection = None
        
    RRF_K = 60
    fused_scores = {}
    doc_map = {}
    
    # 1. Lexical Search via SQLite FTS5
    lexical_results = []
    words = re.findall(r"\w+", query)
    clean_q = " OR ".join(words) if words else ""
    
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
            
    con.close()
    
    # 3. Fuse scores with RRF
    for rank_list in [lexical_results, semantic_results]:
        for item in rank_list:
            doc_id = item["doc_id"]
            rank = item["rank"]
            doc_map[doc_id] = item
            
            contribution = 1.0 / (RRF_K + rank + 1)
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + contribution
            
    # 4. Apply boosts
    boosted_scores = {}
    for doc_id, score in fused_scores.items():
        item = doc_map[doc_id]
        boost = 1.0
        if item["is_good_first_issue"]:
            boost *= 1.5
        if item["state"] == "open":
            boost *= 1.2
        boosted_scores[doc_id] = score * boost
        
    sorted_docs = sorted(boosted_scores.items(), key=lambda x: x[1], reverse=True)[:5]
    top_items = [doc_map[doc_id] for doc_id, _ in sorted_docs]
    
    if not top_items:
        return "No matching issues or pull requests found."
        
    formatted = []
    for item in top_items:
        labels_str = ", ".join(item["labels"])
        gfi_str = " (Good First Issue)" if item["is_good_first_issue"] else ""
        formatted.append(
            f"- [{item['type'].upper()} #{item['number']}] {item['title']}{gfi_str}\n"
            f"  State: {item['state']} | Labels: {labels_str}\n"
            f"  Description: {item['body'][:300]}..."
        )
    return "\n\n".join(formatted)

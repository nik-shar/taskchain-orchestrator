import os
import re
import subprocess
import sqlite3
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import chromadb
from openai import OpenAI

import config
from utils.db import SessionLocal, RepoIngestion
from ingestion.github_fetcher import RepoSnapshot, GitHubFetcher, parse_github_url

logger = logging.getLogger(__name__)

def update_progress(owner: str, repo: str, progress_pct: int, status_message: str):
    """Write intermediate progress status to PostgreSQL repo_ingestions table."""
    db = SessionLocal()
    try:
        ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
        if ingestion:
            ingestion.progress_pct = progress_pct
            ingestion.status_message = status_message
            db.commit()
    except Exception as e:
        logger.error(f"Failed to update progress for {owner}/{repo}: {e}")
    finally:
        db.close()

def get_collection_name(owner: str, repo: str) -> str:
    """Generate a valid Chroma collection name for the repository."""
    name = f"issues_{owner}_{repo}".lower()
    # Replace non-alphanumeric/hyphen/underscore with underscore
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    # Collapse multiple consecutive underscores or hyphens
    name = re.sub(r"_+", "_", name)
    name = re.sub(r"-+", "-", name)
    # Trim leading/trailing separators
    name = name.strip("_-")
    return name[:63]


def embed_texts(texts: list[str], progress_callback=None) -> list[list[float]]:
    """Batch embed text strings using the configured Nebius embeddings API."""
    if not texts:
        return []
        
    # Prepend embedding instruction if matching Qwen embedding instructions
    instruction = "Instruct: Given a GitHub repository issue description, retrieve similar developer context\nQuery: "
    prepared_texts = [instruction + t for t in texts]
    
    # Call embeddings in chunks to avoid large payloads if needed
    chunk_size = 32
    batches = []
    for i in range(0, len(prepared_texts), chunk_size):
        batches.append((i, prepared_texts[i:i+chunk_size]))
        
    def embed_batch_with_retry(batch_index: int, batch: list[str]) -> tuple[int, list[list[float]]]:
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.EMBEDDING_BASE_URL,
                    api_key=config.EMBEDDING_API_KEY,
                    timeout=60.0,
                )
                response = client.embeddings.create(
                    model=config.EMBEDDING_MODEL,
                    input=batch
                )
                # Sort response by index to preserve order within the batch
                sorted_data = sorted(response.data, key=lambda x: x.index)
                embeddings = [item.embedding for item in sorted_data]
                return batch_index, embeddings
            except Exception as e:
                logger.warning(f"Embedding batch attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    results = []
    completed_batches = 0
    total_batches = len(batches)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_batch = {
            executor.submit(embed_batch_with_retry, batch_idx, batch): batch_idx
            for batch_idx, batch in batches
        }
        for future in as_completed(future_to_batch):
            batch_idx, batch_embeddings = future.result()
            results.append((batch_idx, batch_embeddings))
            completed_batches += 1
            if progress_callback:
                # Map progress from 95% to 99%
                progress_pct = 95 + int((completed_batches / total_batches) * 4)
                progress_callback(
                    progress_pct, 
                    f"Generating semantic embeddings ({completed_batches}/{total_batches} batches completed)..."
                )
                
    # Sort results by batch_idx to reconstruct the original list order
    results.sort(key=lambda x: x[0])
    embeddings = []
    for _, batch_embeddings in results:
        embeddings.extend(batch_embeddings)
        
    return embeddings


def generate_repo_dna_summary(snapshot: RepoSnapshot) -> str:
    """Call the LLM to generate the Bucket 1 repository DNA summary using concurrent chunking (4 chunks)."""
    
    def summarize_readme(readme_text: str) -> str:
        if not readme_text:
            return "No README file was found in this repository."
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.LLM_BASE_URL,
                    api_key=config.NEBIUS_API_KEY,
                    timeout=60.0
                )
                system_prompt = (
                    "You are a senior engineer summarizing a GitHub repository README. "
                    "Extract the project overview, setup/installation instructions, and tech stack information."
                )
                user_prompt = f"README:\n{readme_text[:15000]}"
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1024
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"README summary attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    def summarize_contributing(contrib_text: str | None) -> str:
        if not contrib_text:
            return "No CONTRIBUTING.md guidelines were provided in this repository."
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.LLM_BASE_URL,
                    api_key=config.NEBIUS_API_KEY,
                    timeout=60.0
                )
                system_prompt = (
                    "You are a senior engineer analyzing a repository's contributing guidelines. "
                    "Extract details on PR conventions, development setup, and code contribution guidelines."
                )
                user_prompt = f"CONTRIBUTING guidelines:\n{contrib_text[:15000]}"
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1024
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"Contributing guidelines summary attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    def summarize_structure(file_tree: list, tech_stack: dict) -> str:
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.LLM_BASE_URL,
                    api_key=config.NEBIUS_API_KEY,
                    timeout=60.0
                )
                system_prompt = (
                    "You are a senior engineer analyzing a repository's codebase structure. "
                    "Identify core modules, entry-point files, programming languages, and tech stack/framework configuration."
                )
                user_prompt = f"""File tree:
{file_tree[:300]}

Tech stack configuration files/details:
{tech_stack}
"""
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1024
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"Codebase structure summary attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    def summarize_issues_prs(issues: list, prs: list) -> str:
        if not issues and not prs:
            return "No issues or pull requests found in this repository."
            
        issue_lines = []
        seen_issues = set()
        for issue in issues:
            if len(seen_issues) >= 20:
                break
            if issue.number in seen_issues:
                continue
            seen_issues.add(issue.number)
            labels_str = ", ".join(issue.labels) if issue.labels else "None"
            issue_lines.append(f"- Issue #{issue.number}: {issue.title} (State: {issue.state}, Labels: {labels_str}, Good First: {issue.is_good_first_issue})")
            
        pr_lines = []
        for pr in prs[:20]:
            pr_lines.append(f"- PR #{pr.number}: {pr.title} (State: {pr.state}, Merged: {pr.merged})")
            
        issues_input = "\n".join(issue_lines) if issue_lines else "No issues found."
        prs_input = "\n".join(pr_lines) if pr_lines else "No pull requests found."
        
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.LLM_BASE_URL,
                    api_key=config.NEBIUS_API_KEY,
                    timeout=60.0
                )
                system_prompt = (
                    "You are a senior engineer summarizing recent developer issues and pull requests in a codebase. "
                    "Extract common developer activity topics, outstanding issues overview, and recent developer context."
                )
                user_prompt = f"""Recent Issues:
{issues_input}

Recent Pull Requests:
{prs_input}
"""
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1024
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"Issues & PRs summary attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    def synthesize_dna(readme_summary: str, contrib_summary: str, struct_summary: str, issues_summary: str, repo_name: str) -> str:
        max_attempts = 3
        last_error = None
        for attempt in range(max_attempts):
            try:
                client = OpenAI(
                    base_url=config.LLM_BASE_URL,
                    api_key=config.NEBIUS_API_KEY,
                    timeout=60.0
                )
                system_prompt = (
                    "You are a senior engineer summarizing a GitHub repository for a new contributor. "
                    "Generate a cohesive, structured summary in Markdown using the exact requested sections. "
                    "Be highly specific. Use actual file names, tools, and workflows from the provided summaries. "
                    "Never be generic."
                )
                user_prompt = f"""Given these summarized findings for the repository '{repo_name}', generate a structured summary with these exact sections:
1. What this repo does (2-3 sentences max)
2. Tech stack (list only what you can confirm from config files)
3. How to set up locally (extract from README/CONTRIBUTING summaries, step by step)
4. Where to start reading the code (1-2 entry point files with explanation)
5. Contribution workflow (how PRs are structured, any conventions observed)

README summary notes:
{readme_summary}

Contributing guidelines notes:
{contrib_summary}

Structure summary notes:
{struct_summary}

Issues & PRs summary notes:
{issues_summary}
"""
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=2048
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"DNA synthesis attempt {attempt + 1} failed: {e}")
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

    repo_name = f"{snapshot.owner}/{snapshot.repo}"
    
    # Run README, Contributing guidelines, Structure, and Issues/PRs summarizations in parallel (4 tasks)
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_readme = executor.submit(summarize_readme, snapshot.readme)
        future_contrib = executor.submit(summarize_contributing, snapshot.contributing)
        future_struct = executor.submit(summarize_structure, snapshot.file_tree, snapshot.tech_stack)
        future_issues = executor.submit(summarize_issues_prs, snapshot.issues, snapshot.pull_requests)
        
        # Gather results (result() blocks until the thread finishes)
        readme_sum = future_readme.result()
        contrib_sum = future_contrib.result()
        struct_sum = future_struct.result()
        issues_sum = future_issues.result()
        
    # Synthesize the final summary
    return synthesize_dna(readme_sum, contrib_sum, struct_sum, issues_sum, repo_name)


def index_in_sqlite_fts5(repo_id: str, snapshot: RepoSnapshot) -> None:
    """Index issue and pull request content into SQLite FTS5 index database."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(config.SQLITE_PATH), exist_ok=True)
    
    con = sqlite3.connect(config.SQLITE_PATH)
    cur = con.cursor()
    
    # Create the virtual table if not exists
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
            repo_id,
            issue_number,
            title,
            body,
            labels,
            state,
            is_good_first_issue,
            type
        );
    """)
    
    # Delete existing entries for this repo to support clean re-indexing
    cur.execute("DELETE FROM issues_fts WHERE repo_id = ?", (repo_id,))
    
    # Insert issues
    for issue in snapshot.issues:
        labels_str = ", ".join(issue.labels)
        cur.execute("""
            INSERT INTO issues_fts (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            repo_id,
            issue.number,
            issue.title,
            issue.body,
            labels_str,
            issue.state,
            1 if issue.is_good_first_issue else 0,
            "issue"
        ))
        
    # Insert pull requests
    for pr in snapshot.pull_requests:
        cur.execute("""
            INSERT INTO issues_fts (repo_id, issue_number, title, body, labels, state, is_good_first_issue, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            repo_id,
            pr.number,
            pr.title,
            pr.body,
            "",
            pr.state,
            0,
            "pr"
        ))
        
    con.commit()
    con.close()


def index_in_chroma(repo_id: str, snapshot: RepoSnapshot, progress_callback=None) -> None:
    """Generate embeddings and index issue and PR data in Chroma vector database."""
    chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    collection_name = get_collection_name(snapshot.owner, snapshot.repo)
    
    # Delete existing collection if it exists to refresh indices
    try:
        chroma_client.delete_collection(name=collection_name)
    except Exception:
        pass
        
    collection = chroma_client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )
    
    documents = []
    metadatas = []
    ids = []
    
    # Prepare documents to embed from issues
    for idx, issue in enumerate(snapshot.issues):
        labels_str = ", ".join(issue.labels)
        doc_text = f"{issue.title}\n{issue.body}\nLabels: {labels_str}"
        documents.append(doc_text)
        metadatas.append({
            "repo_id": repo_id,
            "number": issue.number,
            "state": issue.state,
            "is_good_first_issue": issue.is_good_first_issue,
            "type": "issue"
        })
        ids.append(f"issue_{issue.number}_{idx}")
        
    # Prepare documents to embed from PRs
    for idx, pr in enumerate(snapshot.pull_requests):
        doc_text = f"{pr.title}\n{pr.body}"
        documents.append(doc_text)
        metadatas.append({
            "repo_id": repo_id,
            "number": pr.number,
            "state": pr.state,
            "is_good_first_issue": False,
            "type": "pr"
        })
        ids.append(f"pr_{pr.number}_{idx}")
        
    if not documents:
        return
        
    # Generate embeddings and add to collection
    logger.info(f"Generating embeddings for {len(documents)} items...")
    embeddings = embed_texts(documents, progress_callback=progress_callback)
    
    # Add to Chroma in batches
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(
            ids=ids[i:i+batch_size],
            embeddings=embeddings[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size],
            documents=documents[i:i+batch_size]
        )


def clone_repository_locally(owner: str, repo: str) -> bool:
    """Clones the repository locally using git clone subprocess."""
    from pathlib import Path
    clone_dir = config.REPOS_CLONE_DIR / owner / repo
    if clone_dir.exists():
        logger.info(f"Repository already cloned locally at {clone_dir}")
        return True
        
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    repo_url = f"https://github.com/{owner}/{repo}.git"
    
    # Check if a custom token is configured
    if config.GITHUB_TOKEN:
        repo_url = f"https://x-access-token:{config.GITHUB_TOKEN}@github.com/{owner}/{repo}.git"
        
    logger.info(f"Cloning repository {repo_url} to {clone_dir}")
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=180
        )
        if res.returncode != 0:
            logger.error(f"Git clone failed for {owner}/{repo}: {res.stderr}")
            return False
        logger.info(f"Successfully cloned repository {owner}/{repo}!")
        return True
    except Exception as err:
        logger.error(f"Failed executing git clone for {owner}/{repo}: {err}")
        return False


def ingest_repository(repo_url: str) -> dict:
    """Run the end-to-end ingestion pipeline for a given repository URL."""
    db: Session = SessionLocal()
    
    # 1. Parse repository URL
    try:
        owner, repo = parse_github_url(repo_url)
        repo_id = f"{owner}/{repo}"
    except ValueError as e:
        logger.error(f"URL parsing failed: {e}")
        db.close()
        return {"status": "failed", "error": str(e)}
        
    # 2. Add or update db ingestion record with pending status
    ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
    if not ingestion:
        ingestion = RepoIngestion(
            owner=owner, 
            repo=repo, 
            status="pending",
            progress_pct=5,
            status_message="Parsing repository URL..."
        )
        db.add(ingestion)
    else:
        ingestion.status = "pending"
        ingestion.progress_pct = 5
        ingestion.status_message = "Parsing repository URL..."
        ingestion.ingested_at = datetime.now(timezone.utc)
    db.commit()
    db.close() # Close connection to prevent locking during fetching
    
    # Define a callback helper for the fetch stage
    def progress_callback(pct, msg):
        update_progress(owner, repo, pct, msg)
        
    try:
        import time
        import json
        start_time = time.time()
        
        # 3. Fetch GitHub Repository Snapshot
        logger.info(f"Starting GitHub fetcher for {repo_url}...")
        fetcher = GitHubFetcher()
        snapshot = fetcher.fetch_repo(repo_url, progress_callback=progress_callback)
        fetch_latency = time.time() - start_time
        
        # 4. Generate DNA Summary (Bucket 1)
        logger.info("Generating repository DNA summary...")
        progress_callback(75, "Generating repository DNA summary...")
        dna_start = time.time()
        dna_summary = generate_repo_dna_summary(snapshot)
        dna_latency = time.time() - dna_start
        
        # 5. Index Issue/PR History in SQLite FTS5 (Bucket 2)
        logger.info("Indexing in SQLite FTS5...")
        progress_callback(85, "Building keyword search index...")
        fts_start = time.time()
        index_in_sqlite_fts5(repo_id, snapshot)
        fts_latency = time.time() - fts_start
        
        # 6. Index in Chroma Vector Database (Bucket 2)
        logger.info("Indexing in Chroma DB...")
        progress_callback(95, "Generating semantic embeddings...")
        chroma_start = time.time()
        index_in_chroma(repo_id, snapshot, progress_callback=progress_callback)
        chroma_latency = time.time() - chroma_start
        
        # 6.5. Clone repository locally for workspace use
        logger.info("Cloning repository locally...")
        progress_callback(97, "Cloning repository locally...")
        clone_repository_locally(owner, repo)
        
        total_latency = time.time() - start_time
        
        latency_info = {
            "fetch_repo": fetch_latency,
            "generate_dna_summary": dna_latency,
            "index_fts": fts_latency,
            "index_chroma": chroma_latency,
            "total_ingestion": total_latency
        }
        
        # 7. Update PostgreSQL Ingestion record
        db = SessionLocal()
        try:
            ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
            if ingestion:
                ingestion.dna_summary = dna_summary
                ingestion.issue_count = len(snapshot.issues)
                ingestion.pr_count = len(snapshot.pull_requests)
                ingestion.status = "complete"
                ingestion.progress_pct = 100
                ingestion.status_message = "Complete!"
                ingestion.latency_info = json.dumps(latency_info)
                db.commit()
        finally:
            db.close()
        
        logger.info(f"Ingestion completed successfully for {repo_id}!")
        return {
            "status": "complete",
            "repo_id": repo_id,
            "issue_count": len(snapshot.issues),
            "pr_count": len(snapshot.pull_requests)
        }
        
    except Exception as e:
        logger.exception(f"Ingestion failed for {repo_id}: {e}")
        db = SessionLocal()
        try:
            ingestion = db.query(RepoIngestion).filter_by(owner=owner, repo=repo).first()
            if ingestion:
                ingestion.status = "failed"
                ingestion.status_message = f"Failed: {str(e)}"
                db.commit()
        except Exception as db_err:
            logger.error(f"Failed to record ingestion failure in DB: {db_err}")
        finally:
            db.close()
        raise e


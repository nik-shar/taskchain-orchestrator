"""Shared path resolution for company resources and retrieval datasets."""

from __future__ import annotations

import os
from pathlib import Path


def company_sim_root() -> Path:
    env_candidates = [
        os.getenv("AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT"),
        os.getenv("ORCHESTRATOR_COMPANY_SIM_ROOT"),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path.exists():
            return path

    default = Path(__file__).resolve().parents[4] / "company_details" / "company_sim"
    return default.resolve()


def rag_index_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_candidates = [
        os.getenv("AGENT_ORCHESTRATOR_RAG_INDEX_PATH"),
        os.getenv("ORCHESTRATOR_RAG_INDEX_PATH"),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        return Path(raw).expanduser().resolve()

    default = Path(__file__).resolve().parents[4] / "data" / "rag_index.sqlite"
    return default.resolve()


def chroma_persist_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_candidates = [
        os.getenv("AGENT_ORCHESTRATOR_CHROMA_PERSIST_PATH"),
        os.getenv("ORCHESTRATOR_CHROMA_PERSIST_PATH"),
    ]
    for raw in env_candidates:
        if not raw:
            continue
        return Path(raw).expanduser().resolve()

    default = Path(__file__).resolve().parents[4] / "data" / "rag_chroma"
    return default.resolve()


def chroma_collection_name(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip()

    env_candidates = [
        os.getenv("AGENT_ORCHESTRATOR_CHROMA_COLLECTION"),
        os.getenv("ORCHESTRATOR_CHROMA_COLLECTION"),
    ]
    for raw in env_candidates:
        if raw and raw.strip():
            return raw.strip()
    return "rag_chunks_v1"

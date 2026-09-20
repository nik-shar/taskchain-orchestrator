from datetime import datetime, timezone
from sqlalchemy import create_engine, Boolean, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

import config

Base = declarative_base()


class RepoIngestion(Base):
    __tablename__ = "repo_ingestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    ingested_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    issue_count = Column(Integer, default=0)
    pr_count = Column(Integer, default=0)
    dna_summary = Column(Text, nullable=True)
    status = Column(String(50), default="pending")  # pending | complete | failed
    progress_pct = Column(Integer, default=0)
    status_message = Column(String(255), nullable=True)


class RepoDoc(Base):
    """Tier 1: curated documentation files collected during ingestion."""

    __tablename__ = "repo_docs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(String(512), nullable=False, index=True)
    path = Column(String(1024), nullable=False)
    content = Column(Text, nullable=False)
    priority = Column(Integer, default=100)  # lower = more important, injected first
    truncated = Column(Boolean, default=False)


_connect_args = (
    {"check_same_thread": False}
    if config.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all required tables in the database."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a database session for dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

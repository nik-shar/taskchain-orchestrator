import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class RepoIngestion(Base):
    __tablename__ = "repo_ingestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    ingested_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    issue_count = Column(Integer, default=0)
    pr_count = Column(Integer, default=0)
    dna_summary = Column(Text, nullable=True)
    status = Column(String(50), default="pending")  # pending | complete | failed
    progress_pct = Column(Integer, default=0)
    status_message = Column(String(255), nullable=True)
    latency_info = Column(Text, nullable=True)

class OnboardingGuide(Base):
    __tablename__ = "onboarding_guides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(String(255), nullable=False)
    background_hash = Column(String(64), nullable=False)
    guide = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    latency_info = Column(Text, nullable=True)

class UserFeedback(Base):
    __tablename__ = "user_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(String(255), nullable=False)
    background_hash = Column(String(64), nullable=False)
    rating = Column(Integer, nullable=False)  # 0 | 1 | 2
    session_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False) # e.g. owner_repo_hash
    role = Column(String(50), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class OnboardingSessionState(Base):
    __tablename__ = "onboarding_session_states"

    session_id = Column(String(255), primary_key=True)
    repo_id = Column(String(255), nullable=False)
    user_background = Column(Text, nullable=False)
    dna_summary = Column(Text, nullable=True)
    selected_issue = Column(Integer, nullable=True)
    files_explored = Column(Text, nullable=True)  # JSON-serialized list
    issues_mentioned = Column(Text, nullable=True)  # JSON-serialized list
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class HandoffSession(Base):
    __tablename__ = "handoff_sessions"

    session_id = Column(String(255), primary_key=True)
    repo_id = Column(String(255), nullable=False)
    selected_issue = Column(Integer, nullable=False)
    user_background = Column(Text, nullable=False)
    steering_instructions = Column(Text, nullable=True)
    dna_summary = Column(Text, nullable=True)
    files_explored = Column(Text, nullable=True)  # JSON-serialized list
    status = Column(String(50), default="pending")  # pending | environment_setup | coding | verification | completed | failed
    progress_pct = Column(Integer, default=0)
    logs = Column(Text, default="")
    patch_diff = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

# Read DATABASE_URL from configuration
import config
engine = create_engine(
    config.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_timeout=60
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all required tables in the database."""
    Base.metadata.create_all(bind=engine)
    
    # Run migrations for progress columns and latency columns if they are not already created
    with engine.connect() as conn:
        from sqlalchemy import text
        try:
            conn.execute(text("ALTER TABLE repo_ingestions ADD COLUMN IF NOT EXISTS progress_pct INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE repo_ingestions ADD COLUMN IF NOT EXISTS status_message VARCHAR(255)"))
            conn.execute(text("ALTER TABLE repo_ingestions ADD COLUMN IF NOT EXISTS latency_info TEXT"))
            conn.execute(text("ALTER TABLE onboarding_guides ADD COLUMN IF NOT EXISTS latency_info TEXT"))
            conn.execute(text("ALTER TABLE handoff_sessions ADD COLUMN IF NOT EXISTS steering_instructions TEXT"))
            conn.commit()
        except Exception:
            pass

def get_db():
    """Retrieve a database session instance."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

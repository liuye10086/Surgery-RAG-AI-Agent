"""Worker-only PostgreSQL limits; no shared HTTP engine or RAG initialization."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=2,
    max_overflow=0,
    pool_timeout=5,
    connect_args={
        "connect_timeout": 5,
        "options": "-c statement_timeout=5000 -c lock_timeout=3000",
        "keepalives_idle": 5,
        "keepalives_interval": 2,
        "keepalives_count": 2,
        "tcp_user_timeout": 5000,
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

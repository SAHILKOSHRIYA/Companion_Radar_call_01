"""SQLAlchemy models and session factory.

One table does the heavy lifting: `calls`. It stores the raw metadata, the
transcript we produced, and the analysis, all keyed by the call id (`sid`).
Customers and agents are derived by grouping on their names — we expose them
through views/queries rather than separate tables, which keeps ingestion simple
and matches how the data actually arrives (names embedded in each call).
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text, JSON, Index, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://callradar:callradar@localhost:5432/callradar",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


class Call(Base):
    __tablename__ = "calls"

    # Identity / metadata
    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    agent_name: Mapped[str] = mapped_column(String(255), index=True)
    session_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)

    # Transcript we produced
    transcript: Mapped[dict] = mapped_column(JSON, default=dict)       # {turns, duration, engine}
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    stt_engine: Mapped[str] = mapped_column(String(64), default="")

    # Analysis
    intent_summary: Mapped[str] = mapped_column(String(512), default="")
    intent_category: Mapped[str] = mapped_column(String(64), default="", index=True)
    mood_start: Mapped[str] = mapped_column(String(32), default="neutral")
    mood_end: Mapped[str] = mapped_column(String(32), default="neutral")
    mood_shifted: Mapped[bool] = mapped_column(Boolean, default=False)
    mood_shift_at: Mapped[str] = mapped_column(String(16), default="")
    resolution_status: Mapped[str] = mapped_column(String(32), default="unclear", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    attention_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)          # full evidence-cited object
    analysis_engine: Mapped[str] = mapped_column(String(64), default="")
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    # QA / compliance layer (the "sounded resolved but wasn't" intelligence)
    qa_score: Mapped[int] = mapped_column(Integer, default=100, index=True)
    qa: Mapped[dict] = mapped_column(JSON, default=dict)                # full QA object
    resolution_risk: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_attention_started", "attention_score", "started_at"),
    )


def init_db() -> None:
    Base.metadata.create_all(engine)

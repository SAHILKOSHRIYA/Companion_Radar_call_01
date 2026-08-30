"""CallRadar API.

Serves everything the dashboard needs and the API contract the brief requires:
  * GET /api/calls/{sid}          -> full per-call analysis with evidence + timings
  * GET /api/customers            -> every customer with call counts
  * GET /api/customers/{name}     -> a customer's full call history
  * GET /api/attention            -> ranked "needs a manager today" list
  * GET /api/trends               -> trending issues across all calls
  * GET /api/agents               -> per-agent volumes, handle times, outcomes
  * GET /api/audio/{sid}.mp3      -> the playable recording
  * GET /api/stats                -> dashboard headline numbers

The API never re-transcribes on request: everything is precomputed by the
pipeline and read straight from Postgres.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, desc

from .models.db import Call, SessionLocal, init_db

AUDIO_DIR = os.getenv("CALLRADAR_AUDIO_DIR", "/data/audio")

app = FastAPI(title="CallRadar API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _call_brief(c: Call) -> dict:
    return {
        "sid": c.sid,
        "customer_name": c.customer_name,
        "agent_name": c.agent_name,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "duration_sec": c.duration_sec,
        "intent_summary": c.intent_summary,
        "intent_category": c.intent_category,
        "mood_start": c.mood_start,
        "mood_end": c.mood_end,
        "mood_shifted": c.mood_shifted,
        "resolution_status": c.resolution_status,
        "summary": c.summary,
        "attention_score": c.attention_score,
        "evidence_score": c.evidence_score,
        "topics": c.topics or [],
        "analysis_engine": c.analysis_engine,
    }


def _call_full(c: Call) -> dict:
    return {
        **_call_brief(c),
        "session_label": c.session_label,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "stt_engine": c.stt_engine,
        "transcript": c.transcript,
        "transcript_text": c.transcript_text,
        "analysis": c.analysis,
        "audio_url": f"/api/audio/{c.sid}.mp3",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    with SessionLocal() as s:
        n = s.query(func.count(Call.sid)).scalar()
    return {"status": "ok", "calls": n}


@app.get("/api/stats")
def stats():
    with SessionLocal() as s:
        total = s.query(func.count(Call.sid)).scalar() or 0
        customers = s.query(func.count(func.distinct(Call.customer_name))).scalar() or 0
        agents = s.query(func.count(func.distinct(Call.agent_name))).scalar() or 0
        unresolved = s.query(func.count(Call.sid)).filter(
            Call.resolution_status.in_(["unresolved", "escalated", "partially_resolved"])
        ).scalar() or 0
        high_attention = s.query(func.count(Call.sid)).filter(Call.attention_score >= 70).scalar() or 0
        avg_att = s.query(func.avg(Call.attention_score)).scalar() or 0
        avg_ev = s.query(func.avg(Call.evidence_score)).scalar() or 0
    return {
        "total_calls": total,
        "customers": customers,
        "agents": agents,
        "unresolved": unresolved,
        "high_attention": high_attention,
        "avg_attention": round(float(avg_att), 1),
        "avg_evidence_score": round(float(avg_ev), 3),
    }


@app.get("/api/calls/{sid}")
def get_call(sid: str):
    with SessionLocal() as s:
        c = s.get(Call, sid)
        if not c:
            raise HTTPException(404, "call not found")
        return _call_full(c)


@app.get("/api/customers")
def list_customers(q: str = Query("", description="name search")):
    with SessionLocal() as s:
        rows = (
            s.query(
                Call.customer_name,
                func.count(Call.sid).label("calls"),
                func.max(Call.started_at).label("last_call"),
                func.max(Call.attention_score).label("max_attention"),
                func.avg(Call.attention_score).label("avg_attention"),
            )
            .group_by(Call.customer_name)
            .order_by(desc("max_attention"))
            .all()
        )
    out = []
    for name, calls, last_call, max_att, avg_att in rows:
        if q and q.lower() not in name.lower():
            continue
        out.append({
            "customer_name": name,
            "calls": calls,
            "last_call": last_call.isoformat() if last_call else None,
            "max_attention": int(max_att or 0),
            "avg_attention": round(float(avg_att or 0), 1),
        })
    return {"customers": out, "total": len(out)}


@app.get("/api/customers/{name}")
def customer_history(name: str):
    with SessionLocal() as s:
        calls = (
            s.query(Call)
            .filter(Call.customer_name == name)
            .order_by(desc(Call.started_at))
            .all()
        )
        if not calls:
            raise HTTPException(404, "customer not found")
    return {
        "customer_name": name,
        "call_count": len(calls),
        "calls": [_call_brief(c) for c in calls],
    }


@app.get("/api/attention")
def attention(limit: int = 50, today_only: bool = False):
    """Ranked 'needs a manager's attention today' list."""
    with SessionLocal() as s:
        q = s.query(Call).order_by(desc(Call.attention_score), desc(Call.started_at))
        if today_only:
            # Rank within the most recent day present in the data.
            latest = s.query(func.max(func.date(Call.started_at))).scalar()
            if latest:
                q = q.filter(func.date(Call.started_at) == latest)
        calls = q.limit(limit).all()
    return {"calls": [_call_brief(c) for c in calls], "count": len(calls)}


@app.get("/api/trends")
def trends(limit: int = 15):
    """Trending issues across all calls (by topic + intent category)."""
    with SessionLocal() as s:
        cat_rows = (
            s.query(Call.intent_category, func.count(Call.sid))
            .group_by(Call.intent_category)
            .order_by(desc(func.count(Call.sid)))
            .all()
        )
        all_topics = s.query(Call.topics).all()
    topic_counter: Counter = Counter()
    for (topics,) in all_topics:
        for t in (topics or []):
            topic_counter[str(t).strip().lower()] += 1
    return {
        "categories": [{"category": c or "other", "count": n} for c, n in cat_rows],
        "topics": [{"topic": t, "count": n} for t, n in topic_counter.most_common(limit)],
    }


@app.get("/api/agents")
def agents():
    """Per-agent view: volumes, handle times, outcomes."""
    with SessionLocal() as s:
        rows = (
            s.query(
                Call.agent_name,
                func.count(Call.sid).label("calls"),
                func.avg(Call.duration_sec).label("avg_handle"),
                func.avg(Call.attention_score).label("avg_attention"),
            )
            .group_by(Call.agent_name)
            .order_by(desc("calls"))
            .all()
        )
        # outcomes per agent
        outcome_rows = (
            s.query(Call.agent_name, Call.resolution_status, func.count(Call.sid))
            .group_by(Call.agent_name, Call.resolution_status)
            .all()
        )
    outcomes: dict[str, dict] = {}
    for agent, status, n in outcome_rows:
        outcomes.setdefault(agent, {})[status] = n
    out = []
    for name, calls, avg_handle, avg_att in rows:
        oc = outcomes.get(name, {})
        resolved = oc.get("resolved", 0)
        out.append({
            "agent_name": name,
            "calls": calls,
            "avg_handle_sec": round(float(avg_handle or 0), 1),
            "avg_attention": round(float(avg_att or 0), 1),
            "resolved": resolved,
            "resolution_rate": round(resolved / calls, 3) if calls else 0.0,
            "outcomes": oc,
        })
    return {"agents": out}


@app.get("/api/audio/{filename}")
def audio(filename: str):
    # Prevent path traversal; only serve <sid>.mp3 from the audio dir.
    safe = os.path.basename(filename)
    path = os.path.join(AUDIO_DIR, safe)
    if not safe.endswith(".mp3") or not os.path.exists(path):
        raise HTTPException(404, "audio not found")
    return FileResponse(path, media_type="audio/mpeg")

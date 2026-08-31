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
        "qa_score": c.qa_score,
        "resolution_risk": c.resolution_risk,
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
        "qa": c.qa,
        "qa_score": c.qa_score,
        "resolution_risk": c.resolution_risk,
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
        resolution_risk = s.query(func.count(Call.sid)).filter(Call.resolution_risk == True).scalar() or 0  # noqa: E712
        avg_qa = s.query(func.avg(Call.qa_score)).scalar() or 0
    return {
        "total_calls": total,
        "customers": customers,
        "agents": agents,
        "unresolved": unresolved,
        "high_attention": high_attention,
        "avg_attention": round(float(avg_att), 1),
        "avg_evidence_score": round(float(avg_ev), 3),
        "resolution_risk": resolution_risk,
        "avg_qa_score": round(float(avg_qa), 1),
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


@app.get("/api/qa")
def qa(limit: int = 50, risk_only: bool = True):
    """QA / compliance view: calls ranked by lowest QA score, i.e. the ones a
    manager should coach on or that "sounded resolved but weren't"."""
    with SessionLocal() as s:
        q = s.query(Call)
        if risk_only:
            q = q.filter(Call.resolution_risk == True)  # noqa: E712
        calls = q.order_by(Call.qa_score.asc(), desc(Call.attention_score)).limit(limit).all()
    return {
        "calls": [{**_call_brief(c), "qa": c.qa} for c in calls],
        "count": len(calls),
    }


@app.get("/api/qa/stats")
def qa_stats():
    """Aggregate QA numbers for the dashboard, incl. per-check pass rates."""
    with SessionLocal() as s:
        rows = s.query(Call.qa, Call.qa_score, Call.resolution_risk).all()
    total = len(rows)
    if not total:
        return {"total": 0}
    risk = sum(1 for _qa, _s, r in rows if r)
    avg = round(sum(s or 0 for _qa, s, _r in rows) / total, 1)
    # per-check pass rates
    check_agg = {}
    for qa_obj, _s, _r in rows:
        for chk in (qa_obj or {}).get("checks", []):
            if chk.get("weight", 0) == 0:
                continue
            k = chk["key"]
            d = check_agg.setdefault(k, {"label": chk["label"], "pass": 0, "total": 0})
            d["total"] += 1
            d["pass"] += 1 if chk["passed"] else 0
    checks = [
        {"key": k, "label": v["label"], "pass": v["pass"], "total": v["total"],
         "rate": round(v["pass"] / v["total"], 4) if v["total"] else 0.0}
        for k, v in check_agg.items()
    ]
    checks.sort(key=lambda x: x["rate"])
    return {
        "total": total,
        "avg_qa_score": avg,
        "resolution_risk_count": risk,
        "resolution_risk_rate": round(risk / total, 4),
        "checks": checks,
    }


@app.get("/api/evaluation")
def evaluation():
    """System quality metrics, computed live from stored analyses.

    Reports faithfulness (evidence grounding), coverage (well-formedness), and
    the engine mix — the research-grounded way to show the system is measured,
    not merely asserted. Diarization/human-validation come from the offline
    report if present.
    """
    import json as _json
    MOOD_VOCAB = {"very_negative", "negative", "neutral", "positive", "very_positive"}
    RES_VOCAB = {"resolved", "unresolved", "partially_resolved", "escalated", "unclear"}

    with SessionLocal() as s:
        calls = s.query(
            Call.analysis, Call.summary, Call.transcript, Call.analysis_engine
        ).all()

    total = len(calls)
    jt = jv = 0
    per_field = {k: [0, 0] for k in ["intent", "mood", "resolution", "attention"]}
    cov = Counter()
    engines = Counter()

    for analysis, summary, transcript, engine in calls:
        a = analysis or {}
        engines[(engine or "unknown").split(":")[0]] += 1

        def tally(field, ev):
            nonlocal jt, jv
            if isinstance(ev, dict):
                per_field[field][1] += 1
                jt += 1
                if ev.get("verified"):
                    per_field[field][0] += 1
                    jv += 1

        tally("intent", a.get("intent", {}).get("evidence"))
        mood = a.get("mood", {})
        tally("mood", (mood.get("shift") or {}).get("evidence") if mood.get("shifted")
              else mood.get("start_evidence"))
        tally("resolution", a.get("resolution", {}).get("evidence"))
        tally("attention", a.get("attention", {}).get("evidence"))

        if a.get("intent", {}).get("summary"):
            cov["has_intent"] += 1
        if mood.get("start") in MOOD_VOCAB and mood.get("end") in MOOD_VOCAB:
            cov["mood_in_vocab"] += 1
        if a.get("resolution", {}).get("status") in RES_VOCAB:
            cov["resolution_in_vocab"] += 1
        if summary and len(summary.split()) <= 40:
            cov["summary_within_40w"] += 1
        sc = a.get("attention", {}).get("score")
        if isinstance(sc, (int, float)) and 0 <= sc <= 100:
            cov["attention_in_range"] += 1
        if not mood.get("shifted") or (mood.get("shift") or {}).get("timestamp"):
            cov["shift_ts_when_shifted"] += 1
        if (transcript or {}).get("turns"):
            cov["has_transcript"] += 1

    faithfulness = {
        "judgments_total": jt,
        "judgments_verified": jv,
        "rate": round(jv / jt, 4) if jt else 0.0,
        "per_field": {
            k: {"verified": v[0], "total": v[1], "rate": round(v[0] / v[1], 4) if v[1] else 0.0}
            for k, v in per_field.items()
        },
    }
    coverage = {k: {"count": v, "rate": round(v / total, 4) if total else 0.0} for k, v in cov.items()}

    # Pull diarization + human-validation from the offline report if it exists.
    diarization = human = None
    data_dir = os.path.dirname(os.getenv("CALLRADAR_ANALYSIS_DIR", "/data/analysis").rstrip("/"))
    report_path = os.path.join(data_dir, "eval", "report.json")
    try:
        with open(report_path, encoding="utf-8") as f:
            rep = _json.load(f)
            diarization = rep.get("diarization")
            human = rep.get("human_validation")
    except Exception:
        pass

    return {
        "total_calls": total,
        "engines": dict(engines),
        "faithfulness": faithfulness,
        "coverage": coverage,
        "diarization": diarization,
        "human_validation": human,
    }


@app.get("/api/audio/{filename}")
def audio(filename: str):
    # Prevent path traversal; only serve <sid>.mp3 from the audio dir.
    safe = os.path.basename(filename)
    path = os.path.join(AUDIO_DIR, safe)
    if not safe.endswith(".mp3") or not os.path.exists(path):
        raise HTTPException(404, "audio not found")
    return FileResponse(path, media_type="audio/mpeg")

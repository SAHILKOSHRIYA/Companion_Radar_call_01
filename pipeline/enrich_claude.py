"""Second-pass enrichment: re-analyse the highest-attention calls with Claude.

The base batch runs a fast, offline engine so it always completes. This pass
upgrades the calls that actually matter — the ones a manager will open first —
to Claude's sharper reasoning and genuine, verified evidence citations.

    python -m pipeline.enrich_claude --top 100

Requires ANTHROPIC_API_KEY. Reads the already-transcribed calls straight from
the database (no re-transcription), re-runs analysis with Claude, re-verifies
the evidence, and updates the row in place.
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .analyze import _analyze_claude, verify_evidence


def _update_row(sid: str, analysis: dict) -> None:
    from sqlalchemy import update
    from backend.app.models.db import Call, SessionLocal

    with SessionLocal() as s:
        c = s.get(Call, sid)
        if not c:
            return
        analysis = verify_evidence(analysis, c.transcript)
        s.execute(
            update(Call).where(Call.sid == sid).values(
                analysis=analysis,
                intent_summary=analysis.get("intent", {}).get("summary", c.intent_summary),
                intent_category=analysis.get("intent", {}).get("category", c.intent_category),
                mood_start=analysis.get("mood", {}).get("start", c.mood_start),
                mood_end=analysis.get("mood", {}).get("end", c.mood_end),
                mood_shifted=analysis.get("mood", {}).get("shifted", c.mood_shifted),
                mood_shift_at=(analysis.get("mood", {}).get("shift") or {}).get("timestamp", c.mood_shift_at),
                resolution_status=analysis.get("resolution", {}).get("status", c.resolution_status),
                summary=analysis.get("summary", c.summary),
                attention_score=int(analysis.get("attention", {}).get("score", c.attention_score)),
                topics=analysis.get("topics", c.topics),
                analysis_engine=analysis.get("_engine", "claude"),
                evidence_score=float(analysis.get("evidence_score", c.evidence_score)),
            )
        )
        s.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-analyse top-attention calls with Claude")
    ap.add_argument("--top", type=int, default=100, help="how many highest-attention calls to enrich")
    args = ap.parse_args()

    if not config.ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY is not set — cannot run Claude enrichment.")
        return 1

    from sqlalchemy import desc
    from backend.app.models.db import Call, SessionLocal

    with SessionLocal() as s:
        rows = (
            s.query(Call.sid, Call.customer_name, Call.agent_name, Call.transcript_text)
            .order_by(desc(Call.attention_score))
            .limit(args.top)
            .all()
        )

    print(f"Enriching {len(rows)} top-attention calls with {config.CLAUDE_MODEL}...")
    ok = err = 0
    for i, (sid, customer, agent, ttext) in enumerate(rows, 1):
        try:
            analysis = _analyze_claude(customer, agent, ttext)
            _update_row(sid, analysis)
            ok += 1
            print(f"[{i}/{len(rows)}] OK  {sid}  {customer}", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"[{i}/{len(rows)}] ERR {sid}: {type(e).__name__}: {e}", flush=True)

    print(f"\nDone. Enriched: {ok}  Errors: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

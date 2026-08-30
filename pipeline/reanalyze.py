"""Re-run analysis over already-transcribed calls — no re-transcription.

Transcription is the slow part; analysis is cheap. When you tune the analysis
logic (or switch engines), this re-scores every call in the database in seconds
using the transcripts already stored, and updates the rows in place.

    python -m pipeline.reanalyze              # re-analyse everything
    python -m pipeline.reanalyze --limit 50   # just the first 50
"""
from __future__ import annotations

import argparse
import sys

from .analyze import analyze_call
from .transcribe import transcript_to_text


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-analyse stored transcripts")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from sqlalchemy import update
    from backend.app.models.db import Call, SessionLocal, init_db

    init_db()
    with SessionLocal() as s:
        q = s.query(Call.sid)
        if args.limit:
            q = q.limit(args.limit)
        sids = [r[0] for r in q.all()]

    print(f"Re-analysing {len(sids)} calls (reusing stored transcripts)...")
    ok = err = 0
    for i, sid in enumerate(sids, 1):
        try:
            with SessionLocal() as s:
                c = s.get(Call, sid)
                if not c or not c.transcript:
                    continue
                ttext = c.transcript_text or transcript_to_text(c.transcript)
                analysis = analyze_call(c.customer_name, c.agent_name, c.transcript, ttext)
                s.execute(update(Call).where(Call.sid == sid).values(
                    analysis=analysis,
                    intent_summary=analysis.get("intent", {}).get("summary", ""),
                    intent_category=analysis.get("intent", {}).get("category", "other"),
                    mood_start=analysis.get("mood", {}).get("start", "neutral"),
                    mood_end=analysis.get("mood", {}).get("end", "neutral"),
                    mood_shifted=analysis.get("mood", {}).get("shifted", False),
                    mood_shift_at=(analysis.get("mood", {}).get("shift") or {}).get("timestamp", ""),
                    resolution_status=analysis.get("resolution", {}).get("status", "unclear"),
                    summary=analysis.get("summary", ""),
                    attention_score=int(analysis.get("attention", {}).get("score", 0)),
                    topics=analysis.get("topics", []),
                    analysis_engine=analysis.get("_engine", ""),
                    evidence_score=float(analysis.get("evidence_score", 0.0)),
                ))
                s.commit()
            ok += 1
            if i % 100 == 0 or i == len(sids):
                print(f"  {i}/{len(sids)}", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  ERR {sid}: {type(e).__name__}: {e}", flush=True)

    print(f"Done. Re-analysed: {ok}  Errors: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

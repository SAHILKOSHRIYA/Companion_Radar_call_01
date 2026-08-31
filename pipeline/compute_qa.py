"""Compute QA / compliance scores for every call from stored transcripts.

No re-transcription, no LLM calls — deterministic and offline. Adds the QA
columns to the DB if they don't exist yet (lightweight migration), then scores
each call and stores the result.

    python -m pipeline.compute_qa
"""
from __future__ import annotations

import sys

from sqlalchemy import text, update

from .qa import score_qa


DDL = [
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS qa_score INTEGER DEFAULT 100",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS qa JSON DEFAULT '{}'::json",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS resolution_risk BOOLEAN DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS ix_calls_qa_score ON calls (qa_score)",
    "CREATE INDEX IF NOT EXISTS ix_calls_resolution_risk ON calls (resolution_risk)",
]


def _migrate(engine):
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))


def main() -> int:
    from backend.app.models.db import Call, SessionLocal, engine, init_db
    init_db()
    _migrate(engine)

    with SessionLocal() as s:
        sids = [r[0] for r in s.query(Call.sid).all()]

    print(f"Computing QA for {len(sids)} calls...")
    ok = err = risk = 0
    for i, sid in enumerate(sids, 1):
        try:
            with SessionLocal() as s:
                c = s.get(Call, sid)
                if not c or not c.transcript:
                    continue
                qa = score_qa(c.transcript, c.analysis or {})
                s.execute(update(Call).where(Call.sid == sid).values(
                    qa=qa,
                    qa_score=int(qa["qa_score"]),
                    resolution_risk=bool(qa["resolution_risk"]),
                ))
                s.commit()
            ok += 1
            if qa["resolution_risk"]:
                risk += 1
            if i % 200 == 0 or i == len(sids):
                print(f"  {i}/{len(sids)}", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  ERR {sid}: {type(e).__name__}: {e}", flush=True)

    print(f"Done. Scored: {ok}  Errors: {err}  Resolution-risk calls: {risk}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

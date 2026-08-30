"""Batch pipeline: recordings -> transcript -> analysis -> database.

This is THE step the brief asks judges to be able to run from scratch:
    python -m pipeline.run

For each call it:
  1. loads metadata (customer, agent, timestamps),
  2. transcribes the stereo mp3 (channel-split diarization),
  3. analyzes the transcript (evidence-cited),
  4. writes a JSON artifact to data/analysis/<sid>.json,
  5. upserts a row into Postgres.

It is resumable (skips calls already in the DB unless --force), parallelised
across processes, and never lets one bad call abort the whole run.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .transcribe import transcribe_call, transcript_to_text
from .analyze import analyze_call


def _load_metadata(sid: str) -> dict | None:
    p = config.METADATA_DIR / f"{sid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _ms_to_dt(ms) -> datetime | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def process_one(sid: str) -> dict:
    """Full pipeline for a single call. Returns a record dict (never raises)."""
    try:
        meta = _load_metadata(sid)
        if meta is None:
            return {"sid": sid, "error": "metadata missing"}

        customer = (meta.get("caller", {}).get("metadata", {}) or {}).get("first and last name", "Unknown Customer")
        agent = (meta.get("agent", {}).get("metadata", {}) or {}).get("agent_name", "Unknown Agent")

        mp3 = config.AUDIO_DIR / f"{sid}.mp3"
        transcript = transcribe_call(mp3)
        transcript_text = transcript_to_text(transcript)

        analysis = analyze_call(customer, agent, transcript, transcript_text)

        record = {
            "sid": sid,
            "customer_name": customer,
            "agent_name": agent,
            "session_label": meta.get("session"),
            "started_at": _ms_to_dt(meta.get("start_time_ms")),
            "ended_at": _ms_to_dt(meta.get("end_time_ms")),
            "duration_sec": transcript["duration"],
            "transcript": transcript,
            "transcript_text": transcript_text,
            "stt_engine": transcript["engine"],
            "analysis": analysis,
            "intent_summary": analysis.get("intent", {}).get("summary", ""),
            "intent_category": analysis.get("intent", {}).get("category", "other"),
            "mood_start": analysis.get("mood", {}).get("start", "neutral"),
            "mood_end": analysis.get("mood", {}).get("end", "neutral"),
            "mood_shifted": analysis.get("mood", {}).get("shifted", False),
            "mood_shift_at": (analysis.get("mood", {}).get("shift") or {}).get("timestamp", ""),
            "resolution_status": analysis.get("resolution", {}).get("status", "unclear"),
            "summary": analysis.get("summary", ""),
            "attention_score": int(analysis.get("attention", {}).get("score", 0)),
            "topics": analysis.get("topics", []),
            "analysis_engine": analysis.get("_engine", ""),
            "evidence_score": float(analysis.get("evidence_score", 0.0)),
        }

        # Persist a JSON artifact regardless of DB availability.
        config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        (config.ANALYSIS_DIR / f"{sid}.json").write_text(
            json.dumps({**record, "started_at": _iso(record["started_at"]),
                        "ended_at": _iso(record["ended_at"])}, indent=2),
            encoding="utf-8",
        )
        return record
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None


def _upsert(record: dict) -> None:
    """Write one record to Postgres (import DB lazily so transcription-only
    runs don't require a database)."""
    from sqlalchemy.dialects.postgresql import insert
    from backend.app.models.db import Call, SessionLocal, init_db

    init_db()
    cols = {k: v for k, v in record.items() if k not in ("error", "trace")}
    with SessionLocal() as s:
        stmt = insert(Call).values(**cols)
        stmt = stmt.on_conflict_do_update(index_elements=["sid"], set_=cols)
        s.execute(stmt)
        s.commit()


def _existing_sids() -> set[str]:
    try:
        from backend.app.models.db import Call, SessionLocal, init_db
        init_db()
        with SessionLocal() as s:
            return {row[0] for row in s.query(Call.sid).all()}
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description="CallRadar batch pipeline")
    ap.add_argument("--limit", type=int, default=0, help="process at most N calls (0 = all)")
    ap.add_argument("--workers", type=int, default=config.PIPELINE_WORKERS)
    ap.add_argument("--force", action="store_true", help="reprocess calls already in the DB")
    ap.add_argument("--no-db", action="store_true", help="write JSON artifacts only, skip the database")
    ap.add_argument("--only", type=str, default="", help="comma-separated sids to process")
    args = ap.parse_args()

    all_sids = sorted(p.stem for p in config.METADATA_DIR.glob("*.json"))
    if args.only:
        wanted = set(args.only.split(","))
        all_sids = [s for s in all_sids if s in wanted]

    if not args.force and not args.no_db:
        done = _existing_sids()
        all_sids = [s for s in all_sids if s not in done]
        if done:
            print(f"Skipping {len(done)} already-processed calls (use --force to redo).")

    if args.limit:
        all_sids = all_sids[: args.limit]

    total = len(all_sids)
    print(f"Processing {total} calls with {args.workers} worker(s). Engine: {config.ANALYSIS_ENGINE}")
    if total == 0:
        print("Nothing to do.")
        return 0

    ok = err = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one, sid): sid for sid in all_sids}
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            sid = rec["sid"]
            if "error" in rec:
                err += 1
                print(f"[{i}/{total}] ERR {sid}: {rec['error']}", flush=True)
                continue
            if not args.no_db:
                try:
                    _upsert(rec)
                except Exception as e:  # noqa: BLE001
                    err += 1
                    print(f"[{i}/{total}] DB-ERR {sid}: {e}", flush=True)
                    continue
            ok += 1
            eng = rec.get("analysis_engine", "?")
            att = rec.get("attention_score", 0)
            print(f"[{i}/{total}] OK  {sid}  {rec['customer_name']:<22} "
                  f"att={att:>3} ev={rec['evidence_score']:.2f} [{eng}]", flush=True)

    print(f"\nDone. Success: {ok}  Errors: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

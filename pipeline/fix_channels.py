"""Correct reversed-channel speaker labels on stored transcripts.

A small minority of recordings came off the phone system with the stereo
channels reversed (customer on the left, agent on the right). This detects that
from the transcript content (the agent speaks the bank script) and swaps the
speaker labels in place — no re-transcription. Then it re-runs analysis + QA on
just the corrected calls so their intelligence reflects the right speakers.

    python -m pipeline.fix_channels
"""
from __future__ import annotations

import sys

from sqlalchemy import update

from .transcribe import _score_agentness, transcript_to_text
from .analyze import analyze_call
from .qa import score_qa


def _needs_swap(turns: list[dict]) -> bool:
    agent_text = " ".join(t["text"].lower() for t in turns if t["speaker"] == "agent")
    cust_text = " ".join(t["text"].lower() for t in turns if t["speaker"] == "customer")
    if not agent_text or not cust_text:
        return False
    return _score_agentness(cust_text) >= _score_agentness(agent_text) + 2


def main() -> int:
    from backend.app.models.db import Call, SessionLocal, init_db
    init_db()

    with SessionLocal() as s:
        sids = [r[0] for r in s.query(Call.sid).all()]

    print(f"Scanning {len(sids)} calls for reversed channels...")
    swapped = err = 0
    for i, sid in enumerate(sids, 1):
        try:
            with SessionLocal() as s:
                c = s.get(Call, sid)
                if not c or not c.transcript:
                    continue
                turns = c.transcript.get("turns", [])
                if not _needs_swap(turns):
                    continue

                # Swap labels in place.
                for t in turns:
                    t["speaker"] = "customer" if t["speaker"] == "agent" else "agent"
                transcript = dict(c.transcript)
                transcript["turns"] = turns
                transcript["channels_corrected"] = True
                ttext = transcript_to_text(transcript)

                # Re-run analysis + QA so the intelligence matches the fix.
                analysis = analyze_call(c.customer_name, c.agent_name, transcript, ttext)
                qa = score_qa(transcript, analysis)

                s.execute(update(Call).where(Call.sid == sid).values(
                    transcript=transcript,
                    transcript_text=ttext,
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
                    qa=qa, qa_score=int(qa["qa_score"]), resolution_risk=bool(qa["resolution_risk"]),
                ))
                s.commit()
            swapped += 1
            print(f"[{i}/{len(sids)}] corrected {sid}  {c.customer_name}", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"[{i}/{len(sids)}] ERR {sid}: {type(e).__name__}: {e}", flush=True)

    print(f"\nDone. Channels corrected on {swapped} calls. Errors: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

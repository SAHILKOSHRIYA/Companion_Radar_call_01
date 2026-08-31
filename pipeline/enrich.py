"""Engine-agnostic enrichment: re-analyse calls with a high-quality LLM.

Works with any configured engine (azure | claude | ollama). Reads transcripts
already in the database (no re-transcription), re-runs analysis, re-verifies the
evidence, and updates the row in place.

    # enrich the top 300 highest-attention calls with Azure GPT-4o
    ANALYSIS_ENGINE=azure python -m pipeline.enrich --top 300

    # enrich EVERY call, but skip ones already done by a strong engine
    ANALYSIS_ENGINE=azure python -m pipeline.enrich --all --skip-strong

Flags:
    --top N          enrich the N highest-attention calls
    --all            enrich every call
    --skip-strong    skip calls already analysed by azure/claude (saves money on reruns)
    --engine NAME    override ANALYSIS_ENGINE for this run
"""
from __future__ import annotations

import argparse
import os
import sys

STRONG_ENGINES = ("azure:", "azure-claude:", "claude:")


def _is_strong(engine: str | None) -> bool:
    return bool(engine) and engine.startswith(STRONG_ENGINES)


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich stored transcripts with an LLM engine")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--top", type=int, help="enrich the N highest-attention calls")
    g.add_argument("--all", action="store_true", help="enrich every call")
    ap.add_argument("--skip-strong", action="store_true",
                    help="skip calls already analysed by azure/claude")
    ap.add_argument("--engine", type=str, default="",
                    help="override ANALYSIS_ENGINE (azure|claude|ollama)")
    args = ap.parse_args()

    if args.engine:
        os.environ["ANALYSIS_ENGINE"] = args.engine

    # Import AFTER setting the env var so config picks it up.
    from . import config
    from .analyze import analyze_call, _resolve_engine
    from .transcribe import transcript_to_text

    engine = _resolve_engine()
    if engine == "heuristic":
        print("Refusing to 'enrich' with the heuristic engine. Set --engine azure|claude|ollama "
              "or configure AZURE_OPENAI_* / ANTHROPIC_API_KEY.")
        return 1

    # Sanity-check the engine is actually reachable before spending money/time.
    if engine == "azure" and not (config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_KEY):
        print("Azure engine selected but AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY are not set.")
        return 1
    if engine == "azure-claude" and not (config.AZURE_CLAUDE_ENDPOINT and config.AZURE_CLAUDE_KEY):
        print("Azure-Claude engine selected but AZURE_CLAUDE_ENDPOINT / AZURE_CLAUDE_KEY are not set.")
        return 1
    if engine == "claude" and not config.ANTHROPIC_API_KEY:
        print("Claude engine selected but ANTHROPIC_API_KEY is not set.")
        return 1

    from sqlalchemy import update, desc
    from backend.app.models.db import Call, SessionLocal, init_db

    init_db()
    with SessionLocal() as s:
        q = s.query(Call.sid, Call.analysis_engine).order_by(desc(Call.attention_score))
        rows = q.all() if args.all else q.limit(args.top).all()

    todo = [(sid, eng) for sid, eng in rows]
    if args.skip_strong:
        before = len(todo)
        todo = [(sid, eng) for sid, eng in todo if not _is_strong(eng)]
        print(f"--skip-strong: skipping {before - len(todo)} calls already done by a strong engine.")

    print(f"Enriching {len(todo)} calls with engine '{engine}'...")
    ok = err = 0
    tot_prompt = tot_completion = 0
    for i, (sid, _eng) in enumerate(todo, 1):
        try:
            with SessionLocal() as s:
                c = s.get(Call, sid)
                if not c or not c.transcript:
                    continue
                ttext = c.transcript_text or transcript_to_text(c.transcript)
                analysis = analyze_call(c.customer_name, c.agent_name, c.transcript, ttext)
                # If the engine errored and fell back to heuristic, don't overwrite
                # a previously-strong analysis with a weaker one.
                if analysis.get("_engine_error") and _is_strong(_eng):
                    err += 1
                    print(f"[{i}/{len(todo)}] SKIP {sid}: engine error, kept existing strong analysis "
                          f"({analysis['_engine_error']})", flush=True)
                    continue
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
                    analysis_engine=analysis.get("_engine", engine),
                    evidence_score=float(analysis.get("evidence_score", 0.0)),
                ))
                s.commit()
            ok += 1
            u = analysis.get("_usage") or {}
            tot_prompt += u.get("prompt_tokens", 0)
            tot_completion += u.get("completion_tokens", 0)
            utxt = (f"  [{u.get('prompt_tokens',0)}+{u.get('completion_tokens',0)} tok]"
                    if u else "")
            print(f"[{i}/{len(todo)}] OK  {sid}  {c.customer_name}{utxt}", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"[{i}/{len(todo)}] ERR {sid}: {type(e).__name__}: {e}", flush=True)
            # Stop early on auth/credit problems — no point burning through the rest.
            msg = str(e).lower()
            if any(w in msg for w in ["credit balance", "insufficient", "quota", "401", "invalid_api", "unauthor"]):
                print("Stopping: the engine reported an auth/credit/quota problem.")
                break

    print(f"\nDone. Enriched: {ok}  Errors/skipped: {err}")

    # Real token usage + full-run extrapolation, so you can decide before --all.
    if ok and (tot_prompt or tot_completion):
        avg_p = tot_prompt / ok
        avg_c = tot_completion / ok
        total_calls = 1441
        # Optional price knobs ($ per 1M tokens). Set AZURE_PRICE_IN / AZURE_PRICE_OUT
        # to your model's actual Azure rates for a dollar estimate.
        p_in = float(os.getenv("AZURE_PRICE_IN", "0") or 0)
        p_out = float(os.getenv("AZURE_PRICE_OUT", "0") or 0)
        print("\n--- token usage (measured) ---")
        print(f"  this run: {tot_prompt:,} prompt + {tot_completion:,} completion "
              f"= {tot_prompt + tot_completion:,} tokens over {ok} calls")
        print(f"  average per call: {avg_p:,.0f} prompt + {avg_c:,.0f} completion")
        est_p = avg_p * total_calls
        est_c = avg_c * total_calls
        print(f"  extrapolated to all {total_calls} calls: "
              f"~{est_p/1e6:.2f}M prompt + {est_c/1e6:.2f}M completion tokens")
        if p_in or p_out:
            cost_sample = (tot_prompt * p_in + tot_completion * p_out) / 1e6
            cost_full = (est_p * p_in + est_c * p_out) / 1e6
            print(f"  cost this run: ${cost_sample:.3f}  |  estimated full run: ${cost_full:.2f}")
        else:
            print("  (set AZURE_PRICE_IN / AZURE_PRICE_OUT env vars — $/1M tokens — for a dollar estimate)")

    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""Human-validation labelling tool.

Shows a random sample of calls with the system's analysis and records whether a
human reviewer agrees with each judgment. This produces an honest, defensible
"validated against N human-reviewed calls" number for the evaluation report —
instead of an unverifiable accuracy claim.

    python -m pipeline.label --n 30           # review 30 random calls
    python -m pipeline.label --summary        # print agreement stats from saved labels

Labels are saved to data/eval/human_labels.json and folded into the evaluation
report automatically.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from . import config
LABELS_PATH = config.ANALYSIS_DIR.parent / "eval" / "human_labels.json"
FIELDS = ["intent", "mood", "resolution", "summary", "attention"]


def _load() -> dict:
    if LABELS_PATH.exists():
        return json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    return {}


def _save(labels: dict) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.write_text(json.dumps(labels, indent=2), encoding="utf-8")


def _show_call(c) -> None:
    a = c.analysis or {}
    print("\n" + "=" * 70)
    print(f"CALL {c.sid}  |  {c.customer_name}  ->  agent {c.agent_name}  ({c.duration_sec:.0f}s)")
    print("-" * 70)
    print("TRANSCRIPT:")
    for t in (c.transcript or {}).get("turns", []):
        m, s = divmod(int(t["start"]), 60)
        print(f"  [{m:02d}:{s:02d}] {t['speaker'].upper():8} {t['text']}")
    print("-" * 70)
    print("SYSTEM ANALYSIS:")
    print(f"  intent     : {a.get('intent',{}).get('summary')}  ({a.get('intent',{}).get('category')})")
    mood = a.get("mood", {})
    if mood.get("shifted"):
        print(f"  mood       : {mood.get('start')} -> {mood.get('end')} at {(mood.get('shift') or {}).get('timestamp')}")
    else:
        print(f"  mood       : {mood.get('end')} (steady)")
    print(f"  resolution : {a.get('resolution',{}).get('status')} - {a.get('resolution',{}).get('reason','')}")
    print(f"  summary    : {c.summary}")
    print(f"  attention  : {a.get('attention',{}).get('score')}/100  {a.get('attention',{}).get('reasons')}")
    print(f"  engine     : {a.get('_engine')}")


def review(n: int) -> int:
    from backend.app.models.db import Call, SessionLocal, init_db
    init_db()
    with SessionLocal() as s:
        all_sids = [r[0] for r in s.query(Call.sid).all()]
    labels = _load()
    unlabelled = [sid for sid in all_sids if sid not in labels]
    random.shuffle(unlabelled)
    batch = unlabelled[:n]

    if not batch:
        print("All calls already reviewed, or none available.")
        return 0

    print(f"Reviewing {len(batch)} calls. For each field, does the system judgment look correct?")
    print("Enter: y (agree) / n (disagree) / s (skip field) / q (quit and save)\n")

    from backend.app.models.db import Call, SessionLocal
    for idx, sid in enumerate(batch, 1):
        with SessionLocal() as s:
            c = s.get(Call, sid)
        _show_call(c)
        print(f"\n[{idx}/{len(batch)}] Your judgment:")
        record = {}
        for field in FIELDS:
            while True:
                ans = input(f"  {field:<11} correct? [y/n/s/q]: ").strip().lower()
                if ans in ("y", "n", "s", "q"):
                    break
            if ans == "q":
                labels[sid] = record  # partial
                _save(labels)
                print("Saved. Bye.")
                return 0
            if ans != "s":
                record[field] = (ans == "y")
        labels[sid] = record
        _save(labels)

    print(f"\nSaved {len(batch)} reviews to {LABELS_PATH}")
    _summary()
    return 0


def _summary() -> None:
    labels = _load()
    if not labels:
        print("No human labels yet. Run: python -m pipeline.label --n 30")
        return
    per_field = {f: {"agree": 0, "total": 0} for f in FIELDS}
    for rec in labels.values():
        for f, ok in rec.items():
            per_field[f]["total"] += 1
            per_field[f]["agree"] += 1 if ok else 0
    print(f"\nHUMAN VALIDATION — {len(labels)} calls reviewed")
    for f, v in per_field.items():
        if v["total"]:
            print(f"  {f:<11} {v['agree']}/{v['total']} agree = {v['agree']/v['total']*100:.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description="Human validation labelling")
    ap.add_argument("--n", type=int, default=30, help="how many random calls to review")
    ap.add_argument("--summary", action="store_true", help="print agreement stats and exit")
    args = ap.parse_args()
    if args.summary:
        _summary()
        return 0
    return review(args.n)


if __name__ == "__main__":
    sys.exit(main())

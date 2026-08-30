"""Call analysis with a pluggable engine (Claude default, Ollama fallback,
heuristic last resort) plus evidence verification.

Design goals:
  * Every judgment is grounded in the transcript (see prompts.py).
  * We VERIFY each cited quote against the actual transcript turn at that
    timestamp. If the model's evidence doesn't line up, we flag it — this is
    exactly what the brief penalises, so we surface it rather than trust blindly.
  * The engine is swappable so the whole thing runs from scratch with no API
    keys (Ollama or heuristic), and shines when a key is present (Claude).
"""
from __future__ import annotations

import json
import re

from . import config
from .prompts import SYSTEM_PROMPT, ANALYSIS_SCHEMA, build_user_prompt


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------
def _resolve_engine() -> str:
    if config.ANALYSIS_ENGINE == "claude":
        return "claude"
    if config.ANALYSIS_ENGINE == "ollama":
        return "ollama"
    if config.ANALYSIS_ENGINE == "heuristic":
        return "heuristic"
    # auto
    if config.ANTHROPIC_API_KEY:
        return "claude"
    return "ollama"


# ---------------------------------------------------------------------------
# Claude backend
# ---------------------------------------------------------------------------
def _analyze_claude(customer: str, agent: str, transcript_text: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(customer, agent, transcript_text)}],
        output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    data["_engine"] = f"claude:{config.CLAUDE_MODEL}"
    return data


# ---------------------------------------------------------------------------
# Ollama backend (offline, no key)
# ---------------------------------------------------------------------------
def _analyze_ollama(customer: str, agent: str, transcript_text: str) -> dict:
    import httpx

    prompt = (
        SYSTEM_PROMPT
        + "\n\nReturn ONLY valid JSON matching this schema (no prose, no markdown):\n"
        + json.dumps(ANALYSIS_SCHEMA)
        + "\n\n"
        + build_user_prompt(customer, agent, transcript_text)
    )
    r = httpx.post(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        json={"model": config.OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
        timeout=180,
    )
    r.raise_for_status()
    data = json.loads(r.json()["response"])
    data["_engine"] = f"ollama:{config.OLLAMA_MODEL}"
    return data


# ---------------------------------------------------------------------------
# Heuristic backend — zero dependencies, always available.
# Not as sharp as an LLM but still produces evidence-cited output so the
# system is fully runnable "from scratch" even with no model at all.
# ---------------------------------------------------------------------------
NEG_WORDS = {"angry", "furious", "ridiculous", "unacceptable", "terrible", "worst",
             "frustrated", "annoyed", "upset", "disappointed", "useless", "never",
             "complaint", "escalate", "manager", "cancel", "lawyer", "fraud", "stolen"}
POS_WORDS = {"thank", "thanks", "great", "perfect", "appreciate", "wonderful",
             "helpful", "resolved", "excellent", "happy", "fixed", "sorted"}
RESOLVED_WORDS = {"resolved", "sorted", "fixed", "taken care", "all set", "done",
                  "confirm", "confirmed", "processed", "refunded", "reversed"}
INTENT_KEYWORDS = {
    "card_lost_stolen": ["lost", "stolen", "misplaced my card", "card missing"],
    "fraud_dispute": ["fraud", "unauthorized", "didn't make", "dispute", "scam"],
    "balance_inquiry": ["balance", "how much", "available funds"],
    "transaction_issue": ["transaction", "charge", "payment failed", "declined"],
    "account_access": ["locked out", "password", "log in", "can't access", "reset"],
    "fees_charges": ["fee", "charged", "overdraft", "interest"],
    "payment_transfer": ["transfer", "send money", "wire", "payment to"],
    "loan_mortgage": ["loan", "mortgage", "interest rate", "repayment"],
    "statement_request": ["statement", "records", "history"],
    "complaint": ["complaint", "complain", "unhappy", "unacceptable"],
}


def _analyze_heuristic(customer: str, agent: str, transcript: dict) -> dict:
    turns = transcript["turns"]
    cust_turns = [t for t in turns if t["speaker"] == "customer"]
    text_all = " ".join(t["text"].lower() for t in turns)

    def first_turn_matching(words, speaker=None):
        for t in turns:
            if speaker and t["speaker"] != speaker:
                continue
            low = t["text"].lower()
            for w in words:
                if w in low:
                    return t, w
        return None, None

    # Intent
    category = "other"
    for cat, kws in INTENT_KEYWORDS.items():
        if any(k in text_all for k in kws):
            category = cat
            break
    intent_turn = cust_turns[0] if cust_turns else (turns[0] if turns else None)
    intent_ev = _ev(intent_turn) if intent_turn else _empty_ev()

    # Mood: score first-third vs last-third of customer turns
    def mood_of(chunk):
        neg = sum(1 for t in chunk for w in NEG_WORDS if w in t["text"].lower())
        pos = sum(1 for t in chunk for w in POS_WORDS if w in t["text"].lower())
        if neg > pos and neg >= 1:
            return "negative"
        if pos > neg and pos >= 1:
            return "positive"
        return "neutral"

    n = len(cust_turns)
    start_mood = mood_of(cust_turns[: max(1, n // 3)]) if n else "neutral"
    end_mood = mood_of(cust_turns[-max(1, n // 3):]) if n else "neutral"
    shifted = start_mood != end_mood
    neg_turn, _ = first_turn_matching(NEG_WORDS, speaker="customer")
    pos_turn, _ = first_turn_matching(POS_WORDS, speaker="customer")
    shift_turn = pos_turn if end_mood == "positive" else neg_turn
    start_ev = _ev(cust_turns[0]) if cust_turns else _empty_ev()

    # Resolution
    res_turn, _ = first_turn_matching(RESOLVED_WORDS)
    if res_turn:
        status = "resolved"
    elif any(w in text_all for w in ["escalate", "manager", "supervisor"]):
        status = "escalated"
    else:
        status = "unclear"
    res_ev = _ev(res_turn) if res_turn else (_ev(turns[-1]) if turns else _empty_ev())

    # Attention score
    neg_count = sum(1 for t in cust_turns for w in NEG_WORDS if w in t["text"].lower())
    score = 20
    score += min(40, neg_count * 12)
    if status in ("escalated", "unresolved"):
        score += 25
    if shifted and end_mood == "negative":
        score += 15
    if category in ("fraud_dispute", "card_lost_stolen", "complaint"):
        score += 10
    score = max(0, min(100, score))
    reasons = []
    if neg_count:
        reasons.append(f"{neg_count} negative cue(s) from customer")
    if status in ("escalated", "unresolved"):
        reasons.append(f"call {status}")
    if category in ("fraud_dispute", "card_lost_stolen"):
        reasons.append("high-risk intent")
    if not reasons:
        reasons.append("routine call")

    summary = _heuristic_summary(customer, category, status)

    return {
        "intent": {
            "summary": category.replace("_", " "),
            "category": category,
            "evidence": intent_ev,
        },
        "mood": {
            "start": _norm5(start_mood),
            "end": _norm5(end_mood),
            "shifted": shifted,
            "shift": {
                "from": _norm5(start_mood),
                "to": _norm5(end_mood),
                "timestamp": (shift_turn or (turns[-1] if turns else {"start": 0}))["start"] and
                             _fmt((shift_turn or turns[-1])["start"]) or "00:00",
                "evidence": _ev(shift_turn) if shift_turn else start_ev,
            } if shifted else {
                "from": _norm5(start_mood), "to": _norm5(end_mood),
                "timestamp": "00:00", "evidence": start_ev,
            },
            "start_evidence": start_ev,
        },
        "resolution": {"status": status, "reason": "keyword-based judgment", "evidence": res_ev},
        "summary": summary,
        "attention": {"score": score, "reasons": reasons, "evidence": res_ev},
        "topics": [category.replace("_", " ")],
        "agent_questions_repeated": False,
        "_engine": "heuristic",
    }


def _heuristic_summary(customer: str, category: str, status: str) -> str:
    cat = category.replace("_", " ")
    return f"{customer} contacted support about {cat}. The call was {status.replace('_', ' ')}."[:240]


def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _ev(turn) -> dict:
    if not turn:
        return _empty_ev()
    return {"timestamp": _fmt(turn["start"]), "quote": turn["text"][:200], "speaker": turn["speaker"]}


def _empty_ev() -> dict:
    return {"timestamp": "00:00", "quote": "", "speaker": "customer"}


def _norm5(m: str) -> str:
    return {"negative": "negative", "positive": "positive", "neutral": "neutral"}.get(m, "neutral")


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------
def _turn_at(timestamp: str, turns: list[dict], speaker: str | None = None) -> dict | None:
    """Find the transcript turn at the cited MM:SS.

    When a speaker is given we only consider that speaker's turns — otherwise a
    time near a speaker boundary can match the wrong party. We prefer a turn
    whose [start, end] window actually contains the time, then fall back to the
    nearest turn by start time.
    """
    try:
        mm, ss = timestamp.split(":")
        t = int(mm) * 60 + int(ss)
    except Exception:
        return None

    candidates = [x for x in turns if speaker is None or x["speaker"] == speaker]
    if not candidates:
        candidates = turns

    # 1) window containment (small tolerance)
    contained = [x for x in candidates if x["start"] - 1.5 <= t <= x["end"] + 1.5]
    if contained:
        return min(contained, key=lambda x: abs(x["start"] - t))
    # 2) nearest by start
    return min(candidates, key=lambda x: abs(x["start"] - t), default=None)


def _quote_matches(quote: str, turn: dict | None) -> bool:
    if not turn or not quote:
        return False
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
    q = norm(quote)
    body = norm(turn["text"])
    if q in body:
        return True
    # partial credit: overlap of significant words
    qwords = set(q.split())
    bwords = set(body.split())
    if not qwords:
        return False
    return len(qwords & bwords) / len(qwords) >= 0.6


def verify_evidence(analysis: dict, transcript: dict) -> dict:
    """Walk every evidence object, check the quote lines up with the cited turn,
    and attach a `verified` flag + a top-level evidence_score (0-1).
    """
    turns = transcript["turns"]
    checks = []

    def check(ev):
        if not isinstance(ev, dict):
            return
        turn = _turn_at(ev.get("timestamp", ""), turns, ev.get("speaker"))
        ok = _quote_matches(ev.get("quote", ""), turn)
        # If the speaker-scoped lookup missed, retry without the speaker filter —
        # the model may have labelled the speaker slightly off while the quote
        # and timestamp are still sound.
        if not ok:
            turn2 = _turn_at(ev.get("timestamp", ""), turns, None)
            if turn2 is not turn:
                ok = _quote_matches(ev.get("quote", ""), turn2)
        ev["verified"] = bool(ok)
        checks.append(ok)

    check(analysis.get("intent", {}).get("evidence"))
    check(analysis.get("mood", {}).get("start_evidence"))
    if analysis.get("mood", {}).get("shift"):
        check(analysis["mood"]["shift"].get("evidence"))
    check(analysis.get("resolution", {}).get("evidence"))
    check(analysis.get("attention", {}).get("evidence"))

    analysis["evidence_score"] = round(sum(checks) / len(checks), 3) if checks else 0.0
    analysis["evidence_checks"] = f"{sum(checks)}/{len(checks)}"
    return analysis


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def analyze_call(customer: str, agent: str, transcript: dict, transcript_text: str) -> dict:
    engine = _resolve_engine()
    try:
        if engine == "claude":
            result = _analyze_claude(customer, agent, transcript_text)
        elif engine == "ollama":
            result = _analyze_ollama(customer, agent, transcript_text)
        else:
            result = _analyze_heuristic(customer, agent, transcript)
    except Exception as e:  # noqa: BLE001 - never let one call kill the batch
        # Fall back gracefully so the pipeline always produces *something*.
        result = _analyze_heuristic(customer, agent, transcript)
        result["_engine_error"] = f"{engine}: {type(e).__name__}: {e}"

    result = verify_evidence(result, transcript)
    return result

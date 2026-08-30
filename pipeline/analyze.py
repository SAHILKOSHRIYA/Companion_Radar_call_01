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
    """Analyse a call with Claude, forcing structured output via a tool.

    We define a single tool whose input_schema IS our analysis schema and force
    Claude to call it. Claude then returns the analysis as the tool's input,
    guaranteed to match the schema. This works across anthropic SDK versions
    (no dependency on the newer output_config parameter).
    """
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    tool = {
        "name": "record_call_analysis",
        "description": "Record the structured, evidence-cited analysis of the call.",
        "input_schema": ANALYSIS_SCHEMA,
    }
    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_call_analysis"},
        messages=[{"role": "user", "content": build_user_prompt(customer, agent, transcript_text)}],
    )
    data = next(b.input for b in resp.content if b.type == "tool_use")
    data = dict(data)  # tool_use.input is a plain dict
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

    # Resolution — outcome-based, not just keyword spotting.
    # These calls typically END with the agent completing the task and closing
    # courteously ("your balance is...", "I've ordered your replacement",
    # "your appointment is scheduled", "is there anything else... have a great
    # day"). So we treat a clean close with no friction as RESOLVED, and only
    # step down when there's real evidence of a problem.
    escalated = any(w in text_all for w in ["escalate", "speak to a manager",
                                            "speak to your manager", "supervisor", "complaint"])
    CLOSE_CUES = ["anything else", "have a great day", "have a good day",
                  "thank you for calling", "is that everything", "all set",
                  "you're welcome", "glad to help"]
    ACTION_CUES = ["has been scheduled", "have been transferred", "has been transferred",
                   "your balance is", "i've ordered", "i have ordered", "your new card",
                   "has been processed", "has been reversed", "has been refunded",
                   "i've updated", "i have updated", "confirmed", "your appointment"]
    RESOLVED_WORDS_EXT = RESOLVED_WORDS | {"scheduled", "transferred", "ordered", "updated"}

    last_cust = cust_turns[-1]["text"].lower() if cust_turns else ""
    customer_unhappy_at_end = any(w in last_cust for w in NEG_WORDS) or \
        any(p in last_cust for p in ["still", "not right", "didn't work", "doesn't work",
                                     "that's not", "no that", "call back", "again"])

    res_turn, _ = first_turn_matching(RESOLVED_WORDS_EXT | set(w for c in ACTION_CUES for w in [c]))
    action_turn, _ = first_turn_matching(ACTION_CUES, speaker="agent")
    close_turn, _ = first_turn_matching(CLOSE_CUES, speaker="agent")
    had_close = close_turn is not None
    had_action = action_turn is not None or res_turn is not None

    if escalated:
        status = "escalated"
    elif customer_unhappy_at_end:
        status = "unresolved"
    elif had_action or had_close:
        status = "resolved"
    else:
        status = "unclear"

    # Cite the moment that best supports the resolution judgment.
    res_turn = (action_turn or res_turn or close_turn or (turns[-1] if turns else None))
    res_ev = _ev(res_turn) if res_turn else _empty_ev()

    # Did the agent have to ask the same thing more than once?
    agent_turns = [t for t in turns if t["speaker"] == "agent"]
    repeated = _agent_repeated_question(agent_turns)

    # ---- Attention score: additive signals, tuned for a rankable spread ----
    # Even a benign dataset should separate harder calls from routine ones, so
    # we reward risk, ambiguity, mood trajectory, friction and length — not just
    # explicit anger, which is rare here.
    neg_count = sum(1 for t in cust_turns for w in NEG_WORDS if w in t["text"].lower())
    HIGH_RISK = {"fraud_dispute", "card_lost_stolen", "complaint", "account_access"}
    MED_RISK = {"transaction_issue", "fees_charges", "loan_mortgage", "payment_transfer"}

    score = 10
    reasons = []

    if neg_count:
        score += min(35, neg_count * 12)
        reasons.append(f"{neg_count} negative cue(s) from customer")
    if status == "escalated":
        score += 30; reasons.append("escalated to a manager")
    elif status == "unresolved":
        score += 28; reasons.append("customer left with an unmet need")
    elif status == "unclear":
        score += 15; reasons.append("resolution not confirmed on the call")
    if shifted and end_mood == "negative":
        score += 20; reasons.append("customer mood turned negative")
    elif shifted and end_mood == "positive":
        score -= 5  # recovered — slightly less urgent
    if category in HIGH_RISK:
        score += 22; reasons.append(f"high-risk topic ({category.replace('_',' ')})")
    elif category in MED_RISK:
        score += 10; reasons.append(f"money-related topic ({category.replace('_',' ')})")
    if repeated:
        score += 12; reasons.append("agent had to ask the same question more than once")
    # Longer-than-typical calls tend to signal friction (dataset mean ~57s).
    dur = max((t["end"] for t in turns), default=0.0)
    if dur >= 90:
        score += 10; reasons.append("long call (possible friction)")
    elif dur >= 70:
        score += 5

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("routine call, resolved cleanly")

    summary = _heuristic_summary(customer, category, status, shifted, end_mood)

    # Attention evidence: prefer the moment that best explains the score.
    att_turn = neg_turn or (shift_turn if (shifted and end_mood == "negative") else None) or res_turn
    att_ev = _ev(att_turn) if att_turn else res_ev

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
        "resolution": {"status": status, "reason": _resolution_reason(status, had_action, had_close), "evidence": res_ev},
        "summary": summary,
        "attention": {"score": score, "reasons": reasons, "evidence": att_ev},
        "topics": [category.replace("_", " ")],
        "agent_questions_repeated": repeated,
        "_engine": "heuristic",
    }


def _agent_repeated_question(agent_turns: list[dict]) -> bool:
    """Detect the agent asking the same thing twice — a friction signal.

    We look at the agent's *questions* (turns containing '?') and flag a repeat
    when two of them share most of their significant words.
    """
    import re as _re
    questions = []
    for t in agent_turns:
        for sent in _re.split(r"(?<=[?.])\s+", t["text"]):
            if "?" in sent:
                words = frozenset(_re.sub(r"[^a-z ]", "", sent.lower()).split())
                words = frozenset(w for w in words if len(w) > 3)
                if len(words) >= 2:
                    questions.append(words)
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            a, b = questions[i], questions[j]
            if a and b and len(a & b) / min(len(a), len(b)) >= 0.6:
                return True
    return False


def _resolution_reason(status: str, had_action: bool, had_close: bool) -> str:
    if status == "escalated":
        return "call was escalated to a manager/supervisor"
    if status == "unresolved":
        return "customer still had an unmet need at the end of the call"
    if status == "resolved":
        if had_action:
            return "agent completed the requested action on the call"
        if had_close:
            return "call ended with a normal close and no unresolved issue"
    return "resolution could not be confirmed from the transcript"


def _heuristic_summary(customer: str, category: str, status: str,
                       shifted: bool = False, end_mood: str = "neutral") -> str:
    cat = category.replace("_", " ")
    outcome = {
        "resolved": "and it was resolved on the call",
        "escalated": "and it was escalated to a manager",
        "unclear": "but the resolution was not confirmed on the call",
    }.get(status, "")
    mood_note = ""
    if shifted and end_mood == "negative":
        mood_note = " The customer's mood turned negative during the call."
    elif shifted and end_mood == "positive":
        mood_note = " The customer ended the call more positive than they began."
    return f"{customer} contacted support about {cat} {outcome}.{mood_note}".strip()[:240]


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

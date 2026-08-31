"""QA / compliance scoring — the "sounded resolved but wasn't" intelligence.

The problem statement calls out exactly the failures a support manager can never
catch by hand: *the call that sounded resolved but wasn't*, *the question the
agent had to ask three times*. This module scores every call against a bank-grade
quality rubric, entirely from the transcript, and produces:

  * a 0-100 QA score (higher = better handling),
  * a list of concrete checks (passed / failed) with cited evidence,
  * coaching flags for the manager,
  * a "resolution risk" — did the call *sound* resolved (polite close) while
    lacking the actions that would make it *actually* resolved?

This runs on top of any engine's analysis, using the transcript we already have,
so it works fully offline and is deterministic + explainable.
"""
from __future__ import annotations

import re


def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _ev(turn) -> dict | None:
    if not turn:
        return None
    return {"timestamp": _fmt(turn["start"]), "quote": turn["text"][:200], "speaker": turn["speaker"]}


# Signals -------------------------------------------------------------------
IDENTITY_CUES = [
    "verify your identity", "security question", "date of birth", "your address",
    "last four", "account number", "confirm your", "for security", "memorable",
    "mother's maiden", "postcode", "zip code", "social security", "pin",
]
ACTION_CONFIRM_CUES = [
    "has been", "i've ordered", "i have ordered", "i've processed", "i've updated",
    "i've scheduled", "has been scheduled", "have been transferred", "your balance is",
    "i've cancelled", "i've blocked", "i've reset", "you'll receive", "you will receive",
    "within", "business days", "is now", "i've sent", "confirmation number",
    "reference number", "i've raised", "i've submitted",
]
CLOSE_CUES = [
    "anything else", "have a great day", "have a good day", "thank you for calling",
    "is that everything", "you're welcome", "glad to help", "take care",
]
SECURITY_ACTIONS = [  # genuinely sensitive actions that SHOULD need identity first
    "reset your password", "reset the password", "new card", "replacement card",
    "replace your card", "transfer", "wire", "block your card", "cancel your card",
    "close the account", "close your account", "change your address",
    "change your pin", "order you a", "order a new",
]
EMPATHY_CUES = [
    "sorry", "apologi", "i understand", "i appreciate", "thank you for your patience",
    "i can imagine", "that must be", "happy to help", "of course",
]
DEAD_AIR_HINT = 6.0  # seconds gap that suggests hold/silence friction


def score_qa(transcript: dict, analysis: dict) -> dict:
    turns = transcript.get("turns", [])
    agent_turns = [t for t in turns if t["speaker"] == "agent"]
    cust_turns = [t for t in turns if t["speaker"] == "customer"]
    text_all = " ".join(t["text"].lower() for t in turns)
    agent_text = " ".join(t["text"].lower() for t in agent_turns)

    checks = []

    def check(key, label, passed, evidence=None, weight=1, coaching=None):
        checks.append({
            "key": key, "label": label, "passed": bool(passed),
            "evidence": evidence, "weight": weight, "coaching": coaching,
        })

    def first_turn_with(cues, speaker="agent"):
        for t in turns:
            if speaker and t["speaker"] != speaker:
                continue
            low = t["text"].lower()
            if any(c in low for c in cues):
                return t
        return None

    # 1. Greeting / branding
    greeted = bool(agent_turns) and any(
        w in agent_turns[0]["text"].lower() for w in ["hello", "hi ", "good morning",
        "good afternoon", "thank you for calling", "how can i help", "how may i help"]
    )
    check("greeting", "Agent opened professionally", greeted,
          _ev(agent_turns[0]) if agent_turns else None,
          coaching=None if greeted else "Open with a branded greeting and offer to help.")

    # 2. Identity verification (only expected when a sensitive action occurs)
    needs_identity = any(a in text_all for a in SECURITY_ACTIONS)
    verified_identity = any(c in agent_text for c in IDENTITY_CUES)
    id_turn = first_turn_with(IDENTITY_CUES)
    if needs_identity:
        check("identity_verification",
              "Verified customer identity before a sensitive action",
              verified_identity, _ev(id_turn),
              weight=3,
              coaching=None if verified_identity else
              "A sensitive action (card/password/transfer) happened with no identity check. "
              "This is a compliance and fraud risk.")
    else:
        check("identity_verification", "Identity verification (not required this call)", True, None, weight=0)

    # 3. Action confirmed
    action_turn = first_turn_with(ACTION_CONFIRM_CUES)
    action_confirmed = action_turn is not None
    check("action_confirmed", "Confirmed the action was completed", action_confirmed,
          _ev(action_turn), weight=2,
          coaching=None if action_confirmed else
          "Agent never confirmed the request was actually done — the customer may leave unsure.")

    # 4. Empathy
    showed_empathy = any(c in agent_text for c in EMPATHY_CUES)
    check("empathy", "Acknowledged / showed empathy", showed_empathy,
          _ev(first_turn_with(EMPATHY_CUES)), weight=1,
          coaching=None if showed_empathy else "Acknowledge the customer's situation before solving.")

    # 5. Repeated question (agent asked the same thing more than once)
    repeated = _agent_repeated_question(agent_turns)
    rep_turn = repeated[1] if repeated else None
    check("no_repeated_question", "Did not have to repeat the same question", not (repeated and repeated[0]),
          _ev(rep_turn), weight=1,
          coaching="Agent asked the same thing more than once — listen actively / avoid rework."
          if (repeated and repeated[0]) else None)

    # 6. Proper close
    closed = any(c in agent_text for c in CLOSE_CUES)
    check("proper_close", "Closed the call properly", closed,
          _ev(first_turn_with(CLOSE_CUES)), weight=1,
          coaching=None if closed else "Close by checking for anything else and thanking the customer.")

    # ---- Score ----
    total_w = sum(c["weight"] for c in checks if c["weight"] > 0)
    got_w = sum(c["weight"] for c in checks if c["passed"] and c["weight"] > 0)
    qa_score = round((got_w / total_w) * 100) if total_w else 100

    # ---- Resolution risk: sounded resolved but wasn't ----
    # We only raise the flag on a STRONG signal, so it stays meaningful:
    #   (a) a genuinely sensitive action happened with no identity check, OR
    #   (b) the call closed politely AND the customer had a real request that was
    #       never confirmed as done AND there's no sign it was actually handled.
    res_status = (analysis.get("resolution", {}) or {}).get("status", "unclear")
    customer_asked = len(cust_turns) >= 1 and len(turns) >= 3  # a real interaction
    sounded_resolved = closed and not any(
        w in text_all for w in ["not right", "still", "didn't work", "call back",
                                "again", "no that", "that's wrong"])

    risk_reasons = []
    # (a) compliance risk — the serious one
    if needs_identity and not verified_identity:
        risk_reasons.append("a sensitive action (card / password / transfer) was taken "
                            "without verifying the customer's identity")
    # (b) sounded-resolved-but-wasn't — only when it truly looks unconfirmed
    if sounded_resolved and customer_asked and not action_confirmed and res_status != "resolved":
        risk_reasons.append("the call closed politely but the requested action was "
                            "never confirmed as completed")

    resolution_risk = len(risk_reasons) > 0

    failed_checks = [c for c in checks if not c["passed"] and c["weight"] > 0]
    coaching = [c["coaching"] for c in checks if c.get("coaching")]

    return {
        "qa_score": qa_score,
        "checks": checks,
        "failed_count": len(failed_checks),
        "coaching": coaching,
        "resolution_risk": resolution_risk,
        "resolution_risk_reasons": risk_reasons,
        "identity_required": needs_identity,
        "identity_verified": verified_identity,
        "action_confirmed": action_confirmed,
        "agent_repeated_question": bool(repeated and repeated[0]),
    }


def _agent_repeated_question(agent_turns):
    """Return (True, turn) if the agent asked the same question twice."""
    questions = []
    for t in agent_turns:
        for sent in re.split(r"(?<=[?.])\s+", t["text"]):
            if "?" in sent:
                words = frozenset(w for w in re.sub(r"[^a-z ]", "", sent.lower()).split() if len(w) > 3)
                if len(words) >= 2:
                    questions.append((words, t))
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            a, b = questions[i][0], questions[j][0]
            if a and b and len(a & b) / min(len(a), len(b)) >= 0.6:
                return (True, questions[j][1])
    return (False, None)

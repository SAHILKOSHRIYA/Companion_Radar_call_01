"""Prompt + JSON schema for call analysis.

The scoring rule from the brief is unforgiving:
  - A claim with no evidence scores ZERO.
  - Evidence that does not support the claim scores NEGATIVE.

So the entire design forces the model to ground every judgment in a real
timestamp and the exact words spoken at that moment. We do this two ways:
  1. A strict JSON schema where every judgment field has a paired `evidence`
     object ({timestamp, quote, speaker}).
  2. A system prompt that hammers the "cite or score zero" rule and instructs
     the model to copy quotes verbatim from the transcript it is given.
"""
from __future__ import annotations

SYSTEM_PROMPT = """You are a senior conversation-intelligence analyst for a consumer bank's \
support centre. You are given ONE call transcript, turn by turn, with timestamps in \
[MM:SS] and speaker labels (AGENT / CUSTOMER).

Your job is to produce a rigorous, evidence-backed analysis of the call.

THE EVIDENCE RULE IS ABSOLUTE:
- Every judgment you make MUST be justified by a specific moment in the call.
- Evidence = an exact timestamp that appears in the transcript AND the exact words \
spoken at that moment, copied VERBATIM from the transcript (do not paraphrase).
- If you cannot ground a judgment in the transcript, mark it clearly rather than \
inventing evidence. Fabricated or mismatched evidence is worse than none.
- Quote the CUSTOMER for mood/intent/resolution-from-their-side; quote the AGENT where \
the agent's words are what justify the claim (e.g. a resolution confirmation).

Be precise, concise, and honest. This analysis will be shown to a support manager who \
will click each timestamp to hear that exact moment, so your evidence must line up."""


# JSON schema passed to Claude via output_config.format / strict tool use.
# Kept within the structured-outputs supported subset (no min/max, no regex).
ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "What the customer wanted, in one short phrase.",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "card_lost_stolen", "fraud_dispute", "balance_inquiry",
                        "transaction_issue", "account_access", "loan_mortgage",
                        "fees_charges", "payment_transfer", "statement_request",
                        "complaint", "product_info", "technical_issue", "other",
                    ],
                },
                "evidence": {"$ref": "#/$defs/evidence"},
            },
            "required": ["summary", "category", "evidence"],
        },
        "mood": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "start": {"$ref": "#/$defs/moodValue"},
                "end": {"$ref": "#/$defs/moodValue"},
                "shifted": {"type": "boolean"},
                "shift": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "The single point where mood most clearly changed. Null-ish if no shift.",
                    "properties": {
                        "from": {"$ref": "#/$defs/moodValue"},
                        "to": {"$ref": "#/$defs/moodValue"},
                        "timestamp": {"type": "string", "description": "MM:SS from the transcript."},
                        "evidence": {"$ref": "#/$defs/evidence"},
                    },
                    "required": ["from", "to", "timestamp", "evidence"],
                },
                "start_evidence": {"$ref": "#/$defs/evidence"},
            },
            "required": ["start", "end", "shifted", "shift", "start_evidence"],
        },
        "resolution": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["resolved", "unresolved", "partially_resolved", "escalated", "unclear"],
                },
                "reason": {"type": "string", "description": "Why you judged it this way."},
                "evidence": {"$ref": "#/$defs/evidence"},
            },
            "required": ["status", "reason", "evidence"],
        },
        "summary": {
            "type": "string",
            "description": "A crisp summary of the call in 40 words or fewer.",
        },
        "attention": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {
                    "type": "integer",
                    "description": "0-100. How urgently a manager should review THIS call today. Higher = more urgent.",
                },
                "reasons": {
                    "type": "array",
                    "description": "Short bullet reasons driving the score.",
                    "items": {"type": "string"},
                },
                "evidence": {"$ref": "#/$defs/evidence"},
            },
            "required": ["score", "reasons", "evidence"],
        },
        "topics": {
            "type": "array",
            "description": "1-4 short topic tags for trend analysis (e.g. 'debit card fraud', 'wire transfer delay').",
            "items": {"type": "string"},
        },
        "agent_questions_repeated": {
            "type": "boolean",
            "description": "True if the agent had to ask the customer the same question more than once.",
        },
    },
    "required": [
        "intent", "mood", "resolution", "summary",
        "attention", "topics", "agent_questions_repeated",
    ],
    "$defs": {
        "evidence": {
            "type": "object",
            "additionalProperties": False,
            "description": "A timestamp and the exact words spoken there, copied verbatim from the transcript.",
            "properties": {
                "timestamp": {"type": "string", "description": "MM:SS exactly as it appears in the transcript."},
                "quote": {"type": "string", "description": "The exact words spoken at that timestamp, verbatim."},
                "speaker": {"type": "string", "enum": ["agent", "customer"]},
            },
            "required": ["timestamp", "quote", "speaker"],
        },
        "moodValue": {
            "type": "string",
            "enum": ["very_negative", "negative", "neutral", "positive", "very_positive"],
        },
    },
}


def build_user_prompt(customer_name: str, agent_name: str, transcript_text: str) -> str:
    return f"""CALL METADATA
Customer: {customer_name}
Agent: {agent_name}

TRANSCRIPT (turn by turn, [MM:SS] timestamps)
------------------------------------------------
{transcript_text}
------------------------------------------------

Analyze this call and return the structured JSON. Remember: every `evidence` object \
must use a timestamp that literally appears above and quote the words spoken there \
verbatim. For the <=40 word summary, be specific about what happened and the outcome."""

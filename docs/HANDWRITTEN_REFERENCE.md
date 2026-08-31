# CallRadar — Documentation Reference (for hand-written notes)

Everything on this page is copied from the **actual code** so what you write by hand matches what the system does. Three parts: **(1) architecture diagram**, **(2) formulas & notation**, **(3) code snippets**.

---

## 1. Architecture diagram (draw this by hand)

```
   ┌──────────────────────────────────────────────────────────────┐
   │                     RAW DATA (off the phone)                  │
   │                                                              │
   │     audio/<id>.mp3                 metadata/<id>.json         │
   │   8 kHz  STEREO                    customer name,             │
   │   L = AGENT                        agent name,                │
   │   R = CUSTOMER                     timestamps                 │
   └───────────────┬──────────────────────────┬───────────────────┘
                   │                          │
                   ▼                          │
   ┌───────────────────────────────┐         │
   │  (1) TRANSCRIBE               │         │
   │      transcribe.py            │         │
   │                               │         │
   │   ffmpeg split channels       │         │
   │   ┌─────────┐ ┌─────────┐     │         │
   │   │ L: agent│ │R: cust. │     │         │
   │   └────┬────┘ └────┬────┘     │         │
   │        ▼           ▼          │         │
   │   faster-whisper (each)       │         │
   │        └─── interleave ───┐   │         │
   │        by timestamp       ▼   │         │
   │   turn-by-turn transcript      │         │
   │   + word timings               │         │
   │   + reversed-channel fix       │         │
   └───────────────┬───────────────┘         │
                   │  transcript              │ customer/agent
                   ▼                          ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  (2) ANALYZE   analyze.py     (pluggable engine)              │
   │      claude | azure | azure-claude | ollama | heuristic       │
   │                                                              │
   │   intent · mood + shift · resolution · summary(<=40w)        │
   │   attention score (0-100) · EVIDENCE {ts, quote, speaker}    │
   │                    │                                          │
   │                    ▼                                          │
   │   (2b) VERIFY EVIDENCE  -> each quote checked vs transcript   │
   │        at its timestamp -> evidence_score                     │
   └───────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  (3) QA / COMPLIANCE   qa.py                                  │
   │   identity check? action confirmed? empathy? repeat? close?  │
   │   -> qa_score(0-100) + resolution_risk ("sounded resolved     │
   │      but wasn't")                                             │
   └───────────────┬──────────────────────────────────────────────┘
                   │  write once
                   ▼
        ┌────────────────────────┐
        │   PostgreSQL           │   one table: calls
        │   (transcript +        │   (transcript, analysis, qa)
        │    analysis + qa)      │
        └───────────┬────────────┘
                    │  read only (never re-transcribe)
                    ▼
        ┌────────────────────────┐        ┌────────────────────────┐
        │  FastAPI  (backend/)   │◀──────▶│  React + Vite (web)    │
        │  /api/calls, /qa,      │  /api  │  Command Center, QA,   │
        │  /attention, /eval ... │        │  Customers, Call view  │
        └────────────────────────┘        └────────────────────────┘

   EVALUATE (evaluate.py) reads the DB -> faithfulness, diarization,
   coverage  ->  Quality page.
```

**One-line version of the pipeline (good to memorise):**

```
MP3 (stereo) → split channels → Whisper (per channel) → interleave
            → analyze (intent/mood/resolution/summary/attention + evidence)
            → verify evidence → QA score → Postgres → API → Dashboard
```

---

## 2. Formulas & notation

### 2.1 Diarization — why channels, not guessing

Let a call have two channels: `L` (agent), `R` (customer). We transcribe each
separately, giving turn sets `T_L` and `T_R`. The final transcript is:

```
T  =  sort( T_L ∪ T_R )   ordered by turn.start
```

**Separation quality** — we prove the channels really are separate speakers by
the Pearson correlation `ρ` between the two channels' energy envelopes
`e_L`, `e_R` (100 ms windows):

```
              Σ (e_Lᵢ − ē_L)(e_Rᵢ − ē_R)
   ρ  =  ─────────────────────────────────────
          √[ Σ(e_Lᵢ − ē_L)²  ·  Σ(e_Rᵢ − ē_R)² ]

   separation_quality  =  1 − max(0, ρ)
```

Low (even negative) `ρ` ⇒ the two speakers don't overlap ⇒ attribution is
correct **by construction**. Measured on this dataset: `ρ ≈ −0.13`,
`separation_quality = 1.00` (100%).

### 2.2 Evidence verification & faithfulness (the scoring-critical part)

Each judgment `j` carries evidence `e_j = (timestamp, quote, speaker)`.
Verification: find the transcript turn `τ` at that timestamp+speaker, normalise
both (lowercase, strip punctuation), and accept if the quote appears in the turn
**or** shares ≥ 60% of its significant words:

```
   normalise(s) = lowercase(s) with only [a-z0-9 ]

   verified(e_j) = 1   if  normalise(quote) ⊆ normalise(τ.text)
                       or  |Q ∩ B| / |Q|  ≥  0.60
                   0   otherwise

        where  Q = words(quote),  B = words(τ.text)
```

**Per-call evidence score** (n = number of judgments checked, here n = 4–5):

```
                    1
   evidence_score = ─ · Σ  verified(e_j)
                    n   j
```

**System-wide faithfulness** (over all calls C):

```
                    Σ_c Σ_j verified(e_{c,j})
   faithfulness  =  ─────────────────────────     = 0.999  (99.9%)
                       Σ_c (# judgments in c)
```

### 2.3 Needs-attention score  A ∈ [0, 100]

Additive signals, then clamped. `neg` = # negative cues from the customer;
`status`, `category`, `shifted`, `end_mood`, `repeated`, `dur` (seconds):

```
   A = 10                                   (base)
     + min(35, 12·neg)                      (customer negativity)
     + 30  if status = escalated
       28  if status = unresolved
       15  if status = unclear
     + 20  if shifted and end_mood = negative
       −5  if shifted and end_mood = positive   (recovered)
     + 22  if category ∈ HIGH_RISK
       10  if category ∈ MED_RISK
     + 12  if agent repeated a question
     + 10  if dur ≥ 90    ( 5 if dur ≥ 70 )    (friction / length)

   A = clamp(A, 0, 100)

   HIGH_RISK = {fraud_dispute, card_lost_stolen, complaint, account_access}
   MED_RISK  = {transaction_issue, fees_charges, loan_mortgage, payment_transfer}
```

### 2.4 QA / compliance score  Q ∈ [0, 100]

Each check `k` has a pass flag `p_k ∈ {0,1}` and a weight `w_k`:

| check | weight |
|---|---|
| greeting (opened professionally) | 1 |
| identity verified before sensitive action | 3  (0 if not required this call) |
| action confirmed | 2 |
| empathy shown | 1 |
| no repeated question | 1 |
| proper close | 1 |

```
          Σ_k  p_k · w_k
   Q = ─────────────────── · 100          (over checks with w_k > 0)
            Σ_k  w_k
```

**Resolution risk** ("sounded resolved but wasn't") — a boolean, true iff:

```
   resolution_risk =
        ( sensitive_action ∧ ¬identity_verified )          # compliance risk
      ∨ ( sounded_resolved ∧ customer_asked
          ∧ ¬action_confirmed ∧ status ≠ resolved )        # unconfirmed
```

---

## 3. Code snippets (the essentials)

### 3.1 Channel split (transcribe.py)

```python
# split one stereo channel to 16 kHz mono WAV; c0=c0 = left(agent), c0=c1 = right(customer)
cmd = ["ffmpeg", "-i", str(mp3_path),
       "-af", f"pan=mono|c0=c{channel}",
       "-ar", "16000", "-ac", "1", str(out_wav)]

# transcribe each channel independently, tag the speaker, then interleave
all_turns  = _transcribe_channel(agent_wav, "agent")
all_turns += _transcribe_channel(cust_wav,  "customer")
all_turns.sort(key=lambda t: t.start)          # rebuild the real conversation
```

### 3.2 Forcing evidence-cited JSON from the LLM (analyze.py)

```python
# a tool whose input schema IS the analysis schema → the model must return it,
# and every judgment field REQUIRES an {timestamp, quote, speaker} evidence object
tool = {"name": "record_call_analysis",
        "input_schema": ANALYSIS_SCHEMA}
resp = client.messages.create(
        model=MODEL, tools=[tool],
        tool_choice={"type": "tool", "name": "record_call_analysis"},
        system=SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}])
data = next(b.input for b in resp.content if b.type == "tool_use")
```

### 3.3 Evidence verification (analyze.py)

```python
def _quote_matches(quote, turn):
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
    q, body = norm(quote), norm(turn["text"])
    if q in body:
        return True
    Q, B = set(q.split()), set(body.split())
    return len(Q & B) / len(Q) >= 0.6            # ≥60% word overlap

# evidence_score = fraction of judgments whose quote verified
analysis["evidence_score"] = round(sum(checks) / len(checks), 3)
```

### 3.4 QA score (qa.py)

```python
total_w = sum(c["weight"] for c in checks if c["weight"] > 0)
got_w   = sum(c["weight"] for c in checks if c["passed"] and c["weight"] > 0)
qa_score = round(got_w / total_w * 100) if total_w else 100
```

### 3.5 The required API contract (backend/app/main.py)

```python
GET /api/calls/{sid}   →  { transcript(turns, speakers, timings),
                            intent, mood{start,end,shift{timestamp}},
                            resolution, summary(<=40w),
                            attention{score 0-100}, qa,
                            evidence{timestamp, quote, verified} }
# API only READS Postgres — analysis is precomputed, never re-transcribed.
```

---

### Numbers to quote (from the full 1,441-call run)

```
   calls              1,441
   customers            100
   agents                10
   faithfulness       99.9 %   (evidence verified)
   diarization         100 %   (channel separation)
   coverage            100 %   (well-formed outputs)
   resolution-risk      195    (sounded resolved but wasn't)
```

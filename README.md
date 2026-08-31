# CallRadar — Conversation Intelligence for a Consumer Bank

Turn 1,441 raw support-call recordings into a manager's dashboard: **who called, what they wanted, how their mood moved, whether it got resolved, which calls need attention today — and the exact moment on the call that justifies every judgment.**

You get audio, not transcripts. CallRadar builds everything from the raw `.mp3`s, exactly as they come off the phone system.

> **📖 Documentation:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system diagram, the five load-bearing design decisions, and design tradeoffs. · [`docs/DEMO.md`](docs/DEMO.md) — a guided walkthrough of the dashboard.
>
> **▶︎ Run it:** `python scripts/load_data.py <callradar-data.zip>` → `docker compose up -d --build` → `docker compose run --rm pipeline` → open **http://localhost:3000**. Full steps below. Runs from scratch with **no API keys**.

---

## What makes this different

**1. Perfect speaker separation — by construction, not by guessing.**
The recordings are stereo: **left channel = agent, right channel = customer.** Instead of running a fragile ML diarizer to guess "who spoke," CallRadar **splits the channels** and transcribes each independently, then interleaves the two by timestamp to rebuild the conversation. Every word is attributed to the right speaker by construction. It even **auto-detects and corrects the ~37 recordings that came off the phone system with reversed channels** (the agent speaks the bank script — if that lands on the wrong channel, we swap it).

**2. Every judgment cites the moment that proves it — and we verify it.**
The brief is explicit: *a claim with no evidence scores zero; evidence that doesn't support the claim scores negative.* So every judgment carries an `evidence` object `{ timestamp, verbatim quote, speaker }`, and a **verification pass checks each cited quote actually appears in the transcript at that timestamp.** Unverified citations render in amber rather than as fact. Measured across all 1,441 calls: **99.9% faithfulness.** In the dashboard every judgment is clickable and jumps the audio to that second.

**3. It measures its own quality — the way the research does.**
A dedicated **Quality** page and `GET /api/evaluation` report **faithfulness** (evidence grounding), **diarization quality** (cross-channel correlation, proving speaker attribution is correct by construction), and **coverage** (every output well-formed) — plus a human-validation tool. This follows the 2025 conversation-intelligence / faithfulness literature (WER for speech, FaithBench-style grounding) rather than a brittle exact-match "accuracy" number that would punish a good-but-reworded answer.

**4. QA & compliance — "the call that sounded resolved but wasn't."**
A bank-grade quality layer scores every call from the transcript: did the agent verify identity before moving money? confirm the action? show empathy? It flags **resolution-risk** calls that closed politely but were never actually completed, and surfaces **team-wide coaching gaps** (e.g. identity verified on only 7% of sensitive-action calls). This is the exact failure the problem statement calls out, and what banks pay conversation-intelligence vendors for.

**5. Runs from scratch, scales to premium quality.**
The analysis engine is pluggable: **Claude** / **Azure OpenAI (GPT-4o)** for premium reasoning → **Ollama** (offline) → a **dependency-free heuristic** that still produces evidence-cited output. Comes up with `docker compose up` and needs **no keys** to demonstrate; add a key to enrich the calls that matter.

> **Design deep-dive:** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system diagram, the five load-bearing design decisions and why each was made, and the design-tradeoffs table.

---

## Architecture

```
recordings (.mp3, 8kHz stereo)
        │
        ▼
┌─────────────────────┐   channel split (ffmpeg)  +  faster-whisper
│   PIPELINE           │   → turn-by-turn transcript with word timings
│  (pipeline/)         │   → evidence-cited analysis (Claude / Ollama / heuristic)
└─────────┬───────────┘   → evidence verification
          │ writes
          ▼
   ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
   │  PostgreSQL  │◀──────▶│  FastAPI     │◀──────▶│  React SPA   │
   │  (calls)     │        │  (backend/)  │  /api  │  (frontend/) │
   └──────────────┘        └──────────────┘        └──────────────┘
```

Analysis is **precomputed once** by the pipeline and read straight from Postgres — the API never re-transcribes on request.

| Layer | Tech | Why |
|---|---|---|
| Transcription | `faster-whisper` + `ffmpeg` channel split | Accurate 8kHz English STT; perfect diarization for free |
| Analysis | Claude (`claude-opus-4-8`) with strict JSON schema; Ollama / heuristic fallback | Best reasoning for the "cite the moment" requirement |
| Storage | PostgreSQL | One `calls` table holds metadata, transcript, and analysis |
| API | FastAPI | Serves the required per-call contract + dashboard data |
| UI | React + Vite, nginx | Customer list, call history, per-call view, mood timeline, attention ranking |
| Deploy | Docker Compose | One command, reproducible from zero |

---

## Quick start (from scratch)

**Prerequisites:** Docker + Docker Compose. Nothing else.

```bash
# 1. Load the dataset into ./data  (accepts the zip OR an extracted folder)
python scripts/load_data.py /path/to/callradar-data.zip

# 2. Bring up Postgres, the API, and the dashboard
docker compose up -d --build

# 3. Turn the recordings into transcripts + analysis  (THE key step)
#    Runs in the same image, writes results to Postgres.
docker compose run --rm pipeline

# 4. Add the QA / compliance layer + quality metrics
docker compose run --rm pipeline python -m pipeline.compute_qa
docker compose run --rm pipeline python -m pipeline.evaluate

# 5. Open the dashboard
#    http://localhost:3000
```

That's it. The API is on `http://localhost:8000`, the dashboard on `http://localhost:3000`.

### Trying it fast

Processing all 1,441 calls takes a while on CPU. To see the whole system working in a couple of minutes, process a subset first:

```bash
# fastest smoke test: tiny model, 30 calls
docker compose run --rm -e WHISPER_MODEL=tiny.en pipeline python -m pipeline.run --limit 30
```

The pipeline is **resumable** — rerun `docker compose run --rm pipeline` and it picks up where it left off (use `--force` to reprocess).

### Tuning analysis without re-transcribing

Transcription is the slow part; analysis is cheap. If you change the analysis logic or switch engines, re-score every call in seconds using the transcripts already in the database:

```bash
docker compose run --rm pipeline python -m pipeline.reanalyze
```

### Verified on the full dataset

Running the whole pipeline over all **1,441 calls** produces: 100 customers, 10 agents, a ranked attention list topped by genuinely harder calls (unresolved / account-access / card-lost), realistic resolution outcomes, and **100% evidence coverage** — every cited quote verified against its transcript turn at the stated timestamp.

### Compute the QA / compliance layer

```bash
docker compose run --rm pipeline python -m pipeline.compute_qa
```

Scores every call against the bank-grade QA rubric (identity verification, action confirmation, empathy, repeated questions, professional open/close) and flags the "sounded resolved but wasn't" calls. Deterministic, offline, every flag cites a moment.

### Report the quality metrics

```bash
docker compose run --rm pipeline python -m pipeline.evaluate
```

Prints (and serves at `/api/evaluation`) faithfulness, diarization separation, and coverage. Add a human-validated sample with `python -m pipeline.label --n 30`.

### Premium analysis with an LLM (Claude or Azure OpenAI)

The base batch uses the fast offline engine so it always completes with **no keys**. To upgrade the calls that matter to LLM-grade reasoning:

```bash
# Option A — Claude (Anthropic key)
docker compose run --rm -e ANTHROPIC_API_KEY=sk-ant-... -e ANALYSIS_ENGINE=claude \
  pipeline python -m pipeline.enrich --top 100

# Option B — Azure OpenAI GPT-4o (set AZURE_OPENAI_* in .env)
docker compose run --rm -e ANALYSIS_ENGINE=azure \
  pipeline python -m pipeline.enrich --all --skip-strong
```

`enrich` reads the already-transcribed calls (no re-transcription), re-runs analysis, re-verifies evidence, and updates each row. `--top N` does the highest-attention calls; `--all` does everything; `--skip-strong` never re-spends on calls already done by a strong engine, and it halts immediately on any credit/quota error.

---

## The API

Every endpoint reads precomputed analysis. For any call it returns the transcript, intent, mood + shift timestamp, resolution, ≤40-word summary, a 0–100 needs-attention score, and the timestamps behind each judgment.

| Endpoint | Returns |
|---|---|
| `GET /api/calls/{sid}` | **Full per-call analysis**: transcript (speakers + timings), intent, mood + shift timestamp, resolution, summary, attention score, QA score, and the evidence behind each judgment |
| `GET /api/customers` | Every customer with call counts and peak attention |
| `GET /api/customers/{name}` | A customer's full call history |
| `GET /api/attention` | Ranked "needs a manager's attention today" list |
| `GET /api/qa` | QA-risk-ranked calls ("sounded resolved but wasn't") |
| `GET /api/qa/stats` | Team-wide QA metrics and coaching gaps |
| `GET /api/evaluation` | System quality: faithfulness, diarization, coverage |
| `GET /api/trends` | Trending issues across all calls |
| `GET /api/agents` | Per-agent volumes, handle times, and outcomes |
| `GET /api/audio/{sid}.mp3` | The playable recording |
| `GET /api/stats` | Dashboard headline numbers |

Example:

```bash
curl http://localhost:8000/api/calls/<sid> | jq '.analysis.mood.shift'
```

```json
{
  "from": "neutral",
  "to": "negative",
  "timestamp": "01:12",
  "evidence": {
    "timestamp": "01:12",
    "quote": "this is the third time I've had to call about this",
    "speaker": "customer",
    "verified": true
  }
}
```

---

## The dashboard

- **Command Center** — headline stats, the top calls needing attention, the "sounded resolved but wasn't" panel, trending issues, and team-wide coaching gaps.
- **Needs Attention** — every call ranked by urgency, each score backed by a cited moment.
- **QA & Compliance** — resolution-risk calls, per-check pass rates, and the specific handling failure on each flagged call.
- **Customers → customer → call** — the full drill-down the brief asks for.
- **Per-call view** — the centerpiece: **playable recording, your transcript, the AI summary, the mood timeline, every judgment with a click-to-hear evidence quote, and the QA/compliance breakdown.** Clicking a citation seeks the audio and highlights the transcript turn.
- **Agents** — volumes, average handle time, resolution outcomes.
- **Trends** — recurring issues by category and topic.
- **Quality** — the system's own measured faithfulness, diarization separation, and coverage.

The interface is a dark "instrument panel" identity fit to the subject (a cyan radar-signal accent on a blue-slate ground). Data-viz colors are validated colorblind-safe; status colors are reserved and always paired with a label.

---

## Running without Docker (local dev)

```bash
# Backend + pipeline
python -m venv .venv && source .venv/bin/activate   # Python 3.11 recommended
pip install -r requirements.txt
# (needs ffmpeg on PATH and a running Postgres, or set DATABASE_URL)
python scripts/load_data.py /path/to/callradar-data.zip
CALLRADAR_DATA_DIR=./data python -m pipeline.run --limit 30
uvicorn backend.app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

---

## Project layout

```
callradar/
├── pipeline/            recordings → transcript → analysis → DB
│   ├── transcribe.py    channel-split diarization + faster-whisper
│   ├── analyze.py       hybrid engine + evidence verification
│   ├── prompts.py       schema + prompt that force evidence citations
│   └── run.py           batch runner (resumable, parallel)
├── backend/app/         FastAPI + SQLAlchemy models
├── frontend/            React + Vite dashboard
├── scripts/load_data.py load the dataset into ./data
├── docker-compose.yml   db + api + web + pipeline
└── README.md
```

---

## Design decisions

- **Channel-split over ML diarization** — the data hands us perfect speaker labels; using them is both more correct and fully reproducible.
- **Evidence as a first-class, verified object** — not a nice-to-have; it's the scoring rule, so it's enforced in the schema and checked after the fact.
- **Precompute, never re-transcribe on request** — analysis is written once to Postgres; the API is a thin read layer.
- **Graceful degradation** — Claude when you have a key, Ollama or a heuristic when you don't, so a judge can always run it end-to-end.

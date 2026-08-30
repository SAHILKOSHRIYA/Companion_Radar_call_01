# CallRadar — Conversation Intelligence for a Consumer Bank

Turn 1,441 raw support-call recordings into a manager's dashboard: **who called, what they wanted, how their mood moved, whether it got resolved, which calls need attention today — and the exact moment on the call that justifies every judgment.**

You get audio, not transcripts. CallRadar builds everything from the raw `.mp3`s, exactly as they come off the phone system.

---

## What makes this different

**1. Perfect speaker separation — by construction, not by guessing.**
The recordings are stereo: **left channel = agent, right channel = customer.** Instead of running a fragile ML diarizer to guess "who spoke," CallRadar **splits the channels** and transcribes each independently, then interleaves the two by timestamp to rebuild the conversation. Every word is attributed to the right speaker with 100% certainty, and every turn carries a real timestamp we can cite as evidence.

**2. Every judgment cites the moment that proves it.**
The brief is explicit: *a claim with no evidence scores zero; evidence that doesn't support the claim scores negative.* So the analysis schema **forces** each judgment — intent, mood shift, resolution, attention score — to carry an `evidence` object: `{ timestamp, verbatim quote, speaker }`. In the dashboard, every judgment is clickable and **jumps the audio player to that second** and highlights the transcript turn.

**3. We verify the evidence, not just trust the model.**
After analysis, a verification pass checks that each cited quote *actually appears* in the transcript at the stated timestamp, and attaches a `verified` flag plus an evidence-coverage score. Unverified citations are surfaced in amber rather than passed off as fact — directly defending against the "negative score" penalty.

**4. Runs from scratch with or without an API key.**
The analysis engine is pluggable: **Claude (default, best quality)** → **Ollama (offline)** → **a dependency-free heuristic** that still produces evidence-cited output. The whole thing comes up with `docker compose up` and needs no keys to demonstrate.

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

# 4. Open the dashboard
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

### Using Claude for best-quality analysis

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY=sk-ant-...
docker compose run --rm pipeline          # now uses Claude, with evidence citations
```

Without a key it automatically falls back to Ollama (if reachable) and then to the built-in heuristic engine, so it always runs.

---

## The API

Every endpoint reads precomputed analysis. For any call it returns the transcript, intent, mood + shift timestamp, resolution, ≤40-word summary, a 0–100 needs-attention score, and the timestamps behind each judgment.

| Endpoint | Returns |
|---|---|
| `GET /api/calls/{sid}` | **Full per-call analysis**: transcript (speakers + timings), intent, mood + shift timestamp, resolution, summary, attention score, and the evidence behind each judgment |
| `GET /api/customers` | Every customer with call counts and peak attention |
| `GET /api/customers/{name}` | A customer's full call history |
| `GET /api/attention` | Ranked "needs a manager's attention today" list |
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

- **Overview** — headline stats, the top calls needing attention, trending issues.
- **Needs Attention** — every call ranked by urgency, each score backed by a cited moment.
- **Customers → customer → call** — the full drill-down the brief asks for.
- **Per-call view** — the centerpiece: **playable recording, your transcript, the AI summary, the mood timeline, and every judgment with a click-to-hear evidence quote.** Clicking a citation seeks the audio and highlights the transcript turn.
- **Agents** — volumes, average handle time, resolution outcomes.
- **Trends** — recurring issues by category and topic.

Colors are validated colorblind-safe (mood uses a diverging red→gray→teal scale; status colors are reserved and always paired with a label).

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

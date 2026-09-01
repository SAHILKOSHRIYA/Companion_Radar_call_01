# Companion for CallRadar — Architecture Overview

A layered view of the system, stage by stage, with the clean data flow and the naming used across the codebase.

**Team:** Sahil Koshriya · Sakshi

---

## Layered structure

### 1. Data Ingestion Layer — *Raw Call Data*

```text
RAW CALL DATA
│
├── Audio
│   └── audio/<call_id>.mp3
│       ├── 8 kHz
│       ├── Stereo
│       ├── Left  → Agent
│       └── Right → Customer
│
└── Metadata
    └── metadata/<call_id>.json
        ├── Customer Name
        ├── Agent Name
        └── Timestamps
```

### 2. Speech Processing Layer — *Speech-to-Text & Speaker Separation*

```text
SPEECH PROCESSING
│
├── Channel Separation
│   ├── Left Channel  → Agent Audio
│   └── Right Channel → Customer Audio
│
├── Audio Conversion
│   └── Stereo → 16 kHz Mono WAV
│
├── Speech Recognition
│   └── faster-whisper
│
└── Transcript Reconstruction
    ├── Timestamp ordering
    ├── Speaker labels
    ├── Word timings
    └── Reversed-channel correction
```

### 3. Conversation Intelligence Layer — *Analysis Engine*

```text
CONVERSATION INTELLIGENCE
│
├── Intent Detection
├── Mood Analysis
│   └── Start → End → Mood Shift
├── Resolution Detection
├── Call Summary
│   └── ≤ 40 words
├── Attention / Risk Score
│   └── 0 – 100
└── Evidence Extraction
    ├── Timestamp
    ├── Quote
    └── Speaker
```

### 4. Evidence Validation Layer — *Evidence Verification Engine*

```text
AI ANALYSIS
     │
     ▼
EVIDENCE VERIFICATION
     │
     ├── Match Timestamp
     ├── Match Speaker
     ├── Normalize Quote
     ├── Exact Text Match
     └── ≥ 60% Word Overlap
              │
              ▼
       Evidence Score
```

Every AI judgment is checked against the actual transcript to verify that the supporting evidence is grounded in the conversation.

### 5. Quality & Compliance Layer — *Quality & Compliance Engine*

```text
QUALITY & COMPLIANCE
│
├── Greeting Check
├── Identity Verification
├── Action Confirmation
├── Empathy Check
├── Repeated Question Check
└── Proper Closing
        │
        ▼
   QA Score (0–100)
        │
        ▼
   Resolution Risk
```

### 6. Persistence Layer — *Call Intelligence Database*

```text
POSTGRESQL
│
└── calls
    ├── Call Metadata
    ├── Transcript
    ├── Analysis
    ├── Evidence
    ├── Attention Score
    └── QA Results
```

### 7. Backend API Layer — *CallRadar API*

```text
CALLRADAR API
│
├── /api/calls
├── /api/qa
├── /api/attention
└── /api/eval
```

**Data flow**

```text
PostgreSQL
     │  READ ONLY
     ▼
 FastAPI
     │  REST API
     ▼
 React + Vite
```

The API reads precomputed results from PostgreSQL. Calls are **not** re-transcribed during API requests.

### 8. Frontend / Dashboard Layer — *CallRadar Command Center*

```text
CALLRADAR COMMAND CENTER
│
├── Command Center
├── QA Dashboard
├── Customer View
├── Call Details
└── Quality / Evaluation
```

---

## Final clean architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                    1. DATA INGESTION                         │
│                                                              │
│   Stereo MP3 Audio                    Call Metadata          │
│   ├── Left  → Agent                   ├── Customer           │
│   └── Right → Customer                ├── Agent              │
│                                       └── Timestamps         │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                 2. SPEECH PROCESSING                         │
│                                                              │
│   Channel Separation → Audio Conversion → faster-whisper     │
│                                      │                       │
│                                      ▼                       │
│                     Transcript Reconstruction                │
│                    Speaker + Timestamp + Words               │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              3. CONVERSATION INTELLIGENCE                    │
│                                                              │
│   Intent │ Mood │ Resolution │ Summary │ Attention │ Evidence │
│                                                              │
│   AI Engines: Claude / Azure / Ollama / Heuristic            │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                4. EVIDENCE VERIFICATION                      │
│                                                              │
│   Timestamp + Speaker + Quote                                │
│                    │                                         │
│                    ▼                                         │
│             Transcript Validation                             │
│                    │                                         │
│                    ▼                                         │
│              Evidence Score                                  │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│             5. QUALITY & COMPLIANCE ENGINE                   │
│                                                              │
│   Greeting │ Identity │ Confirmation │ Empathy │ Closing     │
│                         │                                    │
│                         ▼                                    │
│                    QA Score + Risk                           │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                  6. CALL INTELLIGENCE DB                     │
│                         PostgreSQL                            │
│                                                              │
│        Transcript + Analysis + Evidence + QA                 │
└───────────────────────────┬──────────────────────────────────┘
                            │
                     READ ONLY
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                     7. CALLRADAR API                         │
│                         FastAPI                               │
│                                                              │
│       Calls │ QA │ Attention │ Evaluation                    │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                8. CALLRADAR COMMAND CENTER                   │
│                       React + Vite                            │
│                                                              │
│     Dashboard │ QA │ Customers │ Call View │ Quality         │
└──────────────────────────────────────────────────────────────┘
```

---

## One-line pipeline

```text
MP3 (Stereo)
    ↓
Channel Separation
    ↓
Whisper Transcription
    ↓
Transcript Reconstruction
    ↓
Conversation Intelligence
    ↓
Evidence Verification
    ↓
Quality & Compliance
    ↓
PostgreSQL
    ↓
FastAPI
    ↓
React Dashboard
```

---

## Architecture naming

| Component | Recommended Name |
|---|---|
| Raw Data | Data Ingestion |
| Transcribe | Speech Processing |
| Analyze | Conversation Intelligence |
| Verify Evidence | Evidence Verification |
| QA / Compliance | Quality & Compliance |
| PostgreSQL | Call Intelligence Database |
| FastAPI | CallRadar API |
| React + Vite | CallRadar Command Center |
| Evaluate | Evaluation Engine |

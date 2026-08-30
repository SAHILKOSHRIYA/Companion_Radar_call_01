"""Central configuration for the CallRadar pipeline.

Everything is driven by environment variables so the exact same code runs
locally, in Docker, and in CI. Sensible defaults let it run with zero setup.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# When running in Docker these are mounted volumes; locally they default to the
# repo's ./data folder.
DATA_DIR = Path(os.getenv("CALLRADAR_DATA_DIR", "/data"))
AUDIO_DIR = Path(os.getenv("CALLRADAR_AUDIO_DIR", str(DATA_DIR / "audio")))
METADATA_DIR = Path(os.getenv("CALLRADAR_METADATA_DIR", str(DATA_DIR / "metadata")))
ANALYSIS_DIR = Path(os.getenv("CALLRADAR_ANALYSIS_DIR", str(DATA_DIR / "analysis")))

# ---------------------------------------------------------------------------
# Speech-to-text (faster-whisper)
# ---------------------------------------------------------------------------
# base.en is the sweet spot for 8kHz telephone English: fast, accurate enough,
# runs comfortably on CPU. Override with WHISPER_MODEL=small.en for more quality.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))

# ---------------------------------------------------------------------------
# Analysis engine (hybrid: Claude default, Ollama fallback)
# ---------------------------------------------------------------------------
# ENGINE = "claude" | "ollama" | "auto"
#   auto  -> use Claude if ANTHROPIC_API_KEY is set, else Ollama, else heuristic
ANALYSIS_ENGINE = os.getenv("ANALYSIS_ENGINE", "auto").lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://callradar:callradar@localhost:5432/callradar",
)

# ---------------------------------------------------------------------------
# Pipeline behaviour
# ---------------------------------------------------------------------------
PIPELINE_WORKERS = int(os.getenv("PIPELINE_WORKERS", "4"))

# Channel mapping, per the problem statement:
#   left channel  = agent
#   right channel = customer
AGENT_CHANNEL = int(os.getenv("AGENT_CHANNEL", "0"))     # 0 = left
CUSTOMER_CHANNEL = int(os.getenv("CUSTOMER_CHANNEL", "1"))  # 1 = right

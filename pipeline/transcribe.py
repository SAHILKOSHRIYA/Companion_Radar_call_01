"""Speech-to-text + speaker diarization via channel splitting.

The recordings are stereo: the LEFT channel is the agent, the RIGHT channel is
the customer. That means we get *perfect* speaker separation for free — we do
NOT have to guess "who spoke" with a diarization model. We transcribe each
channel independently, then interleave the resulting segments by their start
time to reconstruct the conversation turn by turn.

This is the single biggest correctness win in the whole system: every word is
attributed to the right speaker by construction, and every segment carries a
real timestamp we can cite as evidence later.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from faster_whisper import WhisperModel

from . import config


@dataclass
class Word:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text}


@dataclass
class Turn:
    """One conversational turn by a single speaker."""
    speaker: str          # "agent" | "customer"
    start: float          # seconds from call start
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text.strip(),
            "words": [w.to_dict() for w in self.words],
        }


# A single model instance is loaded once per process and reused for every call.
_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
            cpu_threads=config.WHISPER_CPU_THREADS,  # single-threaded per worker
        )
    return _model


def _extract_channel(mp3_path: Path, channel: int, out_wav: Path) -> bool:
    """Extract a single channel to 16kHz mono WAV via ffmpeg.

    Uses the ``pan`` filter (``-map_channel`` was removed in modern ffmpeg).
    ``c0=c0`` takes the left channel (agent), ``c0=c1`` the right (customer).
    We upsample 8kHz -> 16kHz because Whisper expects 16kHz. Returns False if
    the channel is silent/empty (some calls are effectively one-sided).
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(mp3_path),
        "-af", f"pan=mono|c0=c{channel}",
        "-ar", "16000", "-ac", "1",
        str(out_wav),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 1024


def _transcribe_channel(wav_path: Path, speaker: str) -> list[Turn]:
    """Run Whisper on one channel and return that speaker's turns."""
    model = get_model()
    segments, _info = model.transcribe(
        str(wav_path),
        language="en",
        beam_size=config.WHISPER_BEAM_SIZE,
        word_timestamps=True,
        vad_filter=True,  # drop the long silences where the *other* party is talking
        vad_parameters={"min_silence_duration_ms": 500},
    )

    turns: list[Turn] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        words = [
            Word(start=w.start, end=w.end, text=w.word.strip())
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
        turns.append(Turn(speaker=speaker, start=seg.start, end=seg.end, text=text, words=words))
    return turns


def _merge_adjacent(turns: list[Turn], gap: float = 0.8) -> list[Turn]:
    """Merge consecutive same-speaker turns separated by a tiny gap.

    Whisper sometimes fragments a single sentence; stitching them back makes
    the transcript read naturally without losing timing.
    """
    if not turns:
        return turns
    merged = [turns[0]]
    for t in turns[1:]:
        prev = merged[-1]
        if t.speaker == prev.speaker and (t.start - prev.end) <= gap:
            prev.end = t.end
            prev.text = f"{prev.text} {t.text}".strip()
            prev.words.extend(t.words)
        else:
            merged.append(t)
    return merged


def transcribe_call(mp3_path: Path) -> dict:
    """Transcribe a stereo call and return a turn-by-turn transcript.

    Output shape:
        {
          "turns": [ {speaker, start, end, text, words:[...]} , ... ],
          "duration": <float seconds>,
          "engine": "faster-whisper:<model>",
        }
    """
    mp3_path = Path(mp3_path)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        agent_wav = tdp / "agent.wav"
        cust_wav = tdp / "customer.wav"

        all_turns: list[Turn] = []
        if _extract_channel(mp3_path, config.AGENT_CHANNEL, agent_wav):
            all_turns += _transcribe_channel(agent_wav, "agent")
        if _extract_channel(mp3_path, config.CUSTOMER_CHANNEL, cust_wav):
            all_turns += _transcribe_channel(cust_wav, "customer")

    # A minority of recordings come off the phone system with the channels
    # reversed. Detect and correct that from the content before interleaving,
    # so speaker attribution stays correct even on those calls.
    swapped = _correct_speaker_swap(all_turns)

    # Interleave both speakers by real start time -> the actual conversation.
    all_turns.sort(key=lambda t: (t.start, 0 if t.speaker == "agent" else 1))
    all_turns = _merge_adjacent(all_turns)

    duration = max((t.end for t in all_turns), default=0.0)
    return {
        "turns": [t.to_dict() for t in all_turns],
        "duration": round(duration, 2),
        "engine": f"faster-whisper:{config.WHISPER_MODEL}",
        "channels_corrected": swapped,
    }


# Phrases the AGENT says (bank script). If these land on the "customer" channel,
# the stereo channels were reversed on this recording.
_AGENT_MARKERS = (
    "national bank", "how can i help", "how may i help", "thank you for calling",
    "is there anything else", "harper valley", "hopper valley", "valley national",
    "my name is", "have a great day", "have a good day",
)
# Phrases the CUSTOMER typically says.
_CUSTOMER_MARKERS = (
    "i lost my", "i need to", "i would like to", "i want to", "can you help",
    "my card", "check my balance", "reset my password", "i need a new",
)


def _score_agentness(turns_text: str) -> int:
    return sum(1 for m in _AGENT_MARKERS if m in turns_text)


def _correct_speaker_swap(turns: list[Turn]) -> bool:
    """If the agent's script language is on the 'customer' channel, swap labels.

    Returns True if a swap was applied. Uses the *content* (bank greeting /
    'how can I help' / closing) rather than channel index, so it's robust to
    recordings that came off the switch with reversed channels.
    """
    agent_text = " ".join(t.text.lower() for t in turns if t.speaker == "agent")
    cust_text = " ".join(t.text.lower() for t in turns if t.speaker == "customer")
    if not agent_text or not cust_text:
        return False

    agent_score = _score_agentness(agent_text)
    cust_score = _score_agentness(cust_text)

    # Only swap when the evidence is clear: the "customer" side sounds much more
    # like the agent than the "agent" side does.
    if cust_score >= agent_score + 2:
        for t in turns:
            t.speaker = "customer" if t.speaker == "agent" else "agent"
        return True
    return False


def transcript_to_text(transcript: dict) -> str:
    """Render a transcript as timestamped dialogue for the LLM / display."""
    lines = []
    for t in transcript["turns"]:
        ts = f"[{_fmt(t['start'])}]"
        who = "AGENT" if t["speaker"] == "agent" else "CUSTOMER"
        lines.append(f"{ts} {who}: {t['text']}")
    return "\n".join(lines)


def _fmt(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

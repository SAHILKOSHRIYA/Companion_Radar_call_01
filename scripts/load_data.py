"""Load the callradar dataset into ./data so the pipeline can find it.

Usage:
    python scripts/load_data.py /path/to/callradar-data.zip
    python scripts/load_data.py /path/to/callradar-data/   # an already-extracted folder

Populates data/audio/*.mp3 and data/metadata/*.json. Idempotent.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "data" / "audio"
META = ROOT / "data" / "metadata"


def _place(name: str, data: bytes):
    base = Path(name).name
    if base.endswith(".mp3"):
        (AUDIO / base).write_bytes(data)
        return "audio"
    if base.endswith(".json"):
        (META / base).write_bytes(data)
        return "meta"
    return None


def from_zip(zip_path: Path):
    a = m = 0
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            kind = _place(n, z.read(n))
            if kind == "audio":
                a += 1
            elif kind == "meta":
                m += 1
    return a, m


def from_dir(src: Path):
    a = m = 0
    for p in src.rglob("*"):
        if p.is_file() and p.suffix in (".mp3", ".json"):
            kind = _place(p.name, p.read_bytes())
            if kind == "audio":
                a += 1
            elif kind == "meta":
                m += 1
    return a, m


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1])
    AUDIO.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)

    if src.is_file() and src.suffix == ".zip":
        a, m = from_zip(src)
    elif src.is_dir():
        a, m = from_dir(src)
    else:
        print(f"Not a zip or directory: {src}")
        return 1

    print(f"Loaded {a} audio files and {m} metadata files into {ROOT / 'data'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

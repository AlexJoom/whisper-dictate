"""Append-only dictation history (JSON lines), like Wispr Flow's history view."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import HISTORY_PATH


class History:
    def __init__(self, path: Path = HISTORY_PATH):
        self.path = path
        self.last: str = ""

    def append(self, text: str, language: str, audio_seconds: float, infer_seconds: float) -> None:
        self.last = text
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lang": language,
            "audio_s": round(audio_seconds, 2),
            "infer_s": round(infer_seconds, 2),
            "text": text.strip(),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

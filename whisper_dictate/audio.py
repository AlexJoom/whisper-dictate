"""Microphone capture through PulseAudio / PipeWire's ``parec``.

Using ``parec`` avoids any native Python audio dependency (no PortAudio) and
works on every Ubuntu desktop. Audio is captured as 16 kHz mono 16-bit PCM,
which is exactly what Whisper expects.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

LevelCallback = Callable[[float], None]


class RecorderError(RuntimeError):
    pass


class Recorder:
    """Start/stop microphone capture; returns float32 audio in [-1, 1]."""

    def __init__(
        self,
        sample_rate: int = 16000,
        source: str = "",
        on_level: Optional[LevelCallback] = None,
        chunk_ms: int = 40,
    ):
        if shutil.which("parec") is None:
            raise RecorderError("`parec` not found. Install it with: sudo apt install pulseaudio-utils")
        self.sample_rate = sample_rate
        self.source = source
        self.on_level = on_level
        self.chunk_bytes = int(sample_rate * chunk_ms / 1000) * 2
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._proc is not None

    def start(self) -> None:
        if self._proc is not None:
            return
        cmd = [
            "parec",
            "--format=s16le",
            f"--rate={self.sample_rate}",
            "--channels=1",
            "--raw",
            "--latency-msec=20",
            "--client-name=Whisper Dictate",
            "--stream-name=Dictation",
        ]
        if self.source:
            cmd += ["--device", self.source]
        self._chunks = []
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise RecorderError(f"Could not start parec: {e}") from e
        self._thread = threading.Thread(target=self._reader, name="parec-reader", daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        while True:
            data = proc.stdout.read(self.chunk_bytes)
            if not data:
                break
            with self._lock:
                self._chunks.append(data)
            if self.on_level is not None:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                try:
                    self.on_level(rms)
                except Exception:  # never let UI errors kill capture
                    log.exception("level callback failed")

    def stop(self) -> np.ndarray:
        proc = self._proc
        if proc is None:
            return np.zeros(0, dtype=np.float32)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._thread is not None:
            self._thread.join(timeout=2)
        stderr = b""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
        self._proc = None
        self._thread = None
        with self._lock:
            raw = b"".join(self._chunks)
            self._chunks = []
        if not raw and stderr:
            raise RecorderError(f"parec produced no audio: {stderr.decode(errors='replace').strip()}")
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return audio

    def cancel(self) -> None:
        try:
            self.stop()
        except RecorderError:
            pass


def duration_seconds(audio: np.ndarray, sample_rate: int = 16000) -> float:
    return float(audio.shape[0]) / sample_rate

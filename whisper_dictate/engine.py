"""Whisper inference wrapper: model loading, language pick, transcription."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Transcription:
    text: str
    language: str
    seconds: float  # wall-clock inference time


class Engine:
    def __init__(
        self,
        model_name: str = "turbo",
        device: str = "auto",
        languages: Sequence[str] = ("el", "en"),
        beam_size: int = 5,
        initial_prompt: str = "",
    ):
        self.model_name = model_name
        self.device_pref = device
        self.languages = list(languages)
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None
        self.model = None
        self.device = "cpu"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        import torch
        import whisper

        if self.device_pref == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = self.device_pref
        t0 = time.time()
        log.info("loading whisper model %r on %s", self.model_name, self.device)
        # Load on the CPU first: whisper.load_model(device="cuda") materializes the
        # fp32 checkpoint on the GPU twice while loading (~6.4 GB for "turbo"),
        # which does not fit on 4 GB cards. Converting to fp16 before the move
        # halves the resident weights as well.
        model = whisper.load_model(self.model_name, device="cpu")
        if self.device.startswith("cuda"):
            model = model.half()
            # whisper's LayerNorm runs in fp32 (x.float()) and needs fp32 weights.
            for module in model.modules():
                if isinstance(module, torch.nn.LayerNorm):
                    module.float()
            model = model.to(self.device)
            torch.cuda.empty_cache()
        self.model = model
        # Warm up so the first real dictation is not slow (CUDA kernels, numba JIT).
        try:
            self.model.transcribe(np.zeros(16000, dtype=np.float32), language="en", fp16=self.device == "cuda")
        except Exception:
            log.exception("warm-up failed (continuing)")
        log.info("model ready in %.1fs", time.time() - t0)

    @property
    def ready(self) -> bool:
        return self.model is not None

    # ------------------------------------------------------------- transcribing
    def _pick_language(self, audio: np.ndarray, candidates: list[str]) -> str:
        import whisper

        if not self.model.is_multilingual:
            return "en"
        if len(candidates) == 1:
            return candidates[0]
        mel = whisper.log_mel_spectrogram(
            whisper.pad_or_trim(audio), n_mels=self.model.dims.n_mels
        ).to(self.model.device)
        if self.device.startswith("cuda"):
            mel = mel.half()
        _, probs = self.model.detect_language(mel)
        best = max(candidates, key=lambda code: probs.get(code, 0.0))
        log.debug("language probs: %s -> %s", {c: round(probs.get(c, 0.0), 3) for c in candidates}, best)
        return best

    def transcribe(self, audio: np.ndarray, languages: Optional[Sequence[str]] = None) -> Transcription:
        if self.model is None:
            raise RuntimeError("model not loaded")
        candidates = list(languages) if languages else self.languages
        t0 = time.time()
        with self._lock:
            language = self._pick_language(audio, candidates)
            result = self.model.transcribe(
                audio,
                language=language,
                fp16=self.device == "cuda",
                beam_size=self.beam_size if self.beam_size > 1 else None,
                best_of=self.beam_size if self.beam_size > 1 else None,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                verbose=None,
            )
        text = " ".join(seg["text"].strip() for seg in result["segments"] if not _is_noise(seg)).strip()
        return Transcription(text=text, language=language, seconds=time.time() - t0)


def _is_noise(segment: dict) -> bool:
    """Drop segments Whisper itself considers likely non-speech."""
    return segment.get("no_speech_prob", 0.0) > 0.8 and segment.get("avg_logprob", 0.0) < -1.0

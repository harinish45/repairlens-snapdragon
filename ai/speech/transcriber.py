"""Offline speech recognition via faster-whisper (ADR-004).

Graceful degradation contract: if the package or model is unavailable, `available`
is False and callers must fall back to typed symptom input (never fake a transcript).
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration_s: float
    latency_ms: float
    model: str
    available: bool = True


class ASRError(Exception):
    pass


class Transcriber:
    """Lazy-loading, thread-safe faster-whisper wrapper."""

    def __init__(self, model_name: str | None = None, device: str = "cpu",
                 compute_type: str = "int8") -> None:
        self.model_name = model_name or os.environ.get("RL_ASR_MODEL", "tiny.en")
        self.device = device or os.environ.get("RL_ASR_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("RL_ASR_COMPUTE_TYPE", "int8")
        self._model = None
        self._lock = threading.Lock()
        self.load_error: str | None = None

    @property
    def available(self) -> bool:
        return self._model is not None or self.load_error is None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                self.load_error = f"faster-whisper not installed: {exc}"
                raise ASRError(self.load_error) from exc
            try:
                log.info("loading ASR model %s (%s/%s)", self.model_name, self.device, self.compute_type)
                self._model = WhisperModel(self.model_name, device=self.device,
                                           compute_type=self.compute_type)
                self.load_error = None
                return self._model
            except Exception as exc:  # noqa: BLE001 - model download/load failure
                self.load_error = str(exc)
                raise ASRError(f"ASR model load failed: {exc}") from exc

    def transcribe_bytes(self, audio: bytes, suffix: str = ".wav") -> Transcript:
        """Transcribe a recorded audio blob. Raises ASRError on any failure."""
        if not audio:
            raise ASRError("empty audio payload")
        model = self._ensure_model()
        # faster-whisper accepts file paths; write to temp (cleanup guaranteed)
        fd, path = tempfile.mkstemp(suffix=suffix)
        started = time.perf_counter()
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(audio)
            segments, info = model.transcribe(path, vad_filter=True, beam_size=1)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            latency = (time.perf_counter() - started) * 1000
            return Transcript(
                text=text,
                language=getattr(info, "language", "unknown"),
                duration_s=float(getattr(info, "duration", 0.0)),
                latency_ms=round(latency, 1),
                model=self.model_name,
            )
        except ASRError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ASRError(f"transcription failed: {exc}") from exc
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

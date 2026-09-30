"""Local reasoning: llama-server (localhost) with deterministic template fallback.

LLM role (ADR-007): explain/rank hypotheses and structure symptoms. It never
owns state transitions or safety decisions. When the LLM is unavailable the
template fallback keeps the full closed loop working offline.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReasoningResult:
    text: str
    source: str            # "llm" | "template"
    latency_ms: float
    raw: dict[str, Any] = field(default_factory=dict)


class Reasoner:
    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout_s: float | None = None) -> None:
        self.host = host or os.environ.get("RL_LLM_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("RL_LLM_PORT", "8081"))
        self.timeout = float(timeout_s or os.environ.get("RL_LLM_TIMEOUT_S", "30"))
        self.enabled = os.environ.get("RL_LLM_ENABLED", "true").lower() != "false"
        self._healthy: bool | None = None

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._healthy is not None:
            return self._healthy
        try:
            req = urllib.request.Request(f"http://{self.host}:{self.port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2):
                self._healthy = True
        except Exception:  # noqa: BLE001 - any failure means "not available"
            self._healthy = False
        return self._healthy

    def reset_health(self) -> None:
        self._healthy = None

    def _chat(self, prompt: str, max_tokens: int = 220) -> str:
        payload = json.dumps({
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stop": ["</s>", "###", "User:"],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.host}:{self.port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()

    def explain(self, device_name: str, symptom: str, evidence_line: str,
                hypotheses: list[dict[str, Any]], next_action: str) -> ReasoningResult:
        """Produce a short technician-style explanation. Falls back to templates."""
        import time

        started = time.perf_counter()
        if self.available:
            try:
                hyp_lines = "\n".join(
                    f"- {h.get('title')} (confidence {h.get('confidence')})" for h in hypotheses[:3]
                )
                prompt = (
                    "You are RepairLens, a careful on-device repair assistant. "
                    "Explain in max 3 short sentences why this is the likely cause and "
                    "what to do next. Never suggest opening equipment or mains work.\n"
                    f"Device: {device_name}\nSymptom: {symptom}\n"
                    f"Observed evidence: {evidence_line}\nCandidate causes:\n{hyp_lines}\n"
                    f"Next action: {next_action}\nExplanation:"
                )
                text = self._chat(prompt, max_tokens=180)
                if text:
                    return ReasoningResult(_sanitize(text), "llm",
                                           round((time.perf_counter() - started) * 1000, 1))
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, OSError) as exc:
                log.warning("LLM call failed, using template fallback: %s", exc)
                self._healthy = False
        return ReasoningResult(self._template_explain(device_name, symptom, evidence_line,
                                                      hypotheses, next_action),
                               "template",
                               round((time.perf_counter() - started) * 1000, 1))

    def structure_symptom(self, raw_text: str, known_symptoms: list[dict[str, Any]]) -> ReasoningResult:
        """Map user text to a known symptom id (deterministic keyword fallback)."""
        import time

        started = time.perf_counter()
        lowered = raw_text.lower()
        best_id, best_hits = "", 0
        for sym in known_symptoms:
            hits = sum(1 for kw in sym.get("keywords", []) if str(kw).lower() in lowered)
            if hits > best_hits:
                best_id, best_hits = str(sym.get("id")), hits
        if self.available and not best_id:
            try:
                opts = ", ".join(str(s.get("id")) for s in known_symptoms)
                prompt = (
                    f"Map the user report to exactly one symptom id from: [{opts}]. "
                    f"Reply with only the id.\nUser report: {raw_text}\nId:"
                )
                out = self._chat(prompt, max_tokens=12)
                m = re.search(r"[a-z_]+", out.lower())
                if m and m.group(0) in {str(s.get("id")) for s in known_symptoms}:
                    return ReasoningResult(m.group(0), "llm",
                                           round((time.perf_counter() - started) * 1000, 1))
            except Exception as exc:  # noqa: BLE001
                log.warning("symptom structuring via LLM failed: %s", exc)
                self._healthy = False
        return ReasoningResult(best_id, "template",
                               round((time.perf_counter() - started) * 1000, 1))

    @staticmethod
    def _template_explain(device_name: str, symptom: str, evidence_line: str,
                          hypotheses: list[dict[str, Any]], next_action: str) -> str:
        if not hypotheses:
            return (f"I could not match the evidence on the {device_name} to a known "
                    f"cause. Please reposition the camera or add more detail.")
        top = hypotheses[0]
        parts = [
            f"Based on {evidence_line or 'the reported symptom'}, the most likely cause is: "
            f"{top.get('title')}.",
        ]
        if len(hypotheses) > 1:
            parts.append(f"Less likely: {hypotheses[1].get('title')}.")
        parts.append(f"Next safe step: {next_action}")
        return " ".join(parts)


def _sanitize(text: str) -> str:
    """Keep LLM output on rails: collapse whitespace, cap length."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:600]


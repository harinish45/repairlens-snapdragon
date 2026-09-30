"""Hypothesis ranking rules: evidence + symptom -> ordered candidate list.

Deterministic (no LLM). The LLM may only *explain* candidates produced here (ADR-007).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge.loader import DeviceDoc, evidence_tags_for_value


@dataclass(frozen=True)
class Hypothesis:
    id: str
    title: str
    confidence: float
    action_text: str
    action_id: str
    safety: str
    expected_change: dict[str, Any]
    verification_note: str
    symptom_id: str

    @property
    def display_confidence(self) -> float:
        return round(max(0.0, min(1.0, self.confidence)), 2)


def _match_evidence(hyp: dict[str, Any], evidence: set[str]) -> bool:
    req_any = [str(t) for t in hyp.get("evidence_requires_any", [])]
    excl_any = [str(t) for t in hyp.get("evidence_excludes_any", [])]
    if req_any and not any(t in evidence for t in req_any):
        return False
    if excl_any and any(t in evidence for t in excl_any):
        return False
    return True


def evidence_tags_from_observations(
    observations: dict[str, str], device: DeviceDoc
) -> set[str]:
    """observations: {indicator_id: observed_value} -> set of evidence tags."""
    tags: set[str] = set()
    for ind_id, value in observations.items():
        known_values = {str(v.get("value")) for v in device.indicator_values(ind_id)}
        if value not in known_values:
            # Unrecognized/unlisted values are treated as unknown evidence, never as facts.
            value = "unknown"
        tags.update(evidence_tags_for_value(value))
    return tags


def rank_hypotheses(
    device: DeviceDoc,
    symptom_id: str | None,
    evidence: set[str],
) -> list[Hypothesis]:
    """Return safety-filtered hypotheses ordered by confidence (desc)."""
    out: list[Hypothesis] = []
    for hyp in device.hypotheses:
        if symptom_id and hyp.get("symptom") != symptom_id:
            continue
        if not _match_evidence(hyp, evidence):
            continue
        action = hyp.get("action") or {}
        out.append(
            Hypothesis(
                id=str(hyp.get("id")),
                title=str(hyp.get("title")),
                confidence=float(hyp.get("confidence", 0.3)),
                action_text=str(action.get("text", "")),
                action_id=str(action.get("id", "")),
                safety=str(action.get("safety", "unknown")),
                expected_change=dict(action.get("expected_visual_change") or {}),
                verification_note=str(action.get("verification_note", "")),
                symptom_id=str(hyp.get("symptom", "")),
            )
        )
    out.sort(key=lambda h: h.confidence, reverse=True)
    return out

"""Session orchestrator: wires state machine + knowledge + safety + AI evidence.

The ONLY place allowed to advance diagnostic state. Deterministic: the LLM may
supply explanation text but never a transition (ADR-007).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from diagnostics.state_machine import DiagnosticStateMachine, State
from diagnostics.rules.hypotheses import rank_hypotheses, evidence_tags_from_observations
from diagnostics.safety.gate import (
    check_action_text,
    check_observations,
    load_device_blocked,
)
from knowledge.loader import KnowledgeBase, DeviceDoc

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Observation:
    phase: str                 # "before" | "after"
    indicator: str
    value: str                 # knowledge vocab value (green_solid, unknown, ...)
    confidence: float
    evidence_tags: list[str]
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "indicator": self.indicator, "value": self.value,
            "confidence": self.confidence, "evidence_tags": self.evidence_tags, "at": self.at,
        }


@dataclass
class Session:
    id: str
    kb: KnowledgeBase
    sm: DiagnosticStateMachine = field(default_factory=DiagnosticStateMachine)
    device_id: str | None = None
    symptom_id: str | None = None
    symptom_text: str = ""
    observations: list[Observation] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    tried_hypotheses: list[str] = field(default_factory=list)
    current_action: dict[str, Any] | None = None
    explanation: str = ""
    explanation_source: str = "template"
    status_message: str = "Ready. Select the device and describe the problem."
    confidence: float = 0.0
    safety_block_reasons: list[str] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    last_error: str | None = None

    @property
    def device(self) -> DeviceDoc | None:
        return self.kb.get(self.device_id) if self.device_id else None

    @property
    def evidence_tags(self) -> set[str]:
        tags: set[str] = set()
        for obs in self.observations:
            tags.update(obs.evidence_tags)
        return tags

    @property
    def latest_before(self) -> Observation | None:
        before = [o for o in self.observations if o.phase == "before"]
        return before[-1] if before else None

    def _fire(self, event: str, detail: str = "") -> None:
        self.sm.fire(event, detail)
        self.events.append({"event": event, "state": self.sm.state.value,
                            "at": _now(), "detail": detail})
        log.info("session %s: %s -> %s (%s)", self.id, event, self.sm.state.value, detail)

    def _classify_phase(self) -> str:
        if self.sm.state in (State.ACTION_RECOMMENDED, State.ACTION_PERFORMED):
            return "after" if self.sm.state is State.ACTION_PERFORMED else "before"
        return "after" if any(o.phase == "after" for o in self.observations) else "before"

    def to_dict(self) -> dict:
        dev = self.device
        idx, total = self.sm.progress
        return {
            "session_id": self.id,
            "state": self.sm.state.value,
            "progress": {"step": idx, "total": total},
            "device": {"id": dev.device_id, "name": dev.name} if dev else None,
            "symptom_id": self.symptom_id,
            "symptom_text": self.symptom_text,
            "observations": [o.to_dict() for o in self.observations],
            "evidence_tags": sorted(self.evidence_tags),
            "hypotheses": self.hypotheses,
            "tried_hypotheses": self.tried_hypotheses,
            "current_action": self.current_action,
            "explanation": self.explanation,
            "explanation_source": self.explanation_source,
            "confidence": self.confidence,
            "status_message": self.status_message,
            "safety_block_reasons": self.safety_block_reasons,
            "allowed_events": self.sm.allowed_events(),
            "events": self.events[-20:],
            "last_error": self.last_error,
        }


class SessionManager:
    """Owns the single active session (MVP: one technician workflow at a time)."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or KnowledgeBase()
        self.session = self.new_session()

    def new_session(self) -> Session:
        return Session(id=uuid.uuid4().hex[:12], kb=self.kb)

    def reset(self) -> Session:
        self.session = self.new_session()
        return self.session

    def select_device(self, device_id: str) -> Session:
        s = self.session
        s.last_error = None
        dev = s.kb.get(device_id)
        if dev is None:
            s.last_error = "unknown_device"
            s.status_message = "I don't have enough verified information for this device."
            if s.sm.state in (State.IDLE, State.UNCERTAIN):
                s._fire("insufficient_evidence", f"unknown device {device_id}")
            return s
        s.device_id = device_id
        s.status_message = f"Device confirmed: {dev.name}. Describe the problem (type or speak)."
        if s.sm.state in (State.IDLE, State.UNCERTAIN):
            s._fire("device_identified", device_id)
        return s

    def submit_symptom(self, text: str, reasoner=None) -> Session:
        s = self.session
        s.last_error = None
        text = (text or "").strip()
        if not text:
            s.last_error = "empty_symptom"
            s.status_message = "Please describe the problem you are seeing."
            return s
        # Safety: escalation phrases in the user's report
        verdict = check_observations(text)
        if not verdict.allowed:
            s.safety_block_reasons = list(verdict.reasons)
            if not s.sm.is_terminal:
                s._fire("escalate", "; ".join(verdict.reasons))
            s.status_message = ("Stop. " + " ".join(verdict.reasons)
                                + ". Recommend qualified service.")
            return s
        if s.device is None:
            s.last_error = "no_device"
            s.status_message = "Select the device first, then describe the problem."
            return s
        s.symptom_text = text
        if s.sm.state in (State.IDLE, State.UNCERTAIN):
            s._fire("device_identified", s.device_id or "")
        if s.sm.can("symptom_received"):
            s._fire("symptom_received", text[:80])
        # Map text -> known symptom id (LLM-assisted, deterministic fallback)
        sym = s.kb.match_symptom(s.device, text)
        s.symptom_id = str(sym.get("id")) if sym else None
        if reasoner is not None and s.symptom_id is None:
            r = reasoner.structure_symptom(text, s.device.symptoms)
            s.symptom_id = r.text or None
        if s.symptom_id is None:
            s.status_message = ("I couldn't map that to a known symptom for this device. "
                                "Try mentioning: "
                                + ", ".join(str(x.get("id", "")) for x in s.device.symptoms))
        else:
            s.status_message = (f"Symptom noted ({s.symptom_id}). "
                                "Now show me the device indicators.")
        # Evidence may already be waiting from an earlier observation
        if s.evidence_tags:
            if s.sm.state is State.SYMPTOM_IDENTIFIED and s.sm.can("evidence_collected"):
                s._fire("evidence_collected", "evidence re-confirmed after symptom")
            if s.sm.can("hypotheses_proposed"):
                return self._propose_hypotheses(reasoner)
        return s

    def observe(self, value: str, confidence: float, indicator: str = "status_led",
                reasoner=None) -> Session:
        """Feed one camera-derived indicator observation into the loop.

        Handles both first observation (evidence collection) and post-action
        verification (before/after comparison + state-changed decision).
        """
        s = self.session
        s.last_error = None
        if s.device is None:
            s.last_error = "no_device"
            s.status_message = "Select the device first so I know what indicators matter."
            return s

        # --- verification branch: user acted, we re-observe ----------------
        if s.sm.state is State.ACTION_PERFORMED:
            if confidence < 0.5 or value == "unknown":
                s.status_message = ("I am not confident enough to read this indicator. "
                                    "Please move closer or improve lighting and re-observe.")
                return s
            s._fire("result_observed", f"after={value}")
            return self._evaluate_verification(value, confidence, indicator)

        # --- evidence branch ------------------------------------------------
        obs_kind = s._classify_phase()
        obs = Observation(obs_kind, indicator, value, confidence,
                          sorted(evidence_tags_from_observations({indicator: value}, s.device)))
        s.observations.append(obs)

        if s.sm.can("evidence_collected"):
            s._fire("evidence_collected", f"{indicator}={value}")
        if s.symptom_id and s.sm.can("hypotheses_proposed"):
            return self._propose_hypotheses(reasoner)
        if s.sm.state is State.DEVICE_DETECTED:
            s.status_message = (f"Observed {indicator}={value}. "
                                "Now describe the problem.")
        return s

    def _propose_hypotheses(self, reasoner=None) -> Session:
        s = self.session
        assert s.device is not None
        hyps = rank_hypotheses(s.device, s.symptom_id, s.evidence_tags)
        hyps = [h for h in hyps if h.id not in s.tried_hypotheses]
        if not hyps:
            if not s.sm.is_terminal:
                s._fire("insufficient_evidence", "no hypothesis matches evidence")
            s.status_message = ("I don't have enough verified information for this evidence. "
                                "Check the indicator again or add more detail.")
            return s
        s._fire("hypotheses_proposed", f"{len(hyps)} candidates")
        s.hypotheses = [
            {"id": h.id, "title": h.title, "confidence": h.display_confidence}
            for h in hyps
        ]
        s.confidence = hyps[0].display_confidence

        # Safety gate: never recommend a blocked action (defense in depth)
        top = hyps[0]
        dev_block = load_device_blocked(s.device.blocked_actions)
        verdict = check_action_text(top.action_text, dev_block)
        if not verdict.allowed:
            s.safety_block_reasons = list(verdict.reasons)
            s._fire("blocked_unsafe", "; ".join(verdict.reasons))
            s.status_message = "Stop. I can't safely guide this procedure."
            return s

        s.current_action = {
            "hypothesis_id": top.id,
            "hypothesis_title": top.title,
            "action_id": top.action_id,
            "text": top.action_text,
            "expected_change": top.expected_change,
            "verification_note": top.verification_note,
            "safety": "safe",
        }
        s._fire("action_recommended", top.action_id)

        evidence_line = ", ".join(f"{o.indicator}={o.value}" for o in s.observations) or "none"
        if reasoner is not None:
            r = reasoner.explain(s.device.name, s.symptom_text or (s.symptom_id or ""),
                                 evidence_line, s.hypotheses, top.action_text)
            s.explanation, s.explanation_source = r.text, r.source
        else:
            from ai.reasoning.llm import Reasoner
            s.explanation = Reasoner._template_explain(
                s.device.name, s.symptom_text, evidence_line, s.hypotheses, top.action_text)
            s.explanation_source = "template"
        s.status_message = f"Next safe step: {top.action_text}"
        return s

    def mark_action_done(self) -> Session:
        s = self.session
        if s.sm.state is not State.ACTION_RECOMMENDED or not s.current_action:
            s.last_error = "no_action_to_confirm"
            s.status_message = "No action is currently recommended."
            return s
        s._fire("action_performed", s.current_action["action_id"])
        s.tried_hypotheses.append(str(s.current_action["hypothesis_id"]))
        s.status_message = ("Action registered. Show me the indicator again so I can "
                            "verify whether the state changed.")
        return s

    def _evaluate_verification(self, value: str, confidence: float,
                               indicator: str) -> Session:
        """Compare after-observation against the action's expected visual change."""
        s = self.session
        assert s.device is not None and s.current_action is not None
        expected = s.current_action.get("expected_change") or {}
        ind_id = str(expected.get("indicator", indicator))
        obs = Observation("after", ind_id, value, confidence,
                          sorted(evidence_tags_from_observations({ind_id: value}, s.device)))
        s.observations.append(obs)

        targets = {str(x) for x in (expected.get("to_any") or [])}
        if expected.get("to"):
            targets.add(str(expected["to"]))

        before = s.latest_before
        before_val = before.value if before else None

        if value in targets:
            crit = s.device.resolution_criteria.get(s.symptom_id or "", "")
            if not s.sm.is_terminal:
                s._fire("state_changed_yes", f"{before_val} -> {value}")
            s.confidence = round(0.7 * confidence + 0.3 * (s.confidence or 0.5), 2)
            s.status_message = (
                f"Verified: indicator changed {before_val or '?'} → {value}. "
                f"{crit or 'The expected visual change occurred.'} "
                "Please confirm on your device that the problem is gone."
            )
            s.current_action = None
            return s

        if value == before_val:
            # Nothing changed -> try next hypothesis
            if s.sm.can("state_changed_no"):
                s._fire("state_changed_no", f"unchanged={value}")
                return self._propose_hypotheses()
            return s

        # Changed but not to the expected target (e.g. green -> red): next step
        if s.sm.can("state_changed_next_step"):
            s._fire("state_changed_next_step", f"unexpected={value}")
            return self._propose_hypotheses()
        s.status_message = (
            f"The indicator is now {value} (expected {sorted(targets) or 'a change'}). "
            "This is an unexpected state — let's try the next diagnostic step."
        )
        s.current_action = None
        return s





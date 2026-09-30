"""Explicit diagnostic state machine for RepairLens.

Transitions are deterministic and data-driven; the LLM never owns transitions (ADR-007).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class State(str, Enum):
    IDLE = "IDLE"
    DEVICE_DETECTED = "DEVICE_DETECTED"
    SYMPTOM_IDENTIFIED = "SYMPTOM_IDENTIFIED"
    EVIDENCE_COLLECTED = "EVIDENCE_COLLECTED"
    HYPOTHESIS_GENERATED = "HYPOTHESIS_GENERATED"
    ACTION_RECOMMENDED = "ACTION_RECOMMENDED"
    ACTION_PERFORMED = "ACTION_PERFORMED"
    RESULT_OBSERVED = "RESULT_OBSERVED"
    NEXT_DIAGNOSTIC_STEP = "NEXT_DIAGNOSTIC_STEP"
    RESOLVED = "RESOLVED"
    NEXT_HYPOTHESIS = "NEXT_HYPOTHESIS"
    STOPPED_UNSAFE = "STOPPED_UNSAFE"
    ESCALATE_SERVICE = "ESCALATE_SERVICE"
    UNCERTAIN = "UNCERTAIN"


# Ordered backbone of the happy path (used for progress display and validation).
PIPELINE: tuple[State, ...] = (
    State.IDLE,
    State.DEVICE_DETECTED,
    State.SYMPTOM_IDENTIFIED,
    State.EVIDENCE_COLLECTED,
    State.HYPOTHESIS_GENERATED,
    State.ACTION_RECOMMENDED,
    State.ACTION_PERFORMED,
    State.RESULT_OBSERVED,
)

TERMINAL_STATES: frozenset[State] = frozenset(
    {State.RESOLVED, State.STOPPED_UNSAFE, State.ESCALATE_SERVICE}
)


class InvalidTransition(Exception):
    """Raised when an event is not legal in the current state."""


# event -> (allowed source states, destination)
_TRANSITIONS: dict[str, tuple[frozenset[State], State]] = {
    "device_identified": (frozenset({State.IDLE, State.UNCERTAIN}), State.DEVICE_DETECTED),
    "symptom_received": (
        frozenset({State.DEVICE_DETECTED, State.EVIDENCE_COLLECTED, State.SYMPTOM_IDENTIFIED}),
        State.SYMPTOM_IDENTIFIED,
    ),
    "evidence_collected": (
        frozenset(
            {
                State.DEVICE_DETECTED,
                State.SYMPTOM_IDENTIFIED,
                State.EVIDENCE_COLLECTED,
                State.RESULT_OBSERVED,
                State.NEXT_DIAGNOSTIC_STEP,
                State.NEXT_HYPOTHESIS,
            }
        ),
        State.EVIDENCE_COLLECTED,
    ),
    "hypotheses_proposed": (
        frozenset({State.EVIDENCE_COLLECTED, State.NEXT_HYPOTHESIS, State.NEXT_DIAGNOSTIC_STEP}),
        State.HYPOTHESIS_GENERATED,
    ),
    "action_recommended": (frozenset({State.HYPOTHESIS_GENERATED}), State.ACTION_RECOMMENDED),
    "action_performed": (frozenset({State.ACTION_RECOMMENDED}), State.ACTION_PERFORMED),
    "result_observed": (frozenset({State.ACTION_PERFORMED}), State.RESULT_OBSERVED),
    "state_changed_yes": (frozenset({State.RESULT_OBSERVED}), State.RESOLVED),
    "state_changed_next_step": (frozenset({State.RESULT_OBSERVED}), State.NEXT_DIAGNOSTIC_STEP),
    "state_changed_no": (frozenset({State.RESULT_OBSERVED}), State.NEXT_HYPOTHESIS),
    "blocked_unsafe": (
        frozenset(s for s in State if s not in TERMINAL_STATES),
        State.STOPPED_UNSAFE,
    ),
    "escalate": (
        frozenset(s for s in State if s not in TERMINAL_STATES),
        State.ESCALATE_SERVICE,
    ),
    "reset": (frozenset(s for s in State if s is not State.IDLE), State.IDLE),
    "insufficient_evidence": (
        frozenset({State.DEVICE_DETECTED, State.SYMPTOM_IDENTIFIED, State.EVIDENCE_COLLECTED}),
        State.UNCERTAIN,
    ),
}


@dataclass
class TransitionRecord:
    event: str
    from_state: str
    to_state: str
    detail: str = ""


@dataclass
class DiagnosticStateMachine:
    state: State = State.IDLE
    history: list[TransitionRecord] = field(default_factory=list)

    def can(self, event: str) -> bool:
        if event not in _TRANSITIONS:
            return False
        sources, _ = _TRANSITIONS[event]
        return self.state in sources

    def fire(self, event: str, detail: str = "") -> State:
        if event not in _TRANSITIONS:
            raise InvalidTransition(f"unknown event '{event}'")
        sources, dest = _TRANSITIONS[event]
        if self.state not in sources:
            raise InvalidTransition(
                f"event '{event}' not allowed in state {self.state.value}"
            )
        prev = self.state
        self.state = dest
        self.history.append(
            TransitionRecord(event=event, from_state=prev.value, to_state=dest.value, detail=detail)
        )
        return dest

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def progress(self) -> tuple[int, int]:
        """Position on the happy-path pipeline (for UI progress bar)."""
        if self.state in (State.NEXT_DIAGNOSTIC_STEP, State.NEXT_HYPOTHESIS):
            idx = PIPELINE.index(State.RESULT_OBSERVED)
        elif self.state in (State.RESOLVED, State.STOPPED_UNSAFE, State.ESCALATE_SERVICE):
            idx = len(PIPELINE)
        elif self.state in (State.UNCERTAIN,):
            idx = 0
        else:
            idx = PIPELINE.index(self.state)
        return idx, len(PIPELINE)

    def allowed_events(self) -> list[str]:
        return sorted(e for e in _TRANSITIONS if self.can(e))


def legal_transition_table() -> Iterable[tuple[str, str, str]]:
    for event, (sources, dest) in sorted(_TRANSITIONS.items()):
        for src in sorted(sources, key=lambda s: s.value):
            yield event, src.value, dest.value

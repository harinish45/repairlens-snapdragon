"""Unit tests: diagnostic state machine transitions (deterministic, §19)."""
import pytest

from diagnostics.state_machine.machine import (
    PIPELINE,
    State,
    DiagnosticStateMachine,
    InvalidTransition,
    legal_transition_table,
)


def test_happy_path_reaches_resolved():
    sm = DiagnosticStateMachine()
    assert sm.state is State.IDLE
    sm.fire("device_identified")
    assert sm.state is State.DEVICE_DETECTED
    sm.fire("symptom_received")
    assert sm.state is State.SYMPTOM_IDENTIFIED
    sm.fire("evidence_collected")
    sm.fire("hypotheses_proposed")
    sm.fire("action_recommended")
    sm.fire("action_performed")
    sm.fire("result_observed")
    sm.fire("state_changed_yes")
    assert sm.state is State.RESOLVED
    assert sm.is_terminal


def test_no_evidence_goes_to_next_hypothesis():
    sm = DiagnosticStateMachine()
    for ev in ("device_identified", "symptom_received", "evidence_collected",
               "hypotheses_proposed", "action_recommended", "action_performed",
               "result_observed"):
        sm.fire(ev)
    sm.fire("state_changed_no")
    assert sm.state is State.NEXT_HYPOTHESIS
    # next hypothesis loop must re-enter evidence/hypothesis flow
    sm.fire("evidence_collected")
    sm.fire("hypotheses_proposed")
    assert sm.state is State.HYPOTHESIS_GENERATED


def test_illegal_transition_raises():
    sm = DiagnosticStateMachine()
    with pytest.raises(InvalidTransition):
        sm.fire("action_performed")  # nothing recommended yet


def test_unknown_event_raises():
    sm = DiagnosticStateMachine()
    with pytest.raises(InvalidTransition):
        sm.fire("made_up_event")


def test_unsafe_block_from_any_non_terminal_state():
    sm = DiagnosticStateMachine()
    sm.fire("device_identified")
    sm.fire("blocked_unsafe")
    assert sm.state is State.STOPPED_UNSAFE
    with pytest.raises(InvalidTransition):
        sm.fire("action_recommended")


def test_reset_returns_to_idle():
    sm = DiagnosticStateMachine()
    sm.fire("device_identified")
    sm.fire("blocked_unsafe")
    sm.fire("reset")
    assert sm.state is State.IDLE


def test_progress_bar_within_bounds():
    sm = DiagnosticStateMachine()
    assert sm.progress == (0, len(PIPELINE))
    for ev in ("device_identified", "symptom_received", "evidence_collected",
               "hypotheses_proposed", "action_recommended", "action_performed",
               "result_observed", "state_changed_yes"):
        sm.fire(ev)
        idx, total = sm.progress
        assert total == len(PIPELINE)
        assert 0 <= idx <= total
    assert sm.progress == (len(PIPELINE), len(PIPELINE))


def test_legal_transition_table_non_empty_and_well_formed():
    rows = list(legal_transition_table())
    assert len(rows) > 10
    for event, src, dst in rows:
        assert event and src and dst


def test_history_records_transitions():
    sm = DiagnosticStateMachine()
    sm.fire("device_identified", detail="router seen")
    assert sm.history[-1].event == "device_identified"
    assert sm.history[-1].to_state == State.DEVICE_DETECTED.value

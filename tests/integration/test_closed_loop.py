"""Integration tests: the full SEE → UNDERSTAND → DIAGNOSE → GUIDE → VERIFY loop
exercised through the orchestrator (no camera/network needed — values are injected
at the observation boundary exactly as the API will do it)."""
import pytest

from app.orchestration.session import SessionManager
from diagnostics.state_machine import State
from knowledge.loader import KnowledgeBase


@pytest.fixture
def mgr() -> SessionManager:
    return SessionManager(kb=KnowledgeBase())


def full_loop_to_action(mgr: SessionManager) -> None:
    """Drive the session to ACTION_RECOMMENDED with amber LED + no_network."""
    mgr.select_device("router_home")
    assert mgr.session.sm.state is State.DEVICE_DETECTED
    mgr.submit_symptom("my wifi is not connecting to the internet")
    assert mgr.session.sm.state is State.SYMPTOM_IDENTIFIED
    mgr.observe(value="amber_solid", confidence=0.9)
    assert mgr.session.sm.state is State.ACTION_RECOMMENDED
    assert mgr.session.current_action is not None


def test_full_loop_resolves_on_expected_change(mgr: SessionManager):
    full_loop_to_action(mgr)
    action = mgr.session.current_action
    assert action["expected_change"]["to"] == "green_solid"
    mgr.mark_action_done()
    assert mgr.session.sm.state is State.ACTION_PERFORMED
    mgr.observe(value="green_solid", confidence=0.92)
    assert mgr.session.sm.state is State.RESOLVED
    assert "Verified" in mgr.session.status_message


def test_full_loop_falls_to_next_hypothesis_when_unchanged(mgr: SessionManager):
    full_loop_to_action(mgr)
    first_hyp = mgr.session.current_action["hypothesis_id"]
    mgr.mark_action_done()
    mgr.observe(value="amber_solid", confidence=0.9)  # nothing changed
    assert mgr.session.current_action is not None
    assert mgr.session.current_action["hypothesis_id"] != first_hyp
    assert first_hyp in mgr.session.tried_hypotheses


def test_unexpected_state_change_takes_next_step(mgr: SessionManager):
    full_loop_to_action(mgr)
    first_hyp = mgr.session.current_action["hypothesis_id"]
    mgr.mark_action_done()
    mgr.observe(value="red_solid", confidence=0.9)  # changed, but not to green
    # Loop must move on: new hypothesis + new recommended action
    assert mgr.session.sm.state is State.ACTION_RECOMMENDED
    assert mgr.session.current_action["hypothesis_id"] != first_hyp
    msg = mgr.session.status_message.lower()
    assert "next" in msg or "unexpected" in msg


def test_unsafe_action_blocked(mgr: SessionManager):
    # Force an unsafe action through the safety gate by patching device knowledge
    dev = mgr.session.kb.get("router_home")
    dev.raw["hypotheses"] = [{
        "id": "unsafe_open", "symptom": "no_network",
        "title": "Inspect internals", "confidence": 0.99,
        "evidence_requires_any": ["led_amber_solid"],
        "action": {"id": "open_it", "text": "Open the router case and inspect the board.",
                   "safety": "safe",
                   "expected_visual_change": {"indicator": "status_led",
                                              "from_any": ["amber_solid"], "to": "green_solid"}},
    }]
    mgr.select_device("router_home")
    mgr.submit_symptom("not connecting to network")
    mgr.observe(value="amber_solid", confidence=0.9)
    assert mgr.session.sm.state is State.STOPPED_UNSAFE
    assert "Stop" in mgr.session.status_message
    assert mgr.session.current_action is None


def test_low_confidence_observation_rejected(mgr: SessionManager):
    full_loop_to_action(mgr)
    mgr.mark_action_done()
    mgr.observe(value="unknown", confidence=0.3)
    assert mgr.session.sm.state is State.ACTION_PERFORMED
    assert "confident" in mgr.session.status_message.lower()


def test_unknown_device_rejected(mgr: SessionManager):
    mgr.select_device("does_not_exist")
    assert mgr.session.last_error == "unknown_device"
    assert "enough verified information" in mgr.session.status_message


def test_symptom_before_device_is_rejected(mgr: SessionManager):
    mgr.submit_symptom("no network")
    assert mgr.session.last_error == "no_device"


def test_empty_symptom_rejected(mgr: SessionManager):
    mgr.select_device("router_home")
    mgr.submit_symptom("   ")
    assert mgr.session.last_error == "empty_symptom"


def test_evidence_before_symptom_waits_for_text(mgr: SessionManager):
    mgr.select_device("router_home")
    mgr.observe(value="amber_solid", confidence=0.9)
    assert mgr.session.sm.state is not State.ACTION_RECOMMENDED
    mgr.submit_symptom("wifi not connecting")
    assert mgr.session.sm.state is State.ACTION_RECOMMENDED


def test_session_serializes_to_dict(mgr: SessionManager):
    full_loop_to_action(mgr)
    d = mgr.session.to_dict()
    assert d["state"] == "ACTION_RECOMMENDED"
    assert d["device"]["id"] == "router_home"
    assert d["hypotheses"]
    assert d["current_action"]["text"]
    assert isinstance(d["observations"], list) and d["observations"]
    assert d["progress"]["total"] >= d["progress"]["step"] >= 0


def test_printer_loop(mgr: SessionManager):
    mgr.select_device("printer_office")
    mgr.submit_symptom("printer error light flashing paper jam")
    mgr.observe(value="red_solid", confidence=0.88)
    assert mgr.session.sm.state is State.ACTION_RECOMMENDED
    mgr.mark_action_done()
    mgr.observe(value="green_solid", confidence=0.9)
    assert mgr.session.sm.state is State.RESOLVED


def test_monitor_loop(mgr: SessionManager):
    mgr.select_device("monitor_display")
    mgr.submit_symptom("monitor shows no picture no signal")
    mgr.observe(value="white_blinking", confidence=0.85)
    assert mgr.session.sm.state is State.ACTION_RECOMMENDED
    mgr.mark_action_done()
    mgr.observe(value="white_solid", confidence=0.9)
    assert mgr.session.sm.state is State.RESOLVED


def test_escalation_on_burning_smell(mgr: SessionManager):
    mgr.select_device("router_home")
    mgr.submit_symptom("there is a burning smell coming from the router")
    assert mgr.session.sm.state is State.ESCALATE_SERVICE
    assert "qualified service" in mgr.session.status_message.lower() or \
           "recommend" in mgr.session.status_message.lower()

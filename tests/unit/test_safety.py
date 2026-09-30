"""Unit tests: safety gate — every blocked pattern must be exercised (§12, §19)."""
from diagnostics.safety.gate import (
    check_action_text,
    check_observations,
    load_device_blocked,
)


def test_safe_action_allowed():
    v = check_action_text("Reseat the WAN cable at both ends until it clicks.")
    assert v.allowed and not v.reasons


def test_open_router_case_blocked():
    v = check_action_text("Open the router case and inspect the board.")
    assert not v.allowed
    assert any("enclosure" in r or "unsafe" in r.lower() for r in v.reasons)


def test_mains_voltage_blocked():
    assert not check_action_text("Check the 220v rail inside the power supply.").allowed
    assert not check_action_text("Call an electrician to wire the wall socket.").allowed


def test_swollen_battery_blocked():
    assert not check_action_text("Continue using the swollen battery carefully.").allowed


def test_capacitor_discharge_blocked():
    assert not check_action_text("Discharge the capacitors before proceeding.").allowed


def test_psu_open_blocked():
    assert not check_action_text("Open the power supply to inspect the fuse.").allowed


def test_device_specific_block_adds_restriction():
    dev = load_device_blocked(
        [{"pattern": "reach into the fuser", "reason": "hot fuser area"}]
    )
    allowed = check_action_text("Gently pull the paper.", device_blocked=dev)
    blocked = check_action_text("Reach into the fuser to clear the jam.", device_blocked=dev)
    assert allowed.allowed
    assert not blocked.allowed
    assert "hot fuser" in blocked.reasons[0]


def test_escalation_observations():
    assert not check_observations("there is a burning smell now").allowed
    assert not check_observations("smoke coming from it").allowed
    assert not check_observations("it is swollen").allowed
    assert check_observations("the light is amber").allowed


def test_escalation_burnt_variants():
    # "burnt"/"burned" are the same hazard class as "burning" and must escalate.
    assert not check_observations("it smells burnt").allowed
    assert not check_observations("the cable looks burned").allowed


def test_reasons_deduplicated():
    v = check_action_text("open the router case and touch the 220v mains inside")
    assert len(v.reasons) == len(set(v.reasons))
    assert len(v.reasons) >= 2


def test_empty_text_is_allowed():
    assert check_action_text("").allowed

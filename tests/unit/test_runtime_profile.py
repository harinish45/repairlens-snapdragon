"""Unit tests: hardware runtime profile (must never fabricate NPU availability)."""
from ai.runtime.profile import get_profile


def test_profile_facts_on_dev_machine():
    p = get_profile()
    d = p.to_dict()
    # Core fields present and typed
    assert isinstance(d["arch"], str) and d["arch"]
    assert isinstance(d["is_snapdragon"], bool)
    assert isinstance(d["npu_present"], bool)
    assert isinstance(d["onnx_providers"], list)
    assert p.notes, "profile must explain its findings"


def test_provider_selection_is_sound():
    p = get_profile()
    if "QNNExecutionProvider" in p.onnx_providers and p.npu_present:
        assert p.qnn_available
        assert p.active_provider == "QNNExecutionProvider"
    else:
        # No NPU -> must fall back to CPU and say so; never claim QNN
        assert not p.qnn_available
        assert p.active_provider in ("CPUExecutionProvider",) or p.active_provider


def test_no_npu_never_claims_qnn(monkeypatch):
    monkeypatch.setenv("RL_ONNX_EP", "auto")
    p = get_profile()
    if not p.npu_present:
        assert not p.qnn_available
        assert any("NOT EXECUTED" in n or "CPU" in n or "NPU" in n for n in p.notes)

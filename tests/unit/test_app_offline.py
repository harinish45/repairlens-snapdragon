"""Unit tests: offline-connectivity probe (app.main) — the badge/mode logic.

The probe is what makes the UI honest when the network is gone, so its cache and
classification behaviour are pinned by tests (socket calls are injected).
"""
import socket
from contextlib import nullcontext

import app.main as main


def _fake_connect_failing(*_args, **_kwargs):
    raise OSError("network unreachable")


def _fake_connect_ok(*_args, **_kwargs):
    return nullcontext()  # socket.create_connection() is used as a context manager


def _clear_cache() -> None:
    main._state.pop("offline_cache", None)


def setup_function(_func) -> None:  # noqa: ANN001 - pytest hook
    _clear_cache()


def teardown_function(_func) -> None:  # noqa: ANN001 - pytest hook
    _clear_cache()


def test_offline_when_all_connects_fail(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _fake_connect_failing)
    assert main._offline() is True


def test_online_when_any_connect_succeeds(monkeypatch):
    calls: list[tuple] = []

    def connect(addr, timeout=0):
        calls.append(addr)
        if addr[0] == "8.8.8.8":  # first probe (1.1.1.1) fails, second succeeds
            return nullcontext()
        raise OSError("blocked")

    monkeypatch.setattr(socket, "create_connection", connect)
    assert main._offline() is False
    assert [c[0] for c in calls] == ["1.1.1.1", "8.8.8.8"]


def test_cache_prevents_reprobing_within_ttl(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _fake_connect_failing)
    assert main._offline() is True  # caches offline=True

    monkeypatch.setattr(socket, "create_connection", _fake_connect_ok)
    assert main._offline() is True  # TTL not expired -> cached value, no probe

    cached_offline, ts = main._state["offline_cache"]
    main._state["offline_cache"] = (cached_offline, ts - 31)  # expire the cache
    assert main._offline() is False  # re-probes and sees the network

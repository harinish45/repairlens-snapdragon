"""Safety gate (docs/safety.md).

Defense in depth: blocked-action patterns are applied to (a) every action text the
system is about to recommend, and (b) per-device `blocked_actions` declared in
knowledge YAML. Any hit -> STOPPED_UNSAFE, never a recommendation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Global blocked patterns (never override these in device YAML).
GLOBAL_BLOCKED: tuple[tuple[str, str], ...] = (
    (r"mains electricity|electrician|220\s*v|240\s*v|120\s*v|high voltage",
     "Mains electricity work is never performed."),
    (r"swollen|bulging|spill(ing)? (battery|capacitor)|damaged battery",
     "Physically damaged batteries require qualified service."),
    (r"exposed (wires?|conductors?|live parts)",
     "Exposed electrical components are unsafe to handle."),
    (r"discharg(e|ing) (the )?capacitors?",
     "Capacitor discharge is a qualified-service procedure."),
    (r"open(ing)? the (power supply|psu|transformer)",
     "Opening power supplies is unsafe."),
    (r"cut(ting)? (the|live) (wire|cable) (while|with).*power",
     "Never cut or modify powered cabling."),
    (r"open(ing)? the .*(case|enclosure|chassis|housing|back panel|internals)",
     "Opening equipment enclosures is unsafe."),
)

# Escalation phrases: checked against user-reported observations.
ESCALATION: tuple[tuple[str, str], ...] = (
    (r"burning|burnt|burned|smoke|smoking|spark|scorch|melting", "burning/smoke/sparks"),
    (r"hot to touch|very hot|extremely hot", "excessive heat"),
    (r"liquid|water|spilled|coffee.*inside", "liquid ingress"),
    (r"swollen|bulging|battery.*swell", "battery deformation"),
    (r"buzzing|humming loudly|crackling", "unusual electrical noise"),
)


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.allowed


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def check_action_text(action_text: str, device_blocked: tuple[tuple[str, str], ...] = ()) -> SafetyVerdict:
    """Return allowed=False if the recommended action matches any blocked pattern."""
    reasons: list[str] = []
    for pattern, reason in GLOBAL_BLOCKED + device_blocked:
        if _compile(pattern).search(action_text):
            reasons.append(reason)
    return SafetyVerdict(allowed=not reasons, reasons=tuple(dict.fromkeys(reasons)))


def check_observations(observed_text: str) -> SafetyVerdict:
    """User-reported observations that force an immediate escalation."""
    reasons: list[str] = []
    for pattern, label in ESCALATION:
        if _compile(pattern).search(observed_text):
            reasons.append(f"observed {label}")
    return SafetyVerdict(allowed=not reasons, reasons=tuple(dict.fromkeys(reasons)))


def load_device_blocked(patterns: list[dict] | list) -> tuple[tuple[str, str], ...]:
    """Normalize knowledge-YAML blocked_actions entries to (pattern, reason) tuples."""
    out: list[tuple[str, str]] = []
    for item in patterns or []:
        if isinstance(item, dict):
            out.append((str(item.get("pattern", "")), str(item.get("reason", "blocked by device policy"))))
        elif isinstance(item, str):
            out.append((item, "blocked by device policy"))
    return tuple(out)

"""Load and query the local knowledge base (knowledge/devices/*.yaml).

No vector DB (ADR-006): structured YAML + in-process retrieval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "devices"


@dataclass(frozen=True)
class DeviceDoc:
    device_id: str
    name: str
    category: str
    safety_class: str
    summary: str
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def indicators(self) -> list[dict[str, Any]]:
        return list(self.raw.get("indicators", []))

    @property
    def symptoms(self) -> list[dict[str, Any]]:
        return list(self.raw.get("symptoms", []))

    @property
    def hypotheses(self) -> list[dict[str, Any]]:
        return list(self.raw.get("hypotheses", []))

    @property
    def blocked_actions(self) -> list[dict[str, Any]]:
        return list(self.raw.get("blocked_actions", []))

    @property
    def escalation_conditions(self) -> list[str]:
        return [str(x) for x in self.raw.get("escalation_conditions", [])]

    @property
    def resolution_criteria(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in (self.raw.get("resolution_criteria") or {}).items()}

    def indicator_values(self, indicator_id: str) -> list[dict[str, Any]]:
        for ind in self.indicators:
            if ind.get("id") == indicator_id:
                return list(ind.get("observed_values", []))
        return []


class KnowledgeBase:
    def __init__(self, devices_dir: Path | None = None) -> None:
        self.devices_dir = Path(devices_dir) if devices_dir else KNOWLEDGE_DIR
        self.devices: dict[str, DeviceDoc] = {}
        self.load_errors: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.devices_dir.is_dir():
            self.load_errors.append(f"devices dir missing: {self.devices_dir}")
            return
        for path in sorted(self.devices_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "device_id" not in data:
                    self.load_errors.append(f"{path.name}: missing device_id")
                    continue
                doc = DeviceDoc(
                    device_id=str(data["device_id"]),
                    name=str(data.get("name", data["device_id"])),
                    category=str(data.get("category", "unknown")),
                    safety_class=str(data.get("safety_class", "unknown")),
                    summary=str(data.get("summary", "")),
                    raw=data,
                )
                self.devices[doc.device_id] = doc
            except Exception as exc:  # noqa: BLE001 - never crash the app on one bad file
                self.load_errors.append(f"{path.name}: {exc}")

    # ---- queries -------------------------------------------------------
    def get(self, device_id: str) -> DeviceDoc | None:
        return self.devices.get(device_id)

    def all_devices(self) -> list[DeviceDoc]:
        return list(self.devices.values())

    def match_symptom(self, device: DeviceDoc, text: str) -> dict[str, Any] | None:
        """Pick the symptom whose keywords appear most in the user text."""
        lowered = text.lower()
        best: dict[str, Any] | None = None
        best_hits = 0
        for sym in device.symptoms:
            hits = sum(1 for kw in sym.get("keywords", []) if re.search(re.escape(str(kw)), lowered))
            if hits > best_hits:
                best, best_hits = sym, hits
        return best

    def indicator_state_map(self, device: DeviceDoc) -> dict[str, str]:
        """indicator_id -> canonical observed value key prefix used by evidence
        (e.g. 'led_amber_solid'). Maps raw values like 'green_solid' -> 'led_green_solid'."""
        out: dict[str, str] = {}
        for ind in device.indicators:
            out[str(ind.get("id"))] = str(ind.get("id"))
        return out


def evidence_tags_for_value(value: str) -> list[str]:
    """Turn an observed indicator value into evidence tags used by hypothesis filters.

    'amber_solid' -> ['led_amber_solid']; 'off' -> ['led_off', 'led_not_green'] etc.
    """
    if not value or value == "unknown":
        return ["led_unknown", "led_not_green"]
    tags = [f"led_{value}"]
    if not value.startswith("green_solid"):
        tags.append("led_not_green")
    return tags

"""Runtime hardware abstraction: detect Snapdragon/NPU/QNN at startup (docs/architecture.md §4).

Nothing here is assumed — every field is either measured on this machine or
explicitly marked as unavailable.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, asdict
from functools import lru_cache


@dataclass(frozen=True)
class HardwareProfile:
    os: str
    arch: str                     # AMD64 | ARM64
    cpu: str
    is_snapdragon: bool
    npu_present: bool             # any NPU device node detected
    onnx_providers: tuple[str, ...]
    active_provider: str          # provider the app will use
    qnn_available: bool           # QNN EP usable right now
    llama_server_available: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["onnx_providers"] = list(self.onnx_providers)
        d["notes"] = list(self.notes)
        return d


def _cpu_name() -> str:
    try:
        import ctypes

        class SYSTEM_INFO(ctypes.Structure):
            _fields_ = [
                ("wProcessorArchitecture", ctypes.c_ushort),
                ("wReserved", ctypes.c_ushort),
                ("dwPageSize", ctypes.c_uint32),
                ("lpMinimumApplicationAddress", ctypes.c_void_p),
                ("lpMaximumApplicationAddress", ctypes.c_void_p),
                ("dwActiveProcessorMask", ctypes.c_wulong_p),
                ("dwNumberOfProcessors", ctypes.c_uint32),
                ("dwProcessorType", ctypes.c_uint32),
                ("dwAllocationGranularity", ctypes.c_uint32),
                ("wProcessorLevel", ctypes.c_ushort),
                ("wProcessorRevision", ctypes.c_ushort),
            ]

        info = SYSTEM_INFO()
        ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(info))  # type: ignore[attr-defined]
        arch_map = {9: "x64", 12: "ARM64"}
        return arch_map.get(info.wProcessorArchitecture, str(info.wProcessorArchitecture))
    except Exception:  # noqa: BLE001
        return platform.processor() or "unknown"


def _detect_npu_and_snapdragon() -> tuple[bool, bool, list[str]]:
    """Return (is_snapdragon, npu_present, notes). Windows-only probing."""
    notes: list[str] = []
    is_snapdragon = False
    npu_present = False
    if os.name != "nt":
        notes.append("non-Windows host: Snapdragon/NPU probing skipped")
        return False, False, notes
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        is_snapdragon = any(k in out.lower() for k in ("snapdragon", "qualcomm", "hexagon"))
        if is_snapdragon:
            notes.append(f"Snapdragon CPU detected: {out}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"CPU probe failed: {exc}")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
             "Where-Object { $_.FriendlyName -match 'Neural|Hexagon|AI Engine' -and $_.FriendlyName -notmatch 'Input' } | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
        npu_present = out.isdigit() and int(out) > 0
        if npu_present:
            notes.append("NPU device node present")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"NPU probe failed: {exc}")
    if not is_snapdragon:
        notes.append("No Snapdragon CPU detected (development machine)")
    if not npu_present:
        notes.append("No NPU device node — NPU claims must read NOT EXECUTED")
    return is_snapdragon, npu_present, notes


def _onnx_providers() -> tuple[str, ...]:
    try:
        import onnxruntime as ort

        return tuple(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return ()


@lru_cache(maxsize=1)
def get_profile(llama_server_path: str | None = None) -> HardwareProfile:
    is_snapdragon, npu_present, notes = _detect_npu_and_snapdragon()
    providers = _onnx_providers()
    qnn = "QNNExecutionProvider" in providers and npu_present
    forced = os.environ.get("RL_ONNX_EP", "auto").strip()
    if forced and forced != "auto" and forced in providers:
        active = forced
    elif qnn:
        active = "QNNExecutionProvider"
    elif "CPUExecutionProvider" in providers:
        active = "CPUExecutionProvider"
    else:
        active = providers[0] if providers else "none"
    if not qnn:
        notes.append("QNN EP unavailable — CPU fallback in effect")
    llama = False
    candidate = llama_server_path or os.environ.get("RL_LLAMA_SERVER", "")
    if candidate:
        llama = os.path.isfile(candidate)
    return HardwareProfile(
        os=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        cpu=_cpu_name(),
        is_snapdragon=is_snapdragon,
        npu_present=npu_present,
        onnx_providers=providers,
        active_provider=active,
        qnn_available=qnn,
        llama_server_available=llama,
        notes=tuple(notes),
    )

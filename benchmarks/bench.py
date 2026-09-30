"""RepairLens benchmark harness — honest by construction.

Measures only what the current machine can actually execute:

  vision.led_classify : full JPEG decode + LED/indicator classification (in-process, CPU)
  asr.tiny.en         : faster-whisper latency on a short spoken wav (CPU/int8)
  npu.qnn_inference   : NOT EXECUTED unless a Snapdragon NPU + QNN EP is present.
                        MVP vision is classical CV (ADR-005) — there is no NPU kernel
                        to execute; the entry exists so the report can never overclaim.

Output: benchmarks/results/latest.json, served by GET /api/benchmarks and rendered
in the UI (fields: hardware, runs, results[].{name,status,p50_ms,p95_ms,ep,note}).

Usage:
    python benchmarks/bench.py [--runs 30] [--asr-runs 4] [--skip-asr] [--out PATH]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from ai.runtime.profile import get_profile  # noqa: E402
from ai.vision.led import analyze_indicator, load_frame  # noqa: E402

DASH = "—"  # em dash for "not measured"
MARKER = "@@RESULT@@"  # child-process result line prefix (stage isolation)


def _pctl(sorted_ms: list[float], q: float) -> float:
    """Nearest-rank percentile on a pre-sorted list."""
    if not sorted_ms:
        return float("nan")
    idx = min(len(sorted_ms) - 1, max(0, math.ceil(q * len(sorted_ms)) - 1))
    return sorted_ms[idx]


def _stats(samples_ms: list[float]) -> dict:
    s = sorted(samples_ms)
    return {
        "runs": len(s),
        "p50_ms": round(_pctl(s, 0.50), 2),
        "p95_ms": round(_pctl(s, 0.95), 2),
        "min_ms": round(s[0], 2),
        "max_ms": round(s[-1], 2),
        "mean_ms": round(sum(s) / len(s), 2),
    }


# ---- vision ----------------------------------------------------------------
def _synthetic_frames() -> list[tuple[str, bytes, str]]:
    """(label, jpeg_bytes, expected_state) — dark frame with one bright saturated LED."""
    variants = [
        ("amber", (255, 160, 10), "amber_solid"),
        ("green", (20, 230, 40), "green_solid"),
        ("red", (240, 30, 30), "red_solid"),
        ("off", None, "off"),
    ]
    frames = []
    for label, rgb, expected in variants:
        arr = np.full((480, 640, 3), 18, dtype=np.uint8)
        if rgb is not None:
            cy, cx, r = 240, 320, 14
            yy, xx = np.ogrid[:480, :640]
            mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
            arr[mask] = rgb
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG", quality=92)
        frames.append((label, buf.getvalue(), expected))
    return frames


def bench_vision(runs: int, warmup: int = 5) -> dict:
    frames = _synthetic_frames()
    for i in range(warmup):  # warm caches (PIL decode, numpy allocator) before sampling
        _, data, _ = frames[i % len(frames)]
        img = load_frame(data)
        analyze_indicator(img)
    lat: list[float] = []
    ok = 0
    total = 0
    for i in range(runs):
        label, data, expected = frames[i % len(frames)]
        t0 = time.perf_counter()
        img = load_frame(data)
        obs = analyze_indicator(img)
        lat.append((time.perf_counter() - t0) * 1000.0)
        total += 1
        ok += int(obs.state == expected)
    return {
        "name": "vision.led_classify",
        "status": "OK",
        "ep": "CPU (numpy+Pillow, classical CV)",
        "accuracy": f"{ok}/{total}",
        **_stats(lat),
    }



# ---- ASR -------------------------------------------------------------------
def _speech_wav() -> tuple[bytes, str]:
    """Real speech via Windows SAPI if possible; otherwise a 3 s tone (portable)."""
    if os.name == "nt":
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "bench.wav"
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.SetOutputToWaveFile('{path}'); "
                    "$s.Speak('My router status light is orange and the wifi is not working.'); "
                    "$s.Dispose()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", script],
                               capture_output=True, timeout=60, check=True)
                data = path.read_bytes() if path.is_file() else b""
                if data:
                    return data, "Windows SAPI TTS: 'My router status light is orange and the wifi is not working.'"
        except Exception:  # noqa: BLE001 - fall through to tone
            pass
    rate, seconds = 16000, 3.0
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    tone = (0.25 * np.sin(2 * math.pi * 440 * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone.tobytes())
    return buf.getvalue(), "synthetic 440 Hz tone (no TTS available — transcript may be empty)"


def bench_asr(runs: int) -> dict:
    from ai.speech.transcriber import ASRError, Transcriber

    wav, source = _speech_wav()
    tr = Transcriber()
    lat: list[float] = []
    text = ""
    warmup_ms = None
    try:
        for i in range(runs + 1):  # one extra warm-up run (model load), excluded
            t0 = time.perf_counter()
            t = tr.transcribe_bytes(wav, suffix=".wav")
            ms = (time.perf_counter() - t0) * 1000.0
            if i == 0:
                warmup_ms = round(ms, 2)
                text = t.text
            else:
                lat.append(ms)
    except ASRError as exc:
        return {"name": "asr.tiny.en", "status": "SKIPPED", "ep": "cpu/int8",
                "p50_ms": DASH, "p95_ms": DASH, "note": f"model unavailable: {exc}"[:220]}
    return {
        "name": "asr.tiny.en",
        "status": "OK",
        "ep": f"CPU (faster-whisper, device={tr.device}, {tr.compute_type})",
        "language": t.language,
        "audio_source": source,
        "first_run_ms": warmup_ms,
        "transcript_sample": text[:120],
        **_stats(lat),
    }



# ---- NPU / QNN -------------------------------------------------------------
def bench_npu(profile) -> dict:
    if profile.npu_present and profile.qnn_available:
        note = ("NPU + QNN EP present, but MVP vision is classical CV (ADR-005) — "
                "no neural kernel exists to execute on the NPU yet.")
        ep = "QNNExecutionProvider (available)"
    elif profile.npu_present:
        note = "NPU device present but QNN EP unavailable in this Python environment."
        ep = "QNNExecutionProvider (unavailable)"
    else:
        note = "No NPU device node on this machine — QNN claims must read NOT EXECUTED."
        ep = "QNNExecutionProvider (no NPU)"
    return {"name": "npu.qnn_inference", "status": "NOT EXECUTED", "ep": ep,
            "p50_ms": DASH, "p95_ms": DASH, "note": note}


# ---- main ------------------------------------------------------------------
def _stage_entry(stage: str, runs: int, asr_runs: int, skip_asr: bool) -> dict:
    if stage == "vision":
        return bench_vision(runs)
    if stage == "asr":
        if skip_asr:
            return {"name": "asr.tiny.en", "status": "SKIPPED", "ep": "cpu/int8",
                    "p50_ms": DASH, "p95_ms": DASH, "note": "--skip-asr was passed"}
        return bench_asr(asr_runs)
    if stage == "npu":
        return bench_npu(get_profile())
    raise ValueError(f"unknown stage {stage!r}")


def _run_stage_isolated(stage: str, runs: int, asr_runs: int, skip_asr: bool) -> dict:
    """Run one stage in a fresh interpreter.

    Why subprocess isolation: the Snapdragon/NPU probe runs WMI/PnP PowerShell
    queries, whose background churn (WmiPrvSE) slows this machine ~4x for tens of
    seconds — enough to corrupt any timing measured in the same process. Thread
    pools from model runtimes (ctranslate2/onnxruntime) can interact similarly.
    Each stage therefore gets a private process; only the timing-free parent
    probes hardware, and only after all stages have finished.
    """
    cmd = [sys.executable, str(Path(__file__).resolve()), "--only", stage,
           "--runs", str(runs), "--asr-runs", str(asr_runs)]
    if skip_asr:
        cmd.append("--skip-asr")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER):])
    tail = (proc.stderr or proc.stdout or "").strip()[-220:]
    return {"name": stage, "status": "SKIPPED", "ep": "-", "p50_ms": DASH, "p95_ms": DASH,
            "note": f"stage process failed (rc={proc.returncode}): {tail}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="RepairLens benchmarks")
    ap.add_argument("--runs", type=int, default=30, help="vision sample count")
    ap.add_argument("--asr-runs", type=int, default=4, help="asr sample count (warm-up excluded)")
    ap.add_argument("--skip-asr", action="store_true")
    ap.add_argument("--only", choices=["vision", "asr", "npu"], default=None,
                    help="internal: run a single stage and print one @@RESULT@@ json line")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results" / "latest.json"))
    args = ap.parse_args()

    if args.only:  # child stage mode — no hardware probing, print and exit
        entry = _stage_entry(args.only, args.runs, args.asr_runs, args.skip_asr)
        print(MARKER + json.dumps(entry))
        return 0

    results = [_run_stage_isolated(s, args.runs, args.asr_runs, args.skip_asr)
               for s in ("vision", "asr", "npu")]

    # Probe hardware only now, after all timing work is done (WMI churn is harmless here).
    profile = get_profile()
    hw = (f"{profile.os} | {profile.arch} | {profile.cpu} | "
          f"snapdragon={'yes' if profile.is_snapdragon else 'no'} | "
          f"npu={'present' if profile.npu_present else 'NOT PRESENT'} | "
          f"active_ep={profile.active_provider}")

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hardware": hw,
        "runs": args.runs,
        "results": results,
        "notes": [
            "All numbers measured on this machine; nothing simulated or extrapolated.",
            "Each stage runs in an isolated subprocess; hardware probing happens only after timing.",
            "NPU/QNN entries read NOT EXECUTED unless a Snapdragon NPU with QNN EP is present.",
            "Latency percentiles use the nearest-rank method over warm runs only.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"hardware : {hw}")
    print(f"python   : {report['python']}")
    for r in results:
        extra = " ".join(f"{k}={r[k]}" for k in ("accuracy", "language", "first_run_ms")
                         if k in r)
        print(f"  {r['name']:<22} {r['status']:<12} p50={r['p50_ms']}ms "
              f"p95={r['p95_ms']}ms ep={r['ep']} {extra}".rstrip())
        if r.get("note"):
            print(f"    note: {r['note']}")
    print(f"written  : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


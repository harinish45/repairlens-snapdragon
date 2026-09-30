# RepairLens — Benchmarks

**Rule (challenge §18/§30):** a number may appear in this file, the UI, or the pitch **only if**
`scripts/run_benchmarks.ps1` measured it on the machine it claims. Nothing is extrapolated,
simulated, or copied from vendor material.

## How to run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1            # vision + ASR + NPU honesty entry
powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1 -SkipAsr   # vision only
python benchmarks\bench.py --runs 50 --asr-runs 5                              # direct invocation
python benchmarks\bench.py --only vision                                       # single stage, prints JSON
```

Results are written to `benchmarks/results/latest.json` (git-ignored — it is machine-specific)
and served to the UI by `GET /api/benchmarks` (panel "Snapdragon / System → Benchmarks").

## What is measured

| Entry | Pipeline under test | Notes |
|---|---|---|
| `vision.led_classify` | JPEG bytes → `load_frame` (PIL decode, ≤640 px) → `analyze_indicator` (numpy HSV blob analysis) | end-to-end as `/api/observe` runs it, minus HTTP |
| `asr.tiny.en` | wav bytes → faster-whisper `tiny.en` int8, VAD on, beam 1 | model warm-up run excluded; audio = real TTS speech |
| `npu.qnn_inference` | Snapdragon NPU via QNN execution provider | **NOT EXECUTED** unless NPU + QNN EP are actually present; MVP vision is classical CV (ADR-005), so there is no neural kernel to run on the NPU yet — the entry exists so the report can never overclaim |

## Methodology (and why it is this way)

- **Warm runs only.** Vision: 5 warm-up iterations first. ASR: one full warm-up transcription
  (model load) excluded; its duration is reported separately as `first_run_ms`.
- **Nearest-rank percentiles** over the samples; `runs` records the sample count
  (defaults: 30 vision / 4 ASR).
- **Stage isolation in subprocesses.** Each stage runs in a fresh interpreter and hardware probing
  happens only *after* timing. Reason: the Snapdragon/NPU probe runs WMI/PnP PowerShell queries
  whose background churn (`WmiPrvSE`) was measured to slow this machine ~4× for tens of seconds —
  enough to turn a 27 ms pipeline into a 106 ms "result". Isolation makes the numbers reproducible.
- **Same input classes as the demo.** Vision frames are 640×480 JPEGs (dark scene, one bright
  saturated indicator); the ASR clip is a spoken router symptom.

## Latest measured results

Environment: Windows 11 · AMD64 · Intel64 Family 6 Model 186 (low-power E-core class) · Python 3.14.2 ·
provider `CPUExecutionProvider` · Snapdragon: **no** · NPU: **NOT PRESENT**.
(`generated_at` in `latest.json` records the exact run.)

| Entry | p50 | p95 | min | max | n | Correctness |
|---|---|---|---|---|---|---|
| `vision.led_classify` | **27.6 ms** | 31.8 ms | 24.9 ms | 34.1 ms | 30 | 30/30 correct classifications (amber/green/red/off) |
| `asr.tiny.en` | **0.90 s** | 1.02 s | 0.34 s | 1.02 s | 4 | correct transcript: "My router status light is orange and the Wi-Fi is not working." (6.8 s audio; first run incl. model load 1.97 s) |
| `npu.qnn_inference` | — | — | — | — | 0 | **NOT EXECUTED — no NPU on this machine** |

Interpretation notes:

- Vision latency **includes** JPEG decode; classification alone is ~26 ms of that on this CPU.
  The lens matters: this is a throttled efficiency-core laptop CPU, not the audited Snapdragon
  device — numbers here are a floor for the demo machine, not a Snapdragon claim.
- ASR spread (0.34–1.02 s) reflects scheduling on this low-power CPU; p50 is the number to quote.

## Honesty rules for NPU cells

- NPU rows may read **VERIFIED** only after this script reports measured QNN EP numbers on the
  audited Snapdragon device (see `docs/hardware-audit.md`).
- Until then, every surface (UI badge, benchmark panel, pitch) must show
  **NOT EXECUTED / EXPECTED** — never "optimized for NPU".

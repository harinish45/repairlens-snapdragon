# RepairLens

**An offline-first multimodal repair assistant** — a technician workflow that
**SEEs** the device, **HEARs** the complaint, **UNDERSTANDs** the symptom,
**DIAGNOSEs** candidate faults, **GUIDEs** one safe step at a time, and **VERIFIEs**
the fix by looking again. Everything runs on `localhost`; no cloud calls in the loop.

Built for the Snapdragon AI Lab Build & Present Challenge — designed Snapdragon-first,
built and measured on a PC, with **no fabricated NPU numbers** (see Honesty below).

## What it does

```
CAMERA ──▶ ai/vision      LED/indicator evidence (classical CV, 27 ms end-to-end)
MIC    ──▶ ai/speech      local speech → text (faster-whisper tiny.en, ~0.9 s)
           ai/reasoning   symptom structuring / explanation (local LLM, template fallback)
           knowledge/     curated device YAML + BM25 retrieval (router, monitor, printer)
           diagnostics/   deterministic state machine + rules + SAFETY GATE
UI     ◀── next safe action (one step), then re-observe to verify the fix
```

The interview loop is explicit, not hidden in a prompt:
`IDLE → DEVICE_DETECTED → SYMPTOM_IDENTIFIED → EVIDENCE_COLLECTED → HYPOTHESIS_GENERATED →
ACTION_RECOMMENDED → ACTION_PERFORMED → RESULT_OBSERVED → RESOLVED` (or `NEXT_HYPOTHESIS` /
`STOPPED_UNSAFE` / `ESCALATE_SERVICE`). Every transition is logged, unit-tested, and shown in the UI.

## Quickstart

```powershell
python -m pip install -r requirements.txt        # pinned, incl. the load-bearing av<19 pin
copy .env.example .env                           # optional overrides
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

First ASR use downloads `tiny.en` (~75 MB) once; after that the HEAR path works with
the network cable pulled. The LLM path uses a local `llama-server` if one is running
(`RL_LLM_ENABLED`), otherwise a deterministic template fallback — the loop never depends on it.

## 90-second demo

1. **Device** → click *Home Wi-Fi Router* → `DEVICE_DETECTED`.
2. Type *"wifi keeps dropping and the status light is orange"* (or press *Record symptom*
   and speak) → `SYMPTOM_IDENTIFIED (no_network)`.
3. *Start camera*, point at the router indicator, *Capture evidence* →
   `LED: amber · amber_solid · conf=99%` → `HYPOTHESIS_GENERATED` → `ACTION_RECOMMENDED`:
   *"Reseat the WAN/Internet cable…"* with the expected visual change spelled out.
4. Perform the step, click *I performed the action* → `ACTION_PERFORMED`.
5. Reseat works, LED turns green → *Re-observe indicator* →
   `RESOLVED — Verified: indicator changed amber_solid → green_solid`.

The system prompt asks for exactly one safe action, refuses unsafe scope (safety gate),
and never claims the problem is fixed until it has *seen* the change.

## Verify it yourself

```powershell
python -m pytest tests -q          # 56 tests: state machine, safety, KB/BM25, vision, closed loop
python scripts\e2e_smoke.py        # full closed loop against the running server (incl. vision) → PASS
python scripts\asr_smoke.py x.wav  # audio path: real speech → transcript over /api/transcribe
```

## Benchmarks (measured, not claimed)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1
```

Writes `benchmarks/results/latest.json`, rendered live in the UI (*Benchmarks* panel).
Latest run on this dev machine (Windows 11 · low-power Intel · Python 3.14):

| Entry | Result |
|---|---|
| `vision.led_classify` | **p50 27.6 ms** / p95 31.8 ms · 30/30 correct (JPEG decode included) |
| `asr.tiny.en` | **p50 0.90 s** for 6.8 s audio · correct transcript |
| `npu.qnn_inference` | **NOT EXECUTED** — no NPU on this machine |

Methodology and honesty rules: [`docs/benchmarks.md`](docs/benchmarks.md). Each stage runs in an
isolated subprocess so hardware probing (WMI churn) cannot contaminate timings.

## Repository layout

```
app/            FastAPI server (main.py) + browser UI (ui/: index.html, app.js, styles.css)
ai/             vision (LED analytics) · speech (whisper) · reasoning (LLM client + fallback)
                runtime (Snapdragon/NPU/EP detection) · embeddings (BM25)
diagnostics/    state machine · rules/hypotheses · safety gate
knowledge/      curated YAML device files (router, monitor, printer) + loader + retrieval
benchmarks/     bench.py + results/latest.json (machine-specific, git-ignored)
scripts/        run_benchmarks.ps1 · e2e_smoke.py · asr_smoke.py
tests/          unit + integration (closed loop) — 56 tests
docs/           architecture · decisions (ADRs) · models · benchmarks · safety · hardware-audit
presentation/   pitch + demo script for the competition
```

## Honesty statement (what is real vs. expected)

- **Real, measured on this machine:** the full closed loop, LED vision latency + accuracy,
  ASR latency + transcripts, CPU execution provider, tests, benchmark harness.
- **Snapdragon / NPU:** *this dev machine has neither.* Every surface shows
  `Snapdragon: no`, `NPU: NOT PRESENT`, `QNN EP: NOT EXECUTED (no NPU)`. NPU rows in
  [`docs/architecture.md`](docs/architecture.md) are marked EXPECTED and may only become
  VERIFIED after the benchmark script runs on the audited Snapdragon device.
- **LLM:** template fallback unless a local `llama-server` is up (badge shows which).
- **Vision scope:** single-frame LED/indicator analytics (classical CV). Blinking detection
  and VLM-based scene understanding are explicitly out of MVP scope (ADR-005).

## Known limitations

- ASR is English-only (`tiny.en`) and single-utterance; typed symptoms are always available.
- The dependency pin `av==18.1.0` is load-bearing for speech — see ADR-009 in
  [`docs/decisions.md`](docs/decisions.md) before upgrading audio dependencies.
- Safety scope is deliberately narrow: the gate allows only user-serviceable, low-risk steps
  and escalates anything involving mains voltage or disassembly
  ([`docs/safety.md`](docs/safety.md)).

## Docs index

| Doc | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | pipeline, state machine, workload placement, runtime abstraction |
| [`docs/decisions.md`](docs/decisions.md) | product decision gate + ADR-001…009 |
| [`docs/models.md`](docs/models.md) | model registry: versions, sizes, runtimes, fallbacks |
| [`docs/benchmarks.md`](docs/benchmarks.md) | how numbers are produced and what they may claim |
| [`docs/safety.md`](docs/safety.md) | evidence vocabulary, allowed/blocked scope, escalation |
| [`docs/hardware-audit.md`](docs/hardware-audit.md) | Snapdragon/NPU feasibility audit of the dev machine |

## License

MIT — see [`LICENSE`](LICENSE).


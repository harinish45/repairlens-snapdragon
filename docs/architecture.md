# RepairLens — System Architecture

## 1. Pipeline (SEE → HEAR → UNDERSTAND → DIAGNOSE → GUIDE → VERIFY)

```
CAMERA (browser getUserMedia)          MIC (browser getUserMedia)
      │ JPEG frame                          │ WAV/Opus blob
      ▼                                     ▼
ai/vision: device-class +             ai/speech: faster-whisper
indicator/LED color evidence           local transcription (CPU int8)
      │                                     │
      └──────────────┬──────────────────────┘
                     ▼
        ┌── LOCAL AI REASONING (llama-server, localhost) ──┐
        │  symptom structuring + explanation of candidate  │
        │  hypotheses (LLM cannot invent transitions)      │
        └──────────────┬───────────────────────────────────┘
                       ▼
        KNOWLEDGE RETRIEVAL (BM25 over knowledge/devices/*.yaml + docs)
                       ▼
        DIAGNOSTIC ENGINE (explicit state machine + rules + safety gate)
                       ▼
        NEXT ACTION (one safe, verified step with expected visual change)
                       ▼
        USER ACTION → CAMERA RE-OBSERVES → STATE VERIFICATION
                       ▼
        STATE_CHANGED? ── YES → RESOLVED / NEXT_STEP
                          └─ NO  → NEXT_HYPOTHESIS
```

## 2. Diagnostic state machine (explicit — never hidden in a prompt)

States: `DEVICE_DETECTED → SYMPTOM_IDENTIFIED → EVIDENCE_COLLECTED →
HYPOTHESIS_GENERATED → ACTION_RECOMMENDED → ACTION_PERFORMED → RESULT_OBSERVED →
(STATE_CHANGED? YES→RESOLVED/NEXT_DIAGNOSTIC_STEP | NO→NEXT_HYPOTHESIS)`

Plus terminal safety state `STOPPED_UNSAFE` and `ESCALATE_SERVICE`.
Transitions live in `diagnostics/state_machine/`, are deterministic, and unit-tested.

## 3. Workload placement table (Snapdragon-first)

| Workload | CPU | GPU | NPU | Reason |
|---|---|---|---|---|
| Speech recognition (faster-whisper int8) | VERIFIED (baseline) | – | **EXPECTED** — AI Hub speech models via QNN EP; NOT EXECUTED | CTranslate2 = CPU; NPU path needs QNN EP build |
| Image understanding (ONNX classifier) | VERIFIED (baseline) | – | **EXPECTED** — QNN EP; NOT EXECUTED | ONNX model; QNN EP documented by Qualcomm |
| Indicator/LED color analytics | VERIFIED | – | N/A | classical CV, no neural net |
| OCR (MVP: none; future PaddleOCR ONNX) | future | – | EXPECTED | deferred (ADR-005) |
| Local language model (llama.cpp) | VERIFIED | optional Vulkan | **N/A — llama.cpp does not target NPU** | honest limitation |
| Embeddings (BM25, optional ONNX embedder) | VERIFIED | – | EXPECTED (embedder only) | BM25 is non-neural |
| Retrieval (BM25 in-process) | VERIFIED | – | N/A | non-neural |
| Diagnostic engine (rules + state machine) | VERIFIED | – | N/A | deterministic Python |
| UI (browser, localhost) | VERIFIED | – | N/A | rendering only |

NPU cells may only be upgraded from EXPECTED → VERIFIED after `scripts/run_benchmarks.ps1`
reports measured QNN EP numbers on the audited Snapdragon device.

## 4. Runtime abstraction (`ai/runtime/`)

`HardwareProfile` detects at startup: CPU arch (x64/ARM64), Snapdragon SoC (WMI/registry),
NPU device presence, ONNX Runtime available execution providers, llama-server availability.
Provider selection: `QNN` if QNN EP + device present → else `CPU`. Exposed in `/api/status`
and rendered in the UI system panel (LOCAL / OFFLINE / MODEL / DEVICE / EP).

## 5. Offline design

- **Local (always):** camera frames, mic audio, ASR, vision, retrieval, diagnostics, LLM, UI, knowledge.
- **Optional network:** one-time model downloads (`scripts/setup_models.ps1`), repo updates.
- Connectivity prober → `OFFLINE MODE` banner; offline disables nothing in the core loop
  (there are no cloud calls in the core loop by design).
- Privacy: frames/audio never leave `localhost`; no telemetry.

## 6. API surface (FastAPI, localhost only)

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | hardware profile, providers, offline flag, model availability |
| `POST /api/session/start` | begin diagnostic session |
| `POST /api/observe` | submit frame → evidence extraction → state transition |
| `POST /api/transcribe` | submit audio → transcript |
| `POST /api/symptom` | submit (typed or transcribed) symptom text |
| `POST /api/action_done` | user reports action performed |
| `GET /api/session` | current state, evidence, hypotheses, next action, confidence |
| `GET /api/benchmarks` | last benchmark results (real numbers only) |
| `GET /api/health` | liveness |

## 7. Failure handling contract
Every subsystem returns structured errors (`code`, `message`, `user_message`); UI shows the
user_message verbatim (e.g. "I can't reliably see the device…"). Model load failure →
degraded mode flags in `/api/status`, never a crash, never fake data.

## 8. Evidence classification (used throughout UI and docs)
`OBSERVED` (sensor-derived) / `LIKELY` (rules+LLM inference) / `UNCERTAIN` (below confidence
thresholds). Confidence thresholds configured in `.env`, defaults documented in `docs/safety.md`.

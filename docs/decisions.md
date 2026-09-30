# RepairLens — Product Decision Gate & Architecture Decision Records

## Part A — Product Decision Gate (required before build)

### Problem
When a device (router, printer, monitor, laptop dock…) misbehaves, users must read manuals,
search the web, decode technical terms, and — critically — **manually judge whether the fix
worked**. AI assistants give one-shot advice but cannot watch the device before/after an action.

### Target user
Non-expert device owners and frontline IT support staff doing safe, first-line troubleshooting
of consumer/network/IT equipment (routers, printers, monitors, laptops, cables, peripherals).

### Existing alternatives
1. Static manuals / support sites — generic, not device-state aware.
2. Web search / cloud chatbots — good text advice, no continuous observation, needs network,
   data leaves the device.
3. Vendor troubleshooting wizards — fixed decision trees, no perception.
4. Human remote support — expensive, scheduling latency.

### Gap
None of these **close the loop**: observe device → advise → user acts → **re-observe and verify
the state actually changed**. Verification today is manual and error-prone ("is that light
green now?").

### AI advantage
Vision (device/indicator recognition), speech (hands-free symptom report), and local language
reasoning (grounded hypothesis generation) must be combined and re-evaluated after each action —
rules alone cannot interpret free-form video/audio evidence.

### Multimodal advantage
The camera carries the ground truth of the physical state (LED color, cable seating, display
message); the microphone carries the user's symptom description. Neither alone closes the loop.

### Snapdragon advantage
A closed perception→reasoning loop must run with low latency, privately, and **without network**.
Running ASR + vision + embeddings + local LLM concurrently is a sustained multi-model workload
where Snapdragon's heterogeneous CPU/GPU/NPU design and high memory bandwidth pay off versus
a thin client sending frames to the cloud.

### NPU advantage (strict classification)
- **EXPECTED (RESEARCHED path):** ONNX-based vision/embedding/ASR models can target the Hexagon
  NPU via ONNX Runtime QNN EP (Qualcomm doc 80-62010-1) — **NOT EXECUTED**, no Snapdragon device audited yet.
- **NOT APPLICABLE:** llama.cpp LLM runs on CPU/GPU, not NPU — stated honestly.
- **VERIFIED today:** identical ONNX models run CPU-only on the dev machine (baseline numbers in
  `docs/benchmarks.md`).

### Offline advantage
Troubleshooting often happens *because* connectivity is broken — a cloud assistant is least
available exactly when needed. Local inference keeps camera/mic data on-device (privacy) and the
demo works with internet switched off (competition centerpiece).

### Innovation
**Closed-loop visual verification**: explicit diagnostic state machine + before/after physical
state comparison, not one-shot advice. Evidence: `diagnostics/state_machine/`.

### Demonstration (2–5 min)
Yes: show router → speak symptom → evidence (LED) → one safe action → re-observe →
verified state change → toggle internet OFF → same flow still works → show benchmark panel.

### Technical feasibility
Yes on the OMEN (CPU-only path). NPU numbers require one run on the (still unidentified)
Snapdragon laptop. MVP deliberately scoped to 3 device types + LED/indicator evidence class.

**GATE RESULT: PROCEED** with scope: router / printer / monitor, camera+mic closed loop,
offline-first, CPU-verified now, NPU-ready architecture.


---

## Part B — Architecture Decision Records

### ADR-001 — Python + FastAPI + browser UI (no Electron, no cloud)
- **Decision:** Backend = Python 3.14 + FastAPI/uvicorn (already installed); UI = static
  HTML/JS served by the backend; camera/mic captured in the browser via getUserMedia and POSTed
  as JPEG/WAV to local endpoints.
- **Alternatives:** Electron (heavy, duplicative), Qt/native (slow to polish), Streamlit (weak
  control over technician workflow).
- **Reason:** Maximizes time for AI/diagnostics; browser guarantees identical UI on OMEN and
  future Snapdragon device; zero network hops (localhost only).
- **Evidence:** FastAPI 0.141.1 + uvicorn 0.52.4 already in environment (VERIFIED).
- **Consequences:** Single-process app; must handle model load failures gracefully.

### ADR-002 — ONNX Runtime as the single inference substrate
- **Decision:** Neural models (vision, embeddings) run through `onnxruntime` with a provider
  strategy: `QNNExecutionProvider` (Snapdragon NPU, when available) → `CPUExecutionProvider` fallback.
- **Alternatives:** torch (large, no NPU path on Windows), DirectML (GPU-focused), per-model runtimes.
- **Reason:** QNN EP is Qualcomm's documented NPU path for ONNX; one substrate simplifies the
  workload-placement table and benchmarks (same model, different EP = CPU vs NPU comparison).
- **Evidence:** Qualcomm 80-62010-1 (RESEARCHED); ORT 1.29 CPU EP VERIFIED locally.
- **Consequences:** Models must be ONNX; llama.cpp kept as separate (CPU) component for the LLM.

### ADR-003 — Local LLM via llama.cpp prebuilt binary (no cmake/native build)
- **Decision:** Reasoning uses a small quantized instruct model served by the official
  prebuilt `llama-server` Windows binary, called over localhost HTTP; graceful template-based
  fallback if the binary/model is missing.
- **Alternatives:** llama-cpp-python (needs cmake/MSVC — absent), llama.cpp build from source
  (no toolchain), cloud LLM (violates offline-first).
- **Evidence:** cmake not installed (VERIFIED); llama-cpp-python has no cp314 wheels (RESEARCHED).
- **Consequences:** Extra process to manage; version-pinned download in `scripts/setup_models.ps1`.

### ADR-004 — Speech: faster-whisper (CTranslate2), isolated venv if Python 3.14 wheels missing
- **Decision:** Offline ASR = `faster-whisper` tiny/base int8 on CPU. If wheels are unavailable
  for Python 3.14, ASR runs in a uv-managed side venv (Python 3.13) as a small local service.
- **Alternatives:** Windows SAPI (worse quality), Vosk (older models), cloud ASR (offline violation).
- **Reason:** Best offline accuracy/latency ratio on CPU; int8 quantization; model ~75 MB.
- **Consequences:** ASR module degrades gracefully (transcription unavailable → typed input).

### ADR-005 — Vision MVP = indicator/LED color analytics + ONNX image classifier (no giant VLM yet)
- **Decision:** MVP evidence extraction uses classical CV (LED/indicator color detection,
  display-text crop) + a small ONNX classifier for device-class confirmation. A VLM (e.g.
  Qwen2.5-VL on AI Hub) is **deferred** until after the closed loop works.
- **Alternatives:** full VLM first (slow, fragile on 16 GB, hides the state machine).
- **Reason:** §23 optimization order = correctness first; LED state detection is deterministic,
  testable, and perfectly matches the router demo's verification step.
- **Consequences:** evidence types limited in MVP (documented in README limitations).

### ADR-006 — Knowledge: curated YAML device files + BM25 retrieval, not a vector DB
- **Decision:** `knowledge/devices/*.yaml` structured files (identity, indicators, symptoms,
  actions, expected visual changes, resolution criteria, escalation). Retrieval = in-process
  BM25 ranking; embedding rerank optional when an embedding model is present.
- **Alternatives:** Chroma/LanceDB (dependency + indirection for ~20 docs).
- **Evidence:** corpus size < 50 docs — vector DB unjustified (§11 of challenge).
- **Consequences:** adding devices = adding YAML + tests; no DB migrations.

### ADR-007 — Diagnostic state machine is explicit, deterministic, LLM-assisted only
- **Decision:** `diagnostics/state_machine/` owns transitions; rules engine proposes hypotheses;
  LLM only explains/ranks **provided** candidates — it cannot invent transitions or bypass safety.
- **Reason:** §7 requirement; determinism enables unit tests and judge-facing explainability.
- **Consequences:** bounded, testable behavior; some conversational flexibility traded away.

### ADR-008 — Repository: fresh `git init` in `repairlens-snapdragon` → empty GitHub repo
- **Decision:** local folder is untracked inside an unrelated parent repo; create an independent
  repo at `c:\Documents\Projects\repairlens-snapdragon` with remote
  `https://github.com/harinish45/repairlens-snapdragon.git` (exists, empty; gh authenticated).
- **Evidence:** VERIFIED via `git rev-parse` + GitHub fetch.

### ADR-009 — Pin PyAV `av<19` so faster-whisper audio decoding keeps working
- **Decision:** `requirements.txt` pins `av==18.1.0` (cp311-abi3 wheel — installs on
  Python 3.12 through 3.14+).
- **Problem found (live):** faster-whisper 1.2.1 (latest on PyPI, 2025-10-31) decodes audio with
  `av.open(path, mode="r", metadata_errors="ignore")`. PyAV 19.0.0 removed that (undocumented)
  keyword argument, so every `/api/transcribe` call failed with
  `TypeError: open() got an unexpected keyword argument 'metadata_errors'` → HTTP 503
  `asr_unavailable`. All voices were silenced by one dependency bump.
- **Alternatives:**
  (a) patch faster-whisper's `audio.py` locally — fragile; breaks silently on updates;
  (b) replace upstream decoding with our own PyAV→ndarray pipeline — ~40 lines to maintain and
  bypasses future upstream fixes;
  (c) wait for an upstream release — none scheduled as of the latest PyPI release.
- **Evidence:** reproduced on Python 3.14/Windows; after `pip install av==18.1.0`, the ASR smoke
  (real Windows TTS speech → `/api/transcribe`) returns the correct transcript in ~1.5 s for
  6.8 s of audio.
- **Consequences:** the pin is load-bearing for HEAR and is documented in `requirements.txt`.
  Revisit when faster-whisper stops passing `metadata_errors` (check upstream release notes).

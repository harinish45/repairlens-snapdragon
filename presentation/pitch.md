# RepairLens — Pitch

## One line
**A local multimodal repair assistant that sees the device, hears the complaint, and guides one
safe step at a time — then looks again to prove the fix worked.**

## The problem
When something breaks, people get search results and forum threads, not a technician. General
chatbots can guess ("try resetting it"), but they cannot *look* at the device, they cannot *hear*
the context, they hallucinate steps for hardware they have never seen, and they rarely ask
"did that actually fix it?". Worse, the risky advice is indistinguishable from the safe advice.

## What RepairLens does (the loop)
```
SEE (camera → indicator state)   HEAR (microphone → symptom text)
UNDERSTAND (structured symptom)  DIAGNOSE (ranked hypotheses from curated knowledge)
GUIDE (exactly one safe action)  VERIFY (re-observe: did the indicator change?)
```
Nothing is hidden inside a prompt. A **deterministic state machine** owns every transition, a
**safety gate** refuses out-of-scope work (mains voltage, opening sealed enclosures) and escalates,
and an **evidence vocabulary** (OBSERVED / LIKELY / UNCERTAIN) keeps claims matched to evidence.
The language model may explain and structure — it can never invent a transition or a fix.

## Why this wins
1. **The loop closes.** Most assistants stop at advice. RepairLens verifies with the camera:
   *"Verified: indicator changed amber_solid → green_solid."* That is the demo moment.
2. **Trustworthy by construction.** Deterministic transitions, unit-tested; the LLM explains
   candidates it is given, and cannot skip safety.
3. **Multimodal where it matters.** Vision (LED/indicator state) and speech (symptom intake) are
   not gimmicks — they are the evidence channels of the troubleshooting loop.
4. **Offline-first.** Camera frames and audio never leave `localhost`; the whole loop, models
   included, runs with the network cable pulled.
5. **Honest under measurement.** Every number the UI shows is measured on the machine it claims,
   and NPU cells say `NOT EXECUTED` instead of borrowed marketing numbers. Judges can run the
   benchmark script themselves.

## Measured proof (dev machine — Windows 11, low-power Intel CPU, Python 3.14)
| Capability | Result |
|---|---|
| Closed loop (SEE→…→VERIFY) | passes end-to-end incl. live vision (`scripts\e2e_smoke.py`) |
| LED/indicator vision | **p50 27.6 ms**, p95 31.8 ms, 30/30 correct classifications |
| Speech → text (tiny.en, int8) | **p50 0.90 s** for 6.8 s of audio, correct transcript |
| Unit + integration tests | 59 passing |
| Snapdragon / NPU / QNN | **not present on this machine — NOT EXECUTED** (see honesty section) |

## The Snapdragon story (Snapdragon-first design, honestly labeled)
- The app detects CPU/NPU/EPs at startup (`ai/runtime/profile.py`) and displays them honestly:
  `EP: CPU`, `Snapdragon: no (dev machine)`, `QNN EP: NOT EXECUTED (no NPU)`.
- Workload placement is planned per component (see `docs/architecture.md` §3): ASR and image
  classification are ONNX/QNN-shaped work targeted at the **Hexagon NPU via QNN EP** (EXPECTED),
  while llama.cpp LLM inference is honestly marked **not NPU-targetable** today.
- The benchmark harness is Snapdragon-ready: on the audited device it measures NPU/QNN numbers;
  until then it *refuses* to print a number, by design (`docs/benchmarks.md`).
- Component-level energy/latency work (resolution caps, single-frame vision, int8 ASR) keeps the
  device loop light: the whole SEE step is tens of milliseconds even on this throttled CPU.

## Live demo (90 seconds, fully local)
1. Click *Home Wi-Fi Router* → device identified.
2. Speak the symptom (*"the status light is orange and the wifi keeps dropping"*) — local
   transcription fills the box and submits itself.
3. Point the camera at the router indicator → *"amber · amber_solid · conf=99%"* → ranked
   hypotheses → **one** safe action with its expected visual change.
4. Perform it, click *I performed the action*; the LED turns green; *Re-observe indicator* →
   **RESOLVED — verified amber → green**.
5. Open the Benchmarks panel: measured numbers, and `npu.qnn_inference: NOT EXECUTED`.
   "This is what we measured — and this is what we refuse to claim."

## Honest limitations (stated up front)
- Vision MVP = single-frame LED/indicator analytics; blinking detection and VLM scene
  understanding are out of scope (ADR-005).
- ASR is English `tiny.en`; typed input is always available as fallback.
- NPU speedups are EXPECTED, not measured, until run on the Snapdragon target.

## Repo
`README.md` (quickstart, verification, layout) · `docs/` (architecture, ADRs, models, benchmarks,
safety, hardware audit) · `scripts/run_benchmarks.ps1` (reproduce every number) ·
`presentation/demo-script.md` (run-of-show).

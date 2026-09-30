# RepairLens — Hardware & Feasibility Audit (Phase 0)

**Date:** 2026-09-30
**Auditor:** Engineering agent (automated, on-machine inspection)
**Method:** PowerShell CIM/PnP queries executed on the development machine; no assumptions.

## 1. Development machine (VERIFIED — measured on this machine)

| Item | Value |
|---|---|
| Manufacturer / Model | HP — **OMEN by HP Gaming Laptop 16-wd0xxx** |
| CPU | **13th Gen Intel® Core™ i7-13620H**, 10 cores / 16 threads (x64) |
| NPU | **NONE PRESENT** — no Hexagon, no Intel NPU device node (verified via `Get-PnpDevice`) |
| GPU | Intel® UHD Graphics + **NVIDIA GeForce RTX 4060 Laptop GPU** |
| RAM | 16 GB (15.7 GB usable) |
| OS | Windows 11 Home Insider Preview, version 10.0.26220, build 26220, 64-bit |
| Camera | **HP True Vision FHD Camera** (present) |
| Microphone | Microphone Array (Intel® Smart Sound Technology for Digital Microphones) + AirPods Max (BT) |
| Python | 3.14.2 (`C:\Python314`); uv-managed CPython 3.13.12 and 3.11.15 also available |
| ONNX Runtime | 1.29.0 installed; available EPs = `AzureExecutionProvider`, `CPUExecutionProvider` only |
| Qualcomm SDKs | **None installed** (no QNN / QAIRT / AI Hub tooling detected) |
| cmake | not installed (native compilation of runtimes not possible without extra setup) |
| Tooling | uv 0.11.23, gh 0.96.0 → gh 2.96.0 (authenticated as `harinish45`), network access to GitHub/HuggingFace OK |

**Conclusion (VERIFIED):** This machine **cannot produce NPU measurements**. Any NPU number shown
in this project must come from a real Snapdragon device or be marked `NOT EXECUTED`.

## 2. Target competition hardware (Snapdragon HP laptop)

**STATUS: NOT YET IDENTIFIED — REQUIRED INPUT.**

Per the challenge rules, Snapdragon model, TOPS, RAM and NPU capabilities must never be assumed.
The user has confirmed the product is *"built for Snapdragon, developed on the OMEN i7"*.
Therefore:

- Development, tests, and **CPU baselines** run on the OMEN (this machine).
- The codebase contains a **runtime hardware-abstraction layer** (`ai/runtime/`) that detects
  Snapdragon + NPU/QNN at startup and selects execution providers accordingly.
- NPU claims remain classified **EXPECTED / NOT EXECUTED** until the benchmark suite is executed
  on the actual Snapdragon device (one command: `scripts/run_benchmarks.ps1`).

**Action required:** before final submission, run the audit script on the competition laptop:

```powershell
scripts/audit-hardware.ps1   # writes hardware facts for the Snapdragon device
scripts/run_benchmarks.ps1   # writes measured numbers into docs/benchmarks.md
```

### Known Snapdragon HP product lines (RESEARCHED, not confirmed as the target device)

HP ships Windows-on-Snapdragon devices in the OmniBook / EliteBook families (e.g. OmniBook X,
EliteBook Ultra). Exact SKU, SoC (X Elite / X Plus / X2 generation), RAM and NPU TOPS are
**unverified** until the physical device is audited.

## 3. Runtime paths for Windows-on-Snapdragon (RESEARCHED)

| Path | Source | What it gives |
|---|---|---|
| ONNX Runtime **QNN Execution Provider** (Qualcomm AI Engine Direct) | Qualcomm doc bundle 80-62010-1 "Windows on Snapdragon"; requires Qualcomm QNN/QAIRT SDK installed | Runs ONNX models on the **Hexagon NPU** (also GPU/DSP backends) |
| Qualcomm **AI Hub Models (Compute)** | aihub.qualcomm.com — 300+ model variants validated for Snapdragon X Elite / X Plus / X2 Elite | Pre-optimized ONNX/QNN artifacts for NPU; runtimes: ONNX Runtime, Qualcomm AI Runtime, llama.cpp |
| **CPU fallback** | stock `onnxruntime` wheel (CPUExecutionProvider) | Always available; this is what runs on the OMEN today |
| llama.cpp (CPU/Vulkan) | official prebuilt Windows binaries | Local LLM; on Snapdragon it targets CPU/GPU — **not the NPU** (be honest about this) |

## 4. Feasibility summary

| Question | Answer | Status |
|---|---|---|
| Can the full app be built and tested now? | Yes — camera, mic, speech, vision, reasoning, retrieval, diagnostics, UI all run CPU-only on the OMEN | VERIFIED (as items are completed) |
| Can NPU benchmarks run now? | **No** — no NPU on this machine | VERIFIED |
| Offline feasibility | Yes — all selected models are downloadable once, then run fully locally | EXPECTED → VERIFIED per model at integration |
| Snapdragon NPU feasibility | Architecture supports QNN EP; requires QNN SDK + model availability on target device | RESEARCHED / EXPECTED |

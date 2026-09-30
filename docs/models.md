# RepairLens — Model Registry

Rules: no silent model swaps (§30). Changing any row requires updating this file,
`requirements*.txt`, `docs/benchmarks.md`, README, and presentation claims.

| ID | Model / version | Task | Input → Output | Size | Precision | Runtime / EP | Device target | License | Offline | Verification status |
|---|---|---|---|---|---|---|---|---|---|---|
| `asr-whisper` | `faster-whisper` `Systran/faster-whisper-tiny.en` pinned by commit in setup script | Speech recognition (EN) | audio 16 kHz → text | ~75 MB | int8 (CTranslate2) | faster-whisper on CPU | CPU (OMEN); NPU: EXPECTED via AI Hub whisper + QNN EP | MIT | yes (after download) | EXPECTED → VERIFIED when ASR integration test passes |
| `vision-led` | classical HSV/blob analyzer (no model) | LED/indicator state | RGB frame → {color, state, confidence} | 0 | n/a | in-process numpy/OpenCV-free | CPU only | n/a (own code) | yes | VERIFIED via unit tests |
| `vision-device` | ONNX image classifier (see setup script pin) | device-class confirmation | 224×224 RGB → class probs | ≤ 30 MB | int8 | onnxruntime QNN→CPU | CPU now; NPU EXPECTED | Apache-2.0 (chosen model) | yes | EXPECTED |
| `llm-reason` | Qwen2.5-1.5B-Instruct Q4_K_M GGUF (pinned URL) | explanation + symptom structuring | prompt → text/JSON | ~1 GB | Q4_K_M | llama-server (localhost) | CPU (llama.cpp); GPU optional; **NPU: not supported by llama.cpp** | Apache-2.0 | yes | EXPECTED → VERIFIED when llama-server integration passes |
| `embed-opt` | (optional) ONNX MiniLM-L6 quantized | retrieval rerank | text → vector | ~23 MB | int8 | onnxruntime QNN→CPU | CPU now; NPU EXPECTED | Apache-2.0 | yes | OPTIONAL — BM25 (non-neural) is default |

## Fallbacks
- `asr-whisper` unavailable → typed symptom input (UI), status shows `ASR: UNAVAILABLE`.
- `llm-reason` unavailable → template-based explanation generator from retrieved knowledge; status shows `LLM: FALLBACK`.
- `vision-device` unavailable → LED analytics still work; device class comes from user selection (labeled UNCERTAIN).
- No model may be replaced without updating this registry (§18/§30).

## Runtime provider strategy
`QNNExecutionProvider` (only if Qualcomm QNN SDK + Snapdragon NPU present) → `CPUExecutionProvider`.
Observed provider list is reported at `/api/status` and in benchmark JSON.

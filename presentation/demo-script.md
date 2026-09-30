# RepairLens — Live Demo Script (run-of-show)

Target: **5 minutes** (90-second core loop + system/benchmarks honesty + Q&A).
Everything is local — the demo works with networking disabled.

## Pre-flight (5 minutes before presenting)

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000     # from repo root
powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1
```

- [ ] Open `http://127.0.0.1:8000` in the browser; badges visible at top.
- [ ] Click **New session** → status must read `IDLE`.
- [ ] Camera permission granted; router (or phone showing a bright **amber** LED image) framed
      so the LED occupies a small part of the frame (dark background around it).
- [ ] Microphone permission granted (test: *Start microphone* → "Microphone ready").
- [ ] Optional: pull the network cable/Wi-Fi ~1 minute before start → badge reads
      `OFFLINE MODE — local models and knowledge` (probe caches 30 s).
- [ ] Backup if hardware misbehaves: `python scripts\asr_smoke.py <file.wav>` (audio path) and
      `python scripts\e2e_smoke.py` (full loop incl. vision) both print `PASS`.

## Run of show

**0:00 — Frame it (15 s).**
> "A broken thing, a phone call to a friend who fixes things — that's today's support stack.
> RepairLens is a local AI technician that sees the device, hears the problem, and *stays honest*:
> it measures what's there, refuses what's unsafe, and checks whether the fix worked.
> Nothing leaves this laptop."

**0:15 — HEAR (25 s).** Click *Home Wi-Fi Router* → `DEVICE_DETECTED`.
Say: "Speaking is realistic — the user describes the problem from across the room."
- Click *Record symptom*, speak: **"The status light is orange and the wifi keeps dropping."**
- Click *Record symptom* again to stop → "Transcribing locally…" → transcript appears in the box
  and submits itself → `SYMPTOM_IDENTIFIED (no_network)`.
> "That was whisper tiny running here, not in a data center."

**0:40 — SEE (25 s).** Click *Start camera*, hold the device to the camera, click *Capture evidence*.
- Vision chip: `LED: amber · state=amber_solid · conf=99%` → `EVIDENCE_COLLECTED`.
> "It doesn't just see 'an LED' — it extracts the indicator state as *evidence*."

**1:05 — UNDERSTAND + DIAGNOSE + GUIDE (30 s).**
- `HYPOTHESIS_GENERATED` (3 candidates, 62%) → action panel: *"Reseat the WAN/Internet cable at
  both the router and the modem until it clicks"* + expected visual change.
> "One step, not a checklist. The ranked explanation says orange usually means WAN link down;
> a restart is the *less* likely fix. And note what's on screen: every arrow came from a state
> machine we unit-test — the model only explains what the rules already found."

**1:35 — VERIFY (30 s).** Perform the step (or pretend), click *I performed the action*.
- Swap the phone image to a **green** LED (or the real LED turns green).
- Click *Re-observe indicator* → `RESULT_OBSERVED` → **RESOLVED —
  Verified: indicator changed amber_solid → green_solid.**
> "This is the moment generic chatbots can't reach: it *verified the repair with its own eyes*."

**2:05 — Safety + honesty beats (45 s).**
- Type *"it smells burnt"* and send → **⚠ SAFETY STOP** — refused with escalation guidance.
  (Reset with *New session* afterwards.)
> "The gate is code, not vibes: burning smells, liquid ingress, exposed mains — refused and
> escalated, no matter what the model might suggest."
- Scroll right panel: `EP: CPU` · `Snapdragon: no (dev machine)` ·
  `QNN EP: NOT EXECUTED (no NPU)`; Benchmarks panel shows measured p50 numbers, then
  `npu.qnn_inference: NOT EXECUTED`.
> "This is the part I'm proudest of: measured vision p50 of 27.6 ms, whisper p50 of 0.9 seconds —
> and NPU rows that say NOT EXECUTED, because this machine has no NPU. The benchmark script
> refuses to print unmeasured numbers. On the audited Snapdragon device, same script, real QNN
> numbers. See docs/benchmarks.md."

**2:50 — Close (30 s).**
> "RepairLens is a complete local loop — see, hear, diagnose, guide, verify — with a safety gate,
> a deterministic core you can audit, and benchmarks you can rerun in one command.
> Snapdragon-first by design, honest by discipline."

**3:20–5:00 — Q&A.** See ammunition below.

## Q&A ammunition

| Question | Answer |
|---|---|
| Why not a cloud LLM? | Privacy + offline + latency. The loop must work in a basement; frames/audio never leave the device. |
| Why classical CV for the LED? | Deterministic, testable, 27 ms, zero model downloads (ADR-005). A mistaken fast classifier is worse than an honest blob analysis. |
| Where would the NPU help? | ASR (whisper via AI Hub/QNN) and the ONNX device classifier — both marked EXPECTED in the model registry. |
| What's the role of the LLM? | Explains and structures the candidates it is *given*; cannot invent transitions or bypass the safety gate (ADR-007). |
| How do you know the fix worked? | Same camera path re-observes the indicator; the state machine only reaches RESOLVED on a verified change (`amber_solid → green_solid`). |
| What about wrong guesses? | Hypotheses carry confidence and expected observations; if the indicator doesn't change, the loop returns to `NEXT_HYPOTHESIS`. |
| Safety for real users? | Explicit allow/deny scope, STOP → WARN → RECOMMEND QUALIFIED SERVICE, all in `docs/safety.md` and enforced in `diagnostics/safety/`. |
| What's not claimed? | NPU numbers (none on this machine), blinking detection, non-English ASR, VLM scene understanding — all listed as limitations. |

## Failure fallbacks (if the demo gods object)

1. **Mic blocked** → type the symptom text; point at the `Microphone unavailable: …` line and
   note the graceful degradation contract (typed input always works).
2. **Camera blocked/bad light** → run `python scripts\e2e_smoke.py` (feeds synthetic amber/green
   frames through the real API) and narrate the same states from the UI after each call.
3. **Server crashed** → restart uvicorn; sessions are in-memory, so click *New session* and go.
4. **No router on stage** → a phone photo of an amber LED, then a green one, works identically —
   the analyzer only needs a small bright saturated blob on a dark field.
5. **Timing pressure** → the core beats are HEAR → SEE → ONE ACTION → VERIFY; everything else is
   optional color.


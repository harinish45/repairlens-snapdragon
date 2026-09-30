# RepairLens — Safety Architecture

Safety is part of the architecture (§12), not an afterthought.

## 1. Evidence vocabulary (enforced in code and UI)
- **OBSERVED** — derived directly from camera/mic sensors (e.g. "LED detected: amber").
- **LIKELY** — diagnostic engine inference above confidence threshold (e.g. "LIKELY: modem offline").
- **UNCERTAIN** — below threshold or contradictory evidence; must be shown as uncertain.
UI never renders an inference as fact; confidence percentage always displayed.

## 2. Safety scope (MVP allowed / blocked)

**Allowed (low-voltage, user-serviceable):**
router/monitor/printer power cycle, cable re-seating (network/USB/HDMI), button-based resets
(pinhole reset), settings changes described to the user, vent/cleaning advice, peripheral
reconnection, checking indicator lights.

**Blocked — triggers `STOPPED_UNSAFE` (STOP → WARN → RECOMMEND QUALIFIED SERVICE):**
- mains electricity work, opening power supplies, any internal rewiring
- dangerous voltages / exposed conductors
- physically damaged batteries, swollen batteries, hot batteries
- discharging capacitors or opening CRT/PSU-class equipment
- unsafe disassembly, mechanical procedures with injury risk
- anything the system cannot verify visually with ≥ configured confidence

Blocked actions are declared in `diagnostics/safety/` as patterns over action text AND as
per-device `blocked_actions` in knowledge YAML — both are checked before any recommendation
reaches the UI (defense in depth). Unit tests must cover every blocked pattern.

## 3. Confidence handling
- Default thresholds (env-overridable): device-class accept ≥ 0.55; LED color accept ≥ 0.60;
  below → UNCERTAIN → system asks for a better view instead of acting.
- Verification requires before/after evidence from the same indicator family; otherwise the
  result is `INCONCLUSIVE`, never `RESOLVED`.

## 4. Escalation conditions (per device, in knowledge YAML)
e.g. burning smell, visible sparks, smoke, liquid damage, physical deformation → immediate
`ESCALATE_SERVICE`, no further guidance.

## 5. Failure-mode user messages (exact copy, §24)
- Vision unavailable: "I can't reliably see the device. Please adjust the camera."
- Low confidence: "I am not confident enough to identify this indicator."
- Unknown device: "I don't have enough verified information for this device."
- Unsafe: "Stop. I can't safely guide this procedure."
- Offline: "Offline mode active. Using local models and knowledge."

## 6. Privacy (§32)
No camera frames, audio, documents, or diagnostics leave the machine. No external services in
core loop. No secrets in repo; configuration via `.env` (see `.env.example`).

/* RepairLens UI — localhost only. Talks to /api/*. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { session: null, status: null, stream: null, mediaRecorder: null,
                 chunks: [], recording: false };

// ---------- helpers -------------------------------------------------------
async function api(path, opts = {}) {
  // FormData bodies must keep the browser-generated multipart Content-Type.
  const headers = opts.body instanceof FormData
    ? { ...(opts.headers || {}) }
    : { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

function show(el, on) { el.classList.toggle("hidden", !on); }

// ---------- status --------------------------------------------------------
async function refreshStatus() {
  try {
    const st = await api("/api/status");
    state.status = st;
    const net = $("badge-net");
    net.textContent = st.offline ? "OFFLINE MODE" : "ONLINE — LOCAL";
    net.className = "badge badge-net " + (st.offline ? "off" : "ok");

    const hw = st.hardware;
    $("badge-ep").textContent = `EP: ${hw.active_provider.replace("ExecutionProvider", "")}` +
      (hw.npu_present ? " · NPU" : "");
    $("badge-ep").className = "badge badge-ep " + (hw.qnn_available ? "ok" : "");

    const llm = $("badge-llm");
    llm.textContent = `LLM: ${st.models.llm.mode}`;
    llm.className = "badge badge-llm " + (st.models.llm.available ? "ok" : "off");

    const asr = $("badge-asr");
    const asrReady = st.models.asr.ready || !st.models.asr.error;
    asr.textContent = `ASR: ${st.models.asr.name}` + (st.models.asr.ready ? " ✓" : "");
    asr.className = "badge badge-asr " + (st.models.asr.error ? "err" : "ok");

    // system table
    const rows = [
      ["CPU", hw.cpu],
      ["Architecture", hw.arch],
      ["OS", hw.os],
      ["Snapdragon", hw.is_snapdragon ? "YES" : "no (dev machine)"],
      ["NPU device", hw.npu_present ? "present" : "NOT PRESENT"],
      ["ONNX providers", hw.onnx_providers.join(", ") || "none"],
      ["Active provider", hw.active_provider],
      ["QNN EP", hw.qnn_available ? "available" : "NOT EXECUTED (no NPU)"],
      ["Knowledge", st.knowledge_devices.length + " devices"],
      ["Mode", st.mode],
    ];
    document.querySelector("#sys-table tbody").innerHTML =
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");

    // hardware notes
    if (hw.notes && hw.notes.length) {
      document.querySelector("#sys-table tbody").innerHTML +=
        hw.notes.map((n) => `<tr><td>note</td><td>${n}</td></tr>`).join("");
    }
  } catch (e) {
    $("badge-net").textContent = "SERVER DOWN";
    $("badge-net").className = "badge err";
  }
}

async function refreshBench() {
  try {
    const b = await api("/api/benchmarks");
    if (!b.available) { $("bench-box").textContent = b.note; return; }
    const d = b.data;
    const lines = [`hw: ${d.hardware || "?"}`, `runs: ${d.runs ?? "?"}`];
    for (const r of (d.results || [])) {
      lines.push(`${r.name}: p50=${r.p50_ms}ms p95=${r.p95_ms}ms ep=${r.ep}`);
    }
    $("bench-box").textContent = lines.join("\n");
  } catch (_) {
    $("bench-box").textContent = "NOT EXECUTED";
  }
}

// ---------- camera ---------------------------------------------------------
$("btn-cam").addEventListener("click", async () => {
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
    $("video").style.display = "none";
    $("video-placeholder").style.display = "flex";
    $("btn-cam").textContent = "Start camera";
    $("btn-shot").disabled = true;
    return;
  }
  try {
    state.stream = await navigator.mediaDevices.getUserMedia(
      { video: { width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
    $("video").srcObject = state.stream;
    $("video").style.display = "block";
    $("video-placeholder").style.display = "none";
    $("btn-cam").textContent = "Stop camera";
    $("btn-shot").disabled = false;
  } catch (e) {
    $("video-placeholder").textContent = "Camera unavailable: " + e.message;
  }
});

function captureFrame() {
  const video = $("video");
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  canvas.getContext("2d").drawImage(video, 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
}

async function observeOnce() {
  const blob = await captureFrame();
  if (!blob) return;
  const fd = new FormData();
  fd.append("file", blob, "frame.jpg");
  try {
    const out = await api("/api/observe", { method: "POST", body: fd });
    renderSession(out);
    if (out.vision) {
      const v = out.vision;
      $("vision-out").textContent =
        `LED: ${v.color} · state=${v.state} · conf=${Math.round(v.confidence * 100)}% · ${v.note}`;
      show($("vision-out"), true);
    }
  } catch (e) {
    $("status-msg").textContent = "I can't reliably see the device. Please adjust the camera. (" + e.message + ")";
  }
}

$("btn-shot").addEventListener("click", observeOnce);
$("btn-reobserve").addEventListener("click", observeOnce);


// ---------- microphone ------------------------------------------------------
async function toggleMic() {
  if (state.stream && state.stream.getAudioTracks().length) {
    stopMic();
    return;
  }
  try {
    const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (state.stream) {
      state.stream.addTrack(micStream.getAudioTracks()[0]);
    } else {
      state.stream = micStream;
    }
    $("mic-state").textContent = "Microphone ready";
    $("btn-mic").textContent = "Stop microphone";
    $("btn-record").disabled = false;
  } catch (e) {
    $("mic-state").textContent = "Microphone unavailable: " + e.message;
  }
}

function stopMic() {
  if (state.mediaRecorder && state.recording) state.mediaRecorder.stop();
  if (state.stream) {
    state.stream.getAudioTracks().forEach((t) => t.stop());
    if (!state.stream.getVideoTracks().length) {
      state.stream = null;
      $("video").style.display = "none";
      $("video-placeholder").style.display = "flex";
      $("btn-cam").textContent = "Start camera";
      $("btn-shot").disabled = true;
    }
  }
  $("mic-state").textContent = "Microphone idle";
  $("btn-mic").textContent = "Start microphone";
  $("btn-record").disabled = true;
}

$("btn-mic").addEventListener("click", toggleMic);

$("btn-record").addEventListener("click", () => {
  if (state.recording && state.mediaRecorder) {
    state.mediaRecorder.stop();
    return;
  }
  const audioOnly = new MediaStream(state.stream.getAudioTracks());
  const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
  state.mediaRecorder = new MediaRecorder(audioOnly, mime ? { mimeType: mime } : undefined);
  state.chunks = [];
  state.mediaRecorder.ondataavailable = (e) => { if (e.data.size) state.chunks.push(e.data); };
  state.mediaRecorder.onstop = async () => {
    state.recording = false;
    $("btn-record").textContent = "Record symptom";
    $("mic-state").textContent = "Transcribing locally…";
    const blob = new Blob(state.chunks, { type: "audio/webm" });
    const fd = new FormData();
    fd.append("file", blob, "symptom.webm");
    try {
      const out = await fetch("/api/transcribe", { method: "POST", body: fd }).then(async (r) => {
        if (!r.ok) {
          const j = await r.json();
          throw new Error(j.user_message || j.detail || "transcription failed");
        }
        return r.json();
      });
      $("symptom-text").value = out.text;
      $("mic-state").textContent =
        `Transcribed in ${out.latency_ms} ms (local ${out.model})`;
      await submitSymptom(out.text);
    } catch (e) {
      $("mic-state").textContent = e.message;
    }
  };
  state.mediaRecorder.start();
  state.recording = true;
  $("btn-record").textContent = "Stop recording";
  $("mic-state").textContent = "Recording… speak the problem";
});

// ---------- session actions --------------------------------------------------
async function submitSymptom(text) {
  const t = (text ?? $("symptom-text").value).trim();
  if (!t) { $("status-msg").textContent = "Please describe the problem you are seeing."; return; }
  try {
    renderSession(await api("/api/session/symptom", {
      method: "POST", body: JSON.stringify({ text: t }),
    }));
  } catch (e) {
    $("status-msg").textContent = e.message;
  }
}
$("btn-send-symptom").addEventListener("click", () => submitSymptom());

$("btn-done").addEventListener("click", async () => {
  try {
    renderSession(await api("/api/session/action_done", { method: "POST", body: "{}" }));
  } catch (e) { $("status-msg").textContent = e.message; }
});

$("btn-reset").addEventListener("click", async () => {
  try {
    renderSession(await api("/api/session/reset", { method: "POST", body: "{}" }));
    show($("vision-out"), false);
  } catch (e) { $("status-msg").textContent = e.message; }
});

// ---------- devices -----------------------------------------------------------
async function loadDevices() {
  const d = await api("/api/devices");
  $("device-buttons").innerHTML = d.devices.map((dev) =>
    `<button class="btn" data-id="${dev.id}">${dev.name}</button>`).join("");
  $("device-buttons").querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", async () => {
      try {
        renderSession(await api("/api/session/device", {
          method: "POST", body: JSON.stringify({ device_id: b.dataset.id }),
        }));
      } catch (e) { $("status-msg").textContent = e.message; }
    });
  });
}

// ---------- init ---------------------------------------------------------------
(async function init() {
  try { renderSession(await api("/api/session")); } catch (_) { /* server down */ }
  await loadDevices();
  await refreshStatus();
  await refreshBench();
  setInterval(refreshStatus, 30000);
})();



const TERMINAL = new Set(["RESOLVED", "STOPPED_UNSAFE", "ESCALATE_SERVICE"]);

function renderSession(s) {
  state.session = s;
  // state pill
  const pill = $("state-pill");
  pill.textContent = s.state;
  pill.className = "state-pill" +
    (s.state === "STOPPED_UNSAFE" || s.state === "ESCALATE_SERVICE" ? " danger" :
     s.state === "RESOLVED" ? " ok" : "");
  // progress
  $("progress-fill").style.width =
    `${Math.round(100 * s.progress.step / Math.max(1, s.progress.total))}%`;
  // pipeline stages
  const stageIdx = Math.min(5, Math.floor(6 * s.progress.step / Math.max(1, s.progress.total)));
  document.querySelectorAll(".stage").forEach((el) => {
    const i = Number(el.dataset.stage);
    el.classList.toggle("active", i === stageIdx && !TERMINAL.has(s.state));
    el.classList.toggle("done", i < stageIdx || TERMINAL.has(s.state));
  });
  // status message
  $("status-msg").textContent = s.status_message;

  // evidence
  const hasEv = s.observations.length > 0;
  show($("evidence-block"), hasEv);
  if (hasEv) {
    $("evidence-list").innerHTML = s.observations.map((o) =>
      `<li>[${o.phase}] ${o.indicator} = <b>${o.value}</b> ` +
      `(${Math.round(o.confidence * 100)}%) — OBSERVED</li>`).join("");
  }

  // diagnosis
  const hasDiag = s.hypotheses.length > 0 && s.explanation;
  show($("diagnosis-block"), hasDiag);
  if (hasDiag) {
    $("explanation").textContent = s.explanation +
      (s.explanation_source === "llm" ? "  [local LLM]" : "  [template]");
    $("hyp-list").innerHTML = s.hypotheses.map((h) =>
      `<li>${h.title} — ${Math.round(h.confidence * 100)}%</li>`).join("");
    $("conf-fill").style.width = `${Math.round(s.confidence * 100)}%`;
    $("conf-val").textContent = `${Math.round(s.confidence * 100)}%`;
  }

  // action
  const hasAction = !!s.current_action && s.state === "ACTION_RECOMMENDED";
  show($("action-block"), hasAction);
  if (s.current_action) {
    $("action-text").textContent = s.current_action.text;
    $("action-verify").textContent = s.current_action.verification_note
      ? `Verify: ${s.current_action.verification_note}` : "";
  }
  // verification prompt
  show($("verify-block"), s.state === "ACTION_PERFORMED");
  if (s.state === "ACTION_PERFORMED") {
    $("verify-msg").textContent = s.status_message;
  }

  // safety
  const unsafe = s.state === "STOPPED_UNSAFE" || s.state === "ESCALATE_SERVICE";
  show($("safety-block"), unsafe);
  if (unsafe) {
    $("safety-list").innerHTML =
      (s.safety_block_reasons.length ? s.safety_block_reasons : [s.status_message])
        .map((r) => `<li>${r}</li>`).join("");
  }

  // events
  $("event-log").innerHTML = [...s.events].reverse().slice(0, 14).map((e) =>
    `<li>${e.at} — ${e.event} → ${e.state}${e.detail ? " (" + e.detail + ")" : ""}</li>`
  ).join("");

  $("btn-done").disabled = !(s.state === "ACTION_RECOMMENDED");
}

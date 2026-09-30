"""RepairLens FastAPI application (localhost only — ADR-001).

Serves the technician UI and the local API. No cloud calls in the core loop.
"""
from __future__ import annotations

import logging
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ai.runtime.profile import get_profile
from ai.speech.transcriber import ASRError, Transcriber
from ai.vision.led import FrameError, analyze_indicator, load_frame, observations_to_evidence_value
from app.orchestration.session import SessionManager
from knowledge.loader import KnowledgeBase

logging.basicConfig(
    level=os.environ.get("RL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("repairlens")

UI_DIR = Path(__file__).resolve().parent / "ui"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB hard cap

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    kb = KnowledgeBase()
    _state["kb"] = kb
    _state["mgr"] = SessionManager(kb=kb)
    _state["asr"] = Transcriber()
    _state["profile"] = get_profile()
    _state["reasoner"] = None
    try:
        from ai.reasoning.llm import Reasoner

        _state["reasoner"] = Reasoner()
    except Exception as exc:  # noqa: BLE001
        log.warning("reasoner unavailable: %s", exc)
    _state["started"] = time.time()
    log.info("RepairLens started — knowledge devices: %s", sorted(kb.devices))
    if kb.load_errors:
        log.error("knowledge load errors: %s", kb.load_errors)
    yield
    _state.clear()


app = FastAPI(title="RepairLens", version="0.1.0", lifespan=lifespan)


def _offline() -> bool:
    """Cached connectivity probe (never in the core loop's critical path)."""
    cached = _state.get("offline_cache")
    now = time.time()
    if cached and now - cached[1] < 30:
        return cached[0]
    offline = True
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=1.2):
                offline = False
                break
        except OSError:
            continue
    _state["offline_cache"] = (offline, now)
    return offline


# ---- endpoints -----------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    profile = _state["profile"]
    reasoner = _state.get("reasoner")
    asr: Transcriber = _state["asr"]
    return {
        "offline": _offline(),
        "mode": ("OFFLINE MODE — local models and knowledge" if _offline()
                 else "LOCAL (network available)"),
        "hardware": profile.to_dict(),
        "models": {
            "asr": {"name": asr.model_name, "ready": asr._model is not None,
                    "error": asr.load_error},
            "llm": {"enabled": bool(reasoner and reasoner.enabled),
                    "available": bool(reasoner and reasoner.available),
                    "mode": "llama-server" if (reasoner and reasoner.available)
                            else "template fallback"},
            "vision": {"name": "led-classical-cv", "ready": True},
            "retrieval": {"name": "bm25-local", "ready": True},
        },
        "knowledge_devices": sorted(_state["kb"].devices),
        "knowledge_errors": _state["kb"].load_errors,
        "uptime_s": round(time.time() - _state["started"], 1),
    }


@app.get("/api/devices")
def devices() -> dict:
    return {
        "devices": [
            {"id": d.device_id, "name": d.name, "category": d.category,
             "summary": d.summary}
            for d in _state["kb"].all_devices()
        ]
    }


@app.get("/api/session")
def get_session() -> dict:
    return _state["mgr"].session.to_dict()


@app.post("/api/session/reset")
def reset_session() -> dict:
    _state["mgr"].reset()
    return _state["mgr"].session.to_dict()


@app.post("/api/session/device")
def select_device(payload: dict) -> dict:
    device_id = str(payload.get("device_id", "")).strip()
    if not device_id:
        raise HTTPException(400, "device_id required")
    return _state["mgr"].select_device(device_id).to_dict()


@app.post("/api/session/symptom")
def submit_symptom(payload: dict) -> dict:
    text = str(payload.get("text", ""))
    return _state["mgr"].submit_symptom(text, reasoner=_state.get("reasoner")).to_dict()


@app.post("/api/session/action_done")
def action_done() -> dict:
    return _state["mgr"].mark_action_done().to_dict()


@app.post("/api/observe")
async def observe(file: UploadFile = File(...)) -> dict:
    """Camera frame in -> LED evidence -> state machine."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "frame too large")
    try:
        frame = load_frame(data)
        obs = analyze_indicator(frame)
    except FrameError as exc:
        raise HTTPException(400, f"unreadable frame: {exc}") from exc
    value = observations_to_evidence_value(obs)
    session = _state["mgr"].observe(value=value, confidence=obs.confidence,
                                    indicator="status_led",
                                    reasoner=_state.get("reasoner"))
    out = session.to_dict()
    out["vision"] = obs.to_dict()
    return out


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio too large")
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    asr: Transcriber = _state["asr"]
    try:
        t = asr.transcribe_bytes(data, suffix=suffix)
    except ASRError as exc:
        return JSONResponse(status_code=503, content={
            "error": "asr_unavailable",
            "message": str(exc),
            "user_message": ("Speech recognition is unavailable. "
                             "Please type the problem instead."),
        })
    return {"text": t.text, "language": t.language, "latency_ms": t.latency_ms,
            "model": t.model, "duration_s": t.duration_s}


@app.get("/api/benchmarks")
def benchmarks() -> dict:
    path = Path(__file__).resolve().parent.parent / "benchmarks" / "results" / "latest.json"
    if not path.is_file():
        return {"available": False, "note": "NOT EXECUTED — run scripts/run_benchmarks.ps1"}
    import json

    return {"available": True, "data": json.loads(path.read_text(encoding="utf-8"))}


# ---- UI ------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")



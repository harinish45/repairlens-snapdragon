"""Indicator/LED state extraction from camera frames (classical CV — ADR-005).

No neural model, no OpenCV dependency: numpy + Pillow only.
Detects bright saturated blobs and classifies their color into the canonical
indicator vocabulary used by the knowledge base:

    red | amber | green | blue | white | off | unknown

Confidence combines: blob brightness, saturation, size sanity and color purity.
Single-frame analysis cannot prove blinking; temporal blinking detection is
explicitly out of MVP scope (documented limitation).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, asdict

import numpy as np
from PIL import Image, UnidentifiedImageError

MAX_SIDE = 640           # analysis resolution (perf, §23)
MIN_AREA_PX = 4          # minimum blob size at analysis resolution
MAX_AREA_RATIO = 0.25    # blobs bigger than 25% of frame are not LEDs
BRIGHT_THRESHOLD = 110   # V channel
SAT_THRESHOLD = 60       # S channel (0-255)


@dataclass(frozen=True)
class LEDObservation:
    color: str            # red|amber|green|blue|white|off
    confidence: float      # 0..1
    state: str             # e.g. amber_solid / off / unknown
    blob_px: int
    x: int                 # blob center (analysis coords)
    y: int
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class FrameError(Exception):
    """Malformed / unreadable image input."""


def load_frame(data: bytes, max_side: int = MAX_SIDE) -> Image.Image:
    if not data:
        raise FrameError("empty frame payload")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise FrameError(f"unreadable image: {exc}") from exc
    img = img.convert("RGB")
    scale = max_side / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
    return img


def _rgb_to_hsv_arr(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized H(0-360)/S(0-255)/V(0-255) from uint8 RGB array (HxWx3)."""
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0.0) * 255.0

    z = np.zeros_like(maxc)
    rc = (maxc - r) / np.maximum(delta, 1e-6)
    gc = (maxc - g) / np.maximum(delta, 1e-6)
    bc = (maxc - b) / np.maximum(delta, 1e-6)
    h = np.where(maxc == r, bc - gc, np.where(maxc == g, 2.0 + rc - bc, 4.0 + gc - rc))
    h = (h / 6.0) % 1.0 * 360.0
    h = np.where(delta < 1e-6, z, h)
    return h, s, v * 255.0


def _classify_hue(h: float, s: float) -> str:
    if s < SAT_THRESHOLD:
        return "white"
    if h < 15 or h >= 345:
        return "red"
    if h < 70:
        return "amber"      # red-orange through orange-yellow band
    if h < 170:
        return "green"
    if h < 260:
        return "blue"
    return "red"            # magenta/purple -> closest safe reading: red-ish



def analyze_indicator(frame: Image.Image) -> LEDObservation:
    """Find the most LED-like bright blob and classify its color."""
    rgb = np.asarray(frame)
    h, s, v = _rgb_to_hsv_arr(rgb)

    bright = v >= BRIGHT_THRESHOLD
    if not np.any(bright):
        return LEDObservation("off", 0.75, "off", 0, 0, 0, "no bright pixels found")

    cand = bright & ((s >= SAT_THRESHOLD) | (v >= 220))
    ys, xs = np.nonzero(cand)
    if len(xs) == 0:
        return LEDObservation("off", 0.6, "off", 0, 0, 0, "no saturated pixels")

    bx, by, bmask = _largest_blob(cand, xs, ys)
    area = int(bmask.sum())
    total = cand.shape[0] * cand.shape[1]
    if area < MIN_AREA_PX:
        return LEDObservation("unknown", 0.3, "unknown", area, bx, by, "blob too small")
    if area > MAX_AREA_RATIO * total:
        # A huge bright region is a scene (window/screen), not an indicator.
        return LEDObservation("unknown", 0.35, "unknown", area, bx, by,
                              "bright region too large for an indicator")

    bh, bs, bv = h[bmask], s[bmask], v[bmask]
    mean_h = float(np.median(bh))
    mean_s = float(np.median(bs))
    mean_v = float(np.median(bv))

    color = _classify_hue(mean_h, mean_s)
    sat_score = min(mean_s / 180.0, 1.0)
    bright_score = min(mean_v / 230.0, 1.0)
    if color != "white":
        ang = np.deg2rad(bh)
        purity = float(np.hypot(np.cos(ang).mean(), np.sin(ang).mean()))
    else:
        purity = 0.9 if mean_s < SAT_THRESHOLD else 0.5
    conf = float(np.clip(0.45 * bright_score + 0.3 * sat_score + 0.25 * purity, 0.0, 0.99))
    state = "unknown"
    if conf >= 0.5:
        state = f"{color}_solid"
    else:
        color = "unknown"
    note = f"median_h={mean_h:.0f} sat={mean_s:.0f} area={area}"
    return LEDObservation(color, round(conf, 2), state, area, int(bx), int(by), note)


def _largest_blob(mask: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> tuple[int, int, np.ndarray]:
    """Return (cx, cy, blob_mask) for the densest bright cluster.

    Coarse-grid density search + rectangular neighborhood — deterministic,
    dependency-free (no scipy).
    """
    gh, gw = mask.shape
    cell = max(8, min(gh, gw) // 24)
    gy = ys // cell
    gx = xs // cell
    combined = gy.astype(np.int64) * 10_000 + gx
    vals, counts = np.unique(combined, return_counts=True)
    best = int(vals[np.argmax(counts)])
    by_i, bx_i = divmod(best, 10_000)
    y0, y1 = by_i * cell, min((by_i + 2) * cell, gh)
    x0, x1 = bx_i * cell, min((bx_i + 2) * cell, gw)
    blob = np.zeros_like(mask)
    blob[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    if not blob.any():
        return int(xs.mean()), int(ys.mean()), mask
    yy, xx = np.nonzero(blob)
    return int(xx.mean()), int(yy.mean()), blob


def observations_to_evidence_value(obs: LEDObservation) -> str:
    """Map an observation to the knowledge-base observed_values vocabulary."""
    if obs.state == "unknown" or obs.confidence < 0.5:
        return "unknown"
    return obs.state

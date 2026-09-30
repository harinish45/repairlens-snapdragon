"""Unit tests: LED/indicator analyzer on synthetic frames (no camera needed)."""
import io

import pytest
from PIL import Image, ImageDraw

from ai.vision.led import (
    FrameError,
    analyze_indicator,
    load_frame,
    observations_to_evidence_value,
)


def make_frame(color: tuple[int, int, int], bg=(18, 18, 20), led_r=8, size=(320, 240)) -> bytes:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    cx, cy = size[0] // 2, size[1] // 2
    d.ellipse((cx - led_r, cy - led_r, cx + led_r, cy + led_r), fill=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_green_led_detected():
    frame = load_frame(make_frame((20, 230, 40)))
    obs = analyze_indicator(frame)
    assert obs.color == "green"
    assert obs.confidence >= 0.5
    assert obs.state == "green_solid"


def test_red_led_detected():
    obs = analyze_indicator(load_frame(make_frame((240, 25, 25))))
    assert obs.color == "red"
    assert obs.state == "red_solid"


def test_amber_led_detected():
    obs = analyze_indicator(load_frame(make_frame((255, 160, 10))))
    assert obs.color == "amber"
    assert obs.state == "amber_solid"


def test_dark_frame_reads_off():
    obs = analyze_indicator(load_frame(make_frame((2, 2, 2), bg=(5, 5, 6))))
    assert obs.color == "off"
    assert obs.state == "off"


def test_empty_payload_raises():
    with pytest.raises(FrameError):
        load_frame(b"")


def test_garbage_payload_raises():
    with pytest.raises(FrameError):
        load_frame(b"not an image at all")


def test_huge_bright_region_is_rejected_as_unknown():
    # Whole-frame white -> not an LED
    img = Image.new("RGB", (320, 240), (250, 250, 250))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    obs = analyze_indicator(load_frame(buf.getvalue()))
    assert obs.state == "unknown" or obs.color == "white"  # either way: not a colored LED fact
    if obs.state == "unknown":
        assert obs.confidence < 0.5


def test_evidence_value_mapping():
    obs = analyze_indicator(load_frame(make_frame((20, 230, 40))))
    assert observations_to_evidence_value(obs) == "green_solid"


def test_downscale_applies():
    frame = load_frame(make_frame((20, 230, 40), size=(1920, 1080)))
    assert max(frame.size) <= 640

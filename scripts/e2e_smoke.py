"""Manual E2E smoke of the closed loop against a running server (dev tool)."""
import io
import json
import sys
import urllib.request

from PIL import Image, ImageDraw

# Console-safe output: status messages contain arrows/em-dashes; cp1252 consoles
# would otherwise crash the script mid-report.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"


def frame(color, size=(320, 240)):
    img = Image.new("RGB", size, (18, 18, 20))
    d = ImageDraw.Draw(img)
    cx, cy = size[0] // 2, size[1] // 2
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def post_file(url, data, name="f.jpg"):
    boundary = "----rlboundary"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=head + data + tail,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def post_json(url, obj):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def main() -> int:
    s = post_json(f"{BASE}/api/session/reset", {})
    print("reset:", s["state"])
    s = post_json(f"{BASE}/api/session/device", {"device_id": "router_home"})
    print("device:", s["state"])
    s = post_json(f"{BASE}/api/session/symptom",
                  {"text": "wifi is not connecting to the internet"})
    print("symptom:", s["state"], "| id:", s["symptom_id"])
    s = post_file(f"{BASE}/api/observe", frame((255, 160, 10)))
    print("observe:", s["state"], "| vision:", s["vision"]["state"],
          s["vision"]["confidence"])
    print("action:", (s.get("current_action") or {}).get("text", "")[:90])
    print("explanation:", s["explanation"][:140])
    s = post_json(f"{BASE}/api/session/action_done", {})
    print("action_done:", s["state"])
    s = post_file(f"{BASE}/api/observe", frame((20, 230, 40)))
    print("verify:", s["state"])
    print("message:", s["status_message"][:200])
    expected = ["DEVICE_DETECTED", "SYMPTOM_IDENTIFIED", "ACTION_RECOMMENDED",
                "ACTION_PERFORMED", "RESOLVED"]
    got = [e["state"] for e in s["events"]]
    ok = all(st in got for st in expected) and s["state"] == "RESOLVED"
    print("E2E RESULT:", "PASS" if ok else "FAIL")
    print("states:", " -> ".join(got))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

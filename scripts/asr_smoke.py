"""ASR smoke: POST a wav file to /api/transcribe (dev tool).

Usage: python scripts/asr_smoke.py [path-to-wav]
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def post_file(url, data, name):
    boundary = "----rlasrboundary"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=head + data + tail,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        return True, json.loads(urllib.request.urlopen(req, timeout=600).read())
    except urllib.error.HTTPError as exc:
        return False, json.loads(exc.read())


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp_symptom.wav")
    if not path.is_file():
        print(f"missing audio file: {path}")
        return 2
    ok, out = post_file(f"{BASE}/api/transcribe", path.read_bytes(), path.name)
    if not ok:
        print("TRANSCRIBE FAILED:", json.dumps(out, indent=2))
        return 1
    print(f"text       : {out['text']!r}")
    print(f"language   : {out['language']} | model: {out['model']}")
    print(f"duration_s : {out['duration_s']} | latency_ms: {out['latency_ms']}")
    return 0 if out.get("text") else 1


if __name__ == "__main__":
    sys.exit(main())

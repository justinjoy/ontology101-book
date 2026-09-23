#!/usr/bin/env python3
# image_to_sosa_ttl.py — CCTV 스냅샷 → 비전 모델 → JSON → SOSA TTL (단일 단계)
#
# Usage:
#   python3 image_to_sosa_ttl.py shot_01.jpg shot_02.jpg shot_03.jpg shot_04.jpg shot_05.jpg \
#       --sensor "http://k.fc/onto/cctv#L010009" \
#       --time "2025-10-17T14:30:00Z" \
#       --out result.ttl

import argparse, base64, json, re, sys, requests
from pathlib import Path

from text_to_sosa_ttl import to_ttl  # TTL 직렬화 재사용 (단일 출처 유지)

HOST = "http://localhost:11434"
MODEL = "qwen3.8:27b-mlx"

PROMPT = """You are an expert traffic and pedestrian analyst.
Given the following sequential CCTV snapshots, extract exactly three fields as compact JSON.
Allowed values:
- weather: one of [Clear, Cloudy, Rain, Snow, Fog, Unknown]
- pedestrian_congestion: one of [VeryCrowded, Crowded, Normal, Sparse, Unknown]
- traffic_volume: one of [Heavy, Moderate, Light, Unknown]

Rules:
1) Decide only from what is visible in the images. Do not invent facts.
2) Return JSON only, no prose.
Example:
{"weather":"Clear","pedestrian_congestion":"VeryCrowded","traffic_volume":"Heavy"}"""

UNKNOWN = {"weather": "Unknown", "pedestrian_congestion": "Unknown", "traffic_volume": "Unknown"}


def to_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def parse_json(msg: str) -> dict:
    # qwen3 계열은 <think>…</think> 를 앞에 붙일 수 있음
    msg = re.sub(r"<think>.*?</think>", "", msg, flags=re.S).strip()
    try:
        return json.loads(msg)
    except json.JSONDecodeError:
        m = re.search(r"\{.*?\}", msg, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return dict(UNKNOWN)


def call_vlm(image_paths, host: str = HOST, model: str = MODEL) -> dict:
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [to_b64(Path(p)) for p in image_paths],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return parse_json(r.json().get("response", "").strip())


def main():
    ap = argparse.ArgumentParser(description="CCTV images -> vision model -> SOSA TTL")
    ap.add_argument("images", nargs="+", help="CCTV snapshot image paths")
    ap.add_argument("--sensor", required=True, help="Sensor IRI (e.g., http://k.fc/onto/cctv#CCTV_1234)")
    ap.add_argument("--time", required=True, help="Observation time ISO8601 (e.g., 2025-10-17T14:30:00Z)")
    ap.add_argument("--out", default="result.ttl", help="Output TTL path")
    ap.add_argument("--host", default=HOST, help="Ollama host")
    ap.add_argument("--model", default=MODEL, help="Vision model name")
    args = ap.parse_args()

    for p in args.images:
        if not Path(p).exists():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(2)

    data = call_vlm(args.images, host=args.host, model=args.model)
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
    ttl = to_ttl(data, args.sensor, args.time)
    Path(args.out).write_text(ttl, encoding="utf-8")
    print(ttl)


if __name__ == "__main__":
    main()

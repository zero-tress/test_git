#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术探针：验证 8032 上的 qwen3.8-27b 是否支持 mp4 base64 视频输入。

用法：
    /home/wj/miniconda3/envs/study/bin/python tools/probe_vlm.py data/搬物体.mp4
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8032"
MODEL = "qwen3.8-27b"


def main() -> int:
    video_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/搬物体.mp4")
    raw = video_path.read_bytes()
    b64 = base64.b64encode(raw).decode()
    print(f"video={video_path} bytes={len(raw)} base64_len={len(b64)}")

    # 先降采样一份小视频，检查体积控制
    small = Path("/tmp/probe_small.mp4")
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", "scale=640:-2", "-r", "8",
         "-c:v", "libx264", "-crf", "28", "-an", str(small)],
        capture_output=True, check=True,
    )
    small_b64 = base64.b64encode(small.read_bytes()).decode()
    print(f"small bytes={small.stat().st_size} base64_len={len(small_b64)}")

    system = "你是视频理解助手，只输出 JSON，不要任何解释。"
    user = [
        {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{small_b64}"}},
        {"type": "text", "text": (
            "看这段视频，用 JSON 回答：\n"
            '{"scene":"一句话描述","viewpoint":"第一人称|第三人称|其他","subject":"谁在操作",'
            '"body_parts":["观察到的活动身体部位"],"action_segments":[{"t_start":0.0,"t_end":1.0,'
            '"actor_part":"手臂","what":"正在做什么"}]}\n'
            "时间用秒。"
        )},
    ]
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": 2048,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=900)
    dt = time.time() - t0
    print(f"HTTP {r.status_code} in {dt:.1f}s")
    if r.status_code != 200:
        print(r.text[:2000])
        return 1
    data = r.json()
    msg = data["choices"][0]["message"]
    print("=== content ===")
    print(msg.get("content", "")[:3000])
    rc = msg.get("reasoning_content")
    if rc:
        print("=== reasoning (first 800) ===")
        print(rc[:800])
    print("=== usage ===")
    print(json.dumps(data.get("usage", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

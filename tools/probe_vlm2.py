#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针 2：验证模型能否输出"执行器级原子动作 + 时序"。

对比两种输入：
  A. 整段视频（全时长）
  B. 短窗口（0-8s）
看细分程度、时间戳精度、并行关系识别。
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8032"
MODEL = "qwen3.8-27b"

SYSTEM = """你是人体操作视频的分析专家。你的输出必须是严格 JSON，不能有任何解释文字。
分析纪律：
1. 只描述画面中真实可见的身体动作，不脑补。
2. 描述是定性的：只说"哪个部位在做什么"，绝不给角度、幅度、速度、力的数值。
3. 身体部位只用这些词：躯干、腰、头、颈、左臂、右臂、左手、右手、左腿、右腿、左脚、右脚、口。
4. 每个动作必须标注它在视频里的起止秒数。"""

USER_TMPL = """分析这段视频（时长 {dur:.1f} 秒），输出操作者每个身体部位的动作。

要求每个动作包含：
- executor: 身体部位
- action: 动作（用"部位+做什么"的短句，如"右臂向前伸出""左手收拢抓紧""双腿交替迈步"）
- start / end: 起止秒数（保留 1 位小数）
- mode: transition(建立/解除一个状态，瞬时) | motion(持续位移/姿态变化) | maintain(区间内保持某状态)
- exerts_force: true/false —— 该区间内该部位是否持续给力（持续施加作用）
- object: 作用对象（没有则 null）
- until: 若是 maintain，写"保持到什么时候结束"——用事件描述，如"直到右手完成抓握"，不要写秒数

另外单独给出 temporal_relations 数组，描述动作之间的关系：
- relation: sequence(先后) | parallel(并行) | alternation(交替) | maintain_until(前者维持直到后者完成)
- from / to: 动作序号（从 1 开始）

输出 JSON：
{{"atomic_actions":[{{"id":1,"executor":"","action":"","start":0.0,"end":0.0,"mode":"","exerts_force":false,"object":null,"until":null}}],
 "temporal_relations":[{{"relation":"","from":1,"to":2,"note":""}}]}}
"""


def encode(path: Path, dur: float | None = None, start: float = 0.0, width: int = 640, fps: int = 8) -> str:
    out = Path(f"/tmp/probe2_{path.stem}_{start}_{dur}.mp4")
    cmd = ["ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-vf", f"scale={width}:-2", "-r", str(fps), "-c:v", "libx264", "-crf", "28", "-an", str(out)]
    subprocess.run(cmd, capture_output=True, check=True)
    return base64.b64encode(out.read_bytes()).decode()


def ask(label: str, b64: str, dur: float) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}},
                {"type": "text", "text": USER_TMPL.format(dur=dur)},
            ]},
        ],
        "temperature": 0.1,
        "max_tokens": 16384,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=1200)
    dt = time.time() - t0
    print(f"\n########## {label}  HTTP {r.status_code}  {dt:.1f}s ##########")
    if r.status_code != 200:
        print(r.text[:1500])
        return {}
    content = r.json()["choices"][0]["message"].get("content", "")
    out_dir = Path("/data/wj_data/deepseek_videostudy/output/_probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label.replace(' ', '_')}.txt").write_text(content, encoding="utf-8")
    print(content[:6000])
    print("--- usage:", json.dumps(r.json().get("usage", {}), ensure_ascii=False))
    return {"content": content, "latency": dt}


def main() -> int:
    vp = Path(sys.argv[1] if len(sys.argv) > 1 else "data/搬物体.mp4")
    total = 15.07
    if len(sys.argv) > 2:
        total = float(sys.argv[2])
    mode = sys.argv[3] if len(sys.argv) > 3 else "both"

    if mode in ("both", "full"):
        b64 = encode(vp, dur=None)
        ask("A 整段视频", b64, total)
    if mode in ("both", "window"):
        b64 = encode(vp, dur=8.0, start=0.0)
        ask("B 窗口 0-8s", b64, 8.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

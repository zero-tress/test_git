#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""媒体处理：视频探测、切片、运动分析（客观证据）。

运动分析给出的是**数值证据**（运动能量曲线、变化点），
不参与语义判断，只用于：
  1. 给 VLM 提供时间锚点（"画面在 2.1s / 3.4s 有显著变化"）；
  2. 校验 VLM 给出的动作时间段是否落在真实的运动区间上。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from . import config


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: Path) -> dict:
    """ffprobe：时长 / 帧率 / 分辨率 / 总帧数。"""
    out = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_frames,codec_name",
        "-show_entries", "format=duration,size",
        "-of", "json", str(path),
    ])
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe 失败：{out.stderr[:500]}")
    data = json.loads(out.stdout)
    st = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    num, _, den = (st.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    return {
        "path": str(path),
        "name": path.stem,
        "duration": round(float(fmt.get("duration") or 0.0), 3),
        "size_bytes": int(fmt.get("size") or 0),
        "width": int(st.get("width") or 0),
        "height": int(st.get("height") or 0),
        "fps": round(fps, 3),
        "nb_frames": int(st.get("nb_frames") or 0),
        "codec": st.get("codec_name"),
    }


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_clip(src: Path, start: float, dur: float, tag: str = "", *, fps: float | None = None) -> Path:
    """切一段送模型的低码率小视频，磁盘缓存。"""
    fps = config.CLIP_FPS if fps is None else fps
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(
        f"{src.resolve()}|{file_sha1(src)}|{start:.3f}|{dur:.3f}|{config.CLIP_WIDTH}|{fps}|{config.CLIP_CRF}|{tag}"
        .encode()).hexdigest()[:12]
    dst = config.WORK_DIR / f"{src.stem}_{start:.1f}_{dur:.1f}_{key}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src), "-t", f"{dur:.3f}",
            "-vf", f"scale={config.CLIP_WIDTH}:-2", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(config.CLIP_CRF),
            "-an", str(dst)]
    out = _run(cmd)
    if out.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg 切片失败：{out.stderr[:500]}")
    return dst


def window_plan(duration: float) -> list[tuple[float, float]]:
    """把视频切成 (start, dur) 窗口列表。短视频整段一次。"""
    if duration <= config.SINGLE_SHOT_MAX_SECONDS:
        return [(0.0, duration)]
    win = config.WINDOW_SECONDS
    step = max(1.0, win - config.WINDOW_OVERLAP_SECONDS)
    plan: list[tuple[float, float]] = []
    t = 0.0
    while t < duration - 0.2:
        d = min(win, duration - t)
        plan.append((round(t, 3), round(d, 3)))
        if t + d >= duration - 0.05:
            break
        t = round(t + step, 3)
    return plan


def motion_profile(path: Path) -> dict:
    """帧差法运动能量曲线 + 变化点（客观证据，非语义判断）。"""
    import cv2  # 延迟导入：非视频分析场景不必装 opencv
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    stride = config.MOTION_SAMPLE_STRIDE
    times: list[float] = []
    energies: list[float] = []
    prev = None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            if prev is not None:
                diff = cv2.absdiff(gray, prev)
                _, binimg = cv2.threshold(diff, config.MOTION_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
                ratio = float(np.count_nonzero(binimg)) / float(binimg.size)
                times.append(round(idx / fps, 3))
                energies.append(round(ratio, 5))
            prev = gray
        idx += 1
    cap.release()

    # 平滑
    win = config.MOTION_SMOOTH_WIN
    smooth: list[float] = []
    for i in range(len(energies)):
        lo = max(0, i - win // 2)
        hi = min(len(energies), i + win // 2 + 1)
        smooth.append(round(sum(energies[lo:hi]) / (hi - lo), 5))

    # 变化点：能量相对相邻窗口显著上升或下降
    changes: list[dict] = []
    for i in range(1, len(smooth)):
        prev_avg = sum(smooth[max(0, i - 4):i]) / max(1, len(smooth[max(0, i - 4):i]))
        cur_avg = sum(smooth[i:i + 4]) / max(1, len(smooth[i:i + 4]))
        delta = cur_avg - prev_avg
        if abs(delta) < 0.012:
            continue
        t = times[i] if i < len(times) else times[-1]
        if changes and t - changes[-1]["t"] < config.MOTION_CHANGE_MIN_GAP:
            if abs(delta) > abs(changes[-1]["delta"]):
                changes[-1] = {"t": t, "delta": round(delta, 5),
                               "kind": "运动增强" if delta > 0 else "运动减弱"}
            continue
        changes.append({"t": t, "delta": round(delta, 5),
                        "kind": "运动增强" if delta > 0 else "运动减弱"})

    # 高活动段
    mean_e = sum(smooth) / len(smooth) if smooth else 0.0
    hot: list[dict] = []
    start_i = None
    for i, e in enumerate(smooth):
        if e > mean_e * 1.35 and start_i is None:
            start_i = i
        elif (e <= mean_e * 1.35 or i == len(smooth) - 1) and start_i is not None:
            end_i = i
            if end_i - start_i >= 2:
                hot.append({"start": times[start_i], "end": times[min(end_i, len(times) - 1)],
                            "peak": round(max(smooth[start_i:end_i + 1]), 5)})
            start_i = None

    return {
        "fps": round(fps, 3),
        "samples": len(smooth),
        "curve": [[times[i], smooth[i]] for i in range(len(smooth))],
        "change_points": changes,
        "hot_segments": hot,
        "mean_energy": round(mean_e, 5),
    }


def motion_hint_text(profile: dict, start: float, dur: float) -> str:
    """把窗口内的客观运动证据翻译成给 VLM 的时间锚点提示。"""
    lo, hi = start, start + dur
    lines = []
    for cp in profile.get("change_points", []):
        if lo - 0.3 <= cp["t"] <= hi + 0.3:
            rel = cp["t"] - start
            lines.append(f"- 第 {rel:.1f} 秒附近画面运动量明显{cp['kind']}（可能会有动作起始或结束）")
    for seg in profile.get("hot_segments", []):
        if seg["end"] >= lo and seg["start"] <= hi:
            lines.append(f"- 第 {max(0, seg['start'] - start):.1f}~{min(dur, seg['end'] - start):.1f} 秒是画面动得最厉害的区间")
    if not lines:
        lines.append("- 该段画面运动量平稳，没有特别剧烈的变化点")
    return "\n".join(lines)

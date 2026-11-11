"""Video overview + state frames + bounded local review, with evidence provenance."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from . import config, media
from .frame_sampling.motion_sampling import MotionAdaptiveWindowSampler


def settings() -> dict:
    return {"candidate_fps": config.KEYFRAME_CANDIDATE_FPS,
            "minimum_frames": 6, "maximum_frames": config.KEYFRAME_MAX_PER_WINDOW,
            "event_settings": {
                "analysis_width": 320, "start_threshold": 0.30, "stop_threshold": 0.23,
                "pre_context_seconds": 0.5, "post_context_seconds": 0.5,
                "coverage_guarantee_enabled": True, "reserved_coverage_frames": 2,
                "rapid_change_max_gap_seconds": 0.5,
                "refinement": {"enabled": True, "long_event_seconds": 4.0,
                               "max_core_seconds": 3.0, "min_core_seconds": 1.0,
                               "short_event_seconds": 0.75, "pre_context_seconds": 0.5,
                               "post_context_seconds": 0.5, "max_additional_windows": 8}}}


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_frames(video: Path, start: float, end: float, out: Path,
                  *, fps: float, maximum: int) -> list[dict]:
    """Decode dense candidates and retain temporal coverage at real source indices."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError("不能打开待复查视频")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if source_fps <= 0 or count <= 0:
        cap.release()
        raise RuntimeError("缺少有效源帧率或帧数")
    first = max(0, round(start * source_fps))
    last = min(count - 1, round(end * source_fps))
    step = max(1, round(source_fps / fps))
    indices = sorted(set([*range(first, last + 1, step), last]))
    if len(indices) > maximum:
        indices = [indices[round(i * (len(indices) - 1) / (maximum - 1))]
                   for i in range(maximum)]
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    try:
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, bgr = cap.read()
            if not ok:
                continue
            actual = round(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            stamp = actual / source_fps
            if not start - 1 / source_fps <= stamp <= end + 1 / source_fps:
                continue
            fid = f"source_f{actual:09d}"
            path = out / (fid + ".jpg")
            if cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 90]):
                frames.append({"frame_id": fid, "path": str(path), "timestamp": round(stamp, 6),
                               "source_frame_index": actual, "selection_roles": ["coverage"],
                               "selection_reasons": ["local_review_temporal_coverage"]})
    finally:
        cap.release()
    return frames


def prepare(ctx: dict) -> dict:
    if not config.KEYFRAMES_ENABLED:
        return {"status": "disabled", "windows": []}
    video = Path(ctx["video"])
    options = settings()
    key = hashlib.sha256((media.file_sha1(video) + json.dumps(options, sort_keys=True)
                          + "|state-frames-v1").encode()).hexdigest()[:16]
    out = Path(ctx["out_dir"]) / "sampling" / key
    out.mkdir(parents=True, exist_ok=True)
    try:
        sampler = MotionAdaptiveWindowSampler(**options)
        _, report = sampler.sample(video, out / "frames", window_seconds=config.WINDOW_SECONDS,
                                   overlap_seconds=config.WINDOW_OVERLAP_SECONDS)
        report["status"] = "ok"
    except Exception as exc:
        # Failure remains visible; original whole-video understanding still runs.
        try:
            frames = export_frames(video, 0, ctx["meta"]["duration"], out / "fallback",
                                   fps=config.KEYFRAME_CANDIDATE_FPS,
                                   maximum=config.KEYFRAME_MAX_PER_WINDOW)
        except Exception as fallback_error:
            frames = []
            failure = f"; fallback: {type(fallback_error).__name__}: {fallback_error}"
        else:
            failure = ""
        report = {"status": "uniform_fallback" if frames else "failed",
                  "reason": f"{type(exc).__name__}: {exc}" + failure,
                  "windows": [{"window_id": "fallback", "start_time": 0,
                               "end_time": ctx["meta"]["duration"], "selected_frames": frames}],
                  "refinement": {"proposals": []}}
    report["source_video_sha1"] = media.file_sha1(video)
    report["version"] = "state-frames-v1"
    report["directory"] = str(out)
    report["policy"] = "运动事件和选帧角色只指导取证，不证明接触、抓握、释放或前后状态"
    _save(out / "sampling_report.json", report)
    render_gallery(report, out)
    return report


def frames_for_window(report: dict, start: float, duration: float, maximum=None) -> list[dict]:
    maximum = maximum or config.KEYFRAME_MAX_PER_WINDOW
    unique = {}
    for window in report.get("windows") or []:
        for frame in window.get("selected_frames") or []:
            if start <= frame["timestamp"] <= start + duration and Path(frame["path"]).is_file():
                unique.setdefault(frame["frame_id"], frame)
    ordered = sorted(unique.values(), key=lambda f: f["timestamp"])
    if len(ordered) <= maximum:
        return ordered
    # Retain context endpoints and temporal coverage, rather than peaks alone.
    return [ordered[round(i * (len(ordered) - 1) / (maximum - 1))] for i in range(maximum)]


def render_gallery(report: dict, out: Path) -> None:
    cards, seen = [], set()
    for window in report.get("windows") or []:
        for frame in window.get("selected_frames") or []:
            if frame["frame_id"] in seen:
                continue
            seen.add(frame["frame_id"])
            src = Path(frame["path"]).relative_to(out).as_posix()
            caption = f'{frame["frame_id"]} · {frame["timestamp"]:.3f}s · ' + "/".join(frame["selection_roles"])
            cards.append(f'<figure><img loading="lazy" src="{html.escape(src, quote=True)}">'
                         f'<figcaption>{html.escape(caption)}</figcaption></figure>')
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>关键状态帧取证</title>'
            '<style>body{font:16px sans-serif;margin:24px;background:#f5f7fa}'
            'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}'
            'figure{margin:0;background:white;padding:12px}img{width:100%}figcaption{overflow-wrap:anywhere}</style>'
            '<h1>关键状态帧取证</h1><p>按源视频时间排列。pre/post 等为运动候选阶段，'
            '不代表已证实的手状态、接触或动作。视频缺失与遮挡仍需保留未知。</p>'
            f'<p>抽样状态：{html.escape(report["status"])}</p><main>' + "".join(cards) + '</main></html>')
    (out / "index.html").write_text(page, encoding="utf-8")

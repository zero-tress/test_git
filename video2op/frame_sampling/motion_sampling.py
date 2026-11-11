from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from video2op.frame_sampling.models import FrameReference, VideoWindow
from video2op.frame_sampling.sampling_refinement import (
    coverage_diagnostics,
    plan_refinement_windows,
    select_context_frames,
    split_motion_events,
)

ROLE_PRIORITY = {
    "onset": 6,
    "manipulate": 5,
    "post": 4,
    "pre": 3,
    "contact": 2,
    "coverage": 1,
}


class MotionAdaptiveWindowSampler:
    """Model-free event-aware sampling based on compensated image motion."""

    def __init__(
        self,
        *,
        candidate_fps: float = 8.0,
        minimum_frames: int = 6,
        maximum_frames: int = 10,
        jpeg_quality: int = 88,
        event_settings: dict[str, Any] | None = None,
        visualization_settings: dict[str, Any] | None = None,
    ) -> None:
        if candidate_fps <= 0:
            raise ValueError("candidate_fps 必须大于0")
        if minimum_frames < 2 or maximum_frames < minimum_frames:
            raise ValueError("关键帧数量范围无效")
        self.candidate_fps = candidate_fps
        self.minimum_frames = minimum_frames
        self.maximum_frames = maximum_frames
        self.jpeg_quality = jpeg_quality
        self.event_settings = dict(event_settings or {})
        self.visualization_settings = dict(visualization_settings or {})

    def sample(
        self,
        video_path: Path,
        output_dir: Path,
        *,
        window_seconds: float,
        overlap_seconds: float,
    ) -> tuple[list[VideoWindow], dict[str, Any]]:
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"无法打开视频：{video_path}")
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / source_fps if source_fps > 0 else 0.0
        if duration <= 0:
            capture.release()
            raise RuntimeError("无法获得视频时长或帧率。")

        candidates = self._scan_timeline(capture, duration, source_fps)
        capture.release()
        self._normalize_features(candidates)
        events = self._detect_events(candidates)
        refinement_settings = dict(self.event_settings.get("refinement", {}))
        sampling_events = split_motion_events(candidates, events, refinement_settings)
        refinement_plan, skipped_refinements = plan_refinement_windows(
            candidates, events, sampling_events, refinement_settings
        )
        bounds = _window_bounds(duration, window_seconds, overlap_seconds)

        selected_by_window: list[tuple[str, float, float, list[dict[str, Any]]]] = []
        window_context = {}
        context_complete_events = set()
        for index, (start, end) in enumerate(bounds):
            window_candidates = [
                item for item in candidates if start <= item["timestamp"] <= end
            ]
            window_events = [
                item
                for item in sampling_events
                if item["end_time"] >= start and item["start_time"] <= end
            ]
            selected = self._select_window_frames(window_candidates, window_events)
            selected_by_window.append((f"window_{index:04d}", start, end, selected))
            window_context[f"window_{index:04d}"] = coverage_diagnostics(selected, window_events)
            for event in window_events:
                if not coverage_diagnostics(selected, [event])["missing_event_context"]:
                    context_complete_events.add(event["event_id"])

        planned_events = {proposal["event"]["event_id"] for proposal in refinement_plan}
        deficits = [event for event in sampling_events
                    if event["event_id"] not in context_complete_events | planned_events]
        if refinement_settings.get("enabled", False) and deficits:
            extra_settings = {**refinement_settings, "include_all_events": True,
                "max_additional_windows": max(0, int(refinement_settings.get(
                    "max_additional_windows", 8)) - len(refinement_plan))}
            extra_plan, skipped_extra = plan_refinement_windows(
                candidates, events, deficits, extra_settings)
            refinement_plan.extend(extra_plan)
            # Existing long/short proposals omitted by the initial cap are
            # already counted there; report context deficits separately.
            unplanned_context_deficits = skipped_extra
        else:
            unplanned_context_deficits = 0
        for index, proposal in enumerate(refinement_plan):
            proposal["window_id"] = f"refine_{index:04d}"

        for proposal in refinement_plan:
            start, end = proposal["start_time"], proposal["end_time"]
            local = [item for item in candidates if start <= item["timestamp"] <= end]
            selected = select_context_frames(
                local, [proposal["event"]], self.minimum_frames,
                self.maximum_frames, self.event_settings,
            )
            window_id = proposal["window_id"]
            selected_by_window.append((window_id, start, end, selected))
            window_context[window_id] = coverage_diagnostics(selected, [proposal["event"]])
        selected_by_window.sort(key=lambda item: (item[1], item[2], item[0]))

        output_dir.mkdir(parents=True, exist_ok=True)
        exported = self._export_selected_frames(video_path, output_dir, selected_by_window)
        windows: list[VideoWindow] = []
        for window_id, start, end, selected in selected_by_window:
            exported_selected = [item for item in selected
                                 if round(float(item["timestamp"]), 3) in exported]
            failed_exports = len(selected) - len(exported_selected)
            if failed_exports:
                # Never report context protection for a frame that failed export.
                relevant = [event for event in sampling_events
                            if event["end_time"] >= start and event["start_time"] <= end]
                window_context[window_id] = coverage_diagnostics(exported_selected, relevant)
                window_context[window_id]["failed_frame_exports"] = failed_exports
            frames: list[FrameReference] = []
            for item in selected:
                timestamp = round(float(item["timestamp"]), 3)
                path = exported.get(timestamp)
                if path is None:
                    continue
                frames.append(
                    FrameReference(
                        frame_id=_frame_id(timestamp),
                        path=str(path.resolve()),
                        timestamp=timestamp,
                        selection_score=round(float(item["selection_score"]), 4),
                        selection_roles=sorted(item["selection_roles"]),
                        event_ids=sorted(item["event_ids"]),
                        selection_reasons=sorted(item["selection_reasons"]),
                    )
                )
            windows.append(
                VideoWindow(
                    window_id=window_id,
                    start_time=round(start, 3),
                    end_time=round(end, 3),
                    frames=frames,
                )
            )

        report = {
            "strategy": "motion_adaptive",
            "detector": "opencv_classical_motion",
            "uses_learned_detector": False,
            "uses_mediapipe": False,
            "source_duration_seconds": round(duration, 3),
            "window_seconds": window_seconds,
            "overlap_seconds": overlap_seconds,
            "step_seconds": window_seconds - overlap_seconds,
            "candidate_fps": self.candidate_fps,
            "candidate_frame_count": len(candidates),
            "minimum_frames_per_window": self.minimum_frames,
            "maximum_frames_per_window": self.maximum_frames,
            "interaction_mode": "camera_compensated_motion",
            "selection_policy": ("context_refinement_v3" if
                self.event_settings.get("coverage_guarantee_enabled", False)
                else "phase_preserving_v2"),
            "selection_policy_settings": {
                "pre_context_seconds": float(
                    self.event_settings.get("pre_context_seconds", 0.5)
                ),
                "post_context_seconds": float(
                    self.event_settings.get("post_context_seconds", 0.25)
                ),
                "rapid_change_max_gap_seconds": float(
                    self.event_settings.get("rapid_change_max_gap_seconds", 0.5)
                ),
            },
            "events": events,
            "sampling_events": sampling_events,
            "refinement": {
                "enabled": bool(refinement_settings.get("enabled", False)),
                "additional_window_count": len(refinement_plan),
                "skipped_due_to_cap": skipped_refinements,
                "context_deficit_count": len(deficits),
                "unplanned_context_deficits": unplanned_context_deficits,
                "settings": refinement_settings,
                "proposals": refinement_plan,
                "semantics": "Motion proposals only; VLM must verify actual actions and state changes.",
            },
            "candidate_timeline": [
                {
                    "timestamp": item["timestamp"],
                    "source_frame_index": item["source_frame_index"],
                    "residual_flow": round(item["residual_flow_norm"], 5),
                    "motion_area": round(item["motion_area_norm"], 5),
                    "local_change": round(item["local_change_norm"], 5),
                    "edge_change": round(item["edge_change_norm"], 5),
                    "global_motion": round(item["global_motion_norm"], 5),
                    "motion_bbox": item.get("motion_bbox"),
                    "activity_score": item["activity_score"],
                }
                for item in candidates
            ],
            "windows": [
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time,
                    "end_time": window.end_time,
                    "context_coverage": window_context.get(window.window_id, {}),
                    "selected_frames": [
                        frame.model_dump(mode="json") for frame in window.frames
                    ],
                }
                for window in windows
            ],
        }
        report["visualization"] = {"status": "handled_by_video2op"}
        return windows, report

    def _scan_timeline(
        self, capture: Any, duration: float, source_fps: float
    ) -> list[dict[str, Any]]:
        import cv2

        candidate_count = max(2, math.floor(duration * self.candidate_fps) + 1)
        previous_gray = None
        candidates: list[dict[str, Any]] = []
        analysis_width = max(96, int(self.event_settings.get("analysis_width", 320)))
        for index in range(candidate_count):
            timestamp = min(duration - 0.001, index / self.candidate_fps)
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            success, bgr = capture.read()
            if not success:
                continue
            source_index = round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            timestamp = source_index / source_fps
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            height = max(54, round(gray.shape[0] * analysis_width / gray.shape[1]))
            small_gray = cv2.resize(
                gray, (analysis_width, height), interpolation=cv2.INTER_AREA
            )
            features = _compensated_motion_features(previous_gray, small_gray)
            sharpness = float(cv2.Laplacian(small_gray, cv2.CV_64F).var())
            candidates.append(
                {
                    "timestamp": round(timestamp, 3),
                    "source_frame_index": source_index,
                    **features,
                    "sharpness": sharpness,
                }
            )
            previous_gray = small_gray
        return candidates

    def _normalize_features(self, candidates: list[dict[str, Any]]) -> None:
        for name in (
            "residual_flow",
            "motion_area",
            "local_change",
            "edge_change",
            "global_motion",
            "sharpness",
        ):
            normalized = _robust_normalize(
                [float(item.get(name, 0.0)) for item in candidates]
            )
            for item, value in zip(candidates, normalized, strict=False):
                item[f"{name}_norm"] = value
        raw_scores = [
            min(
                1.0,
                0.38 * item["residual_flow_norm"]
                + 0.25 * item["motion_area_norm"]
                + 0.24 * item["local_change_norm"]
                + 0.13 * item["edge_change_norm"],
            )
            for item in candidates
        ]
        smoothed = _smooth_scores(
            raw_scores,
            median_radius=max(
                0, int(self.event_settings.get("median_radius_frames", 1))
            ),
            ema_alpha=float(self.event_settings.get("ema_alpha", 0.55)),
        )
        for item, raw, score in zip(candidates, raw_scores, smoothed, strict=False):
            item["activity_score_raw"] = round(raw, 5)
            item["activity_score"] = round(score, 5)

    def _detect_events(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return []
        start_threshold = float(
            self.event_settings.get(
                "start_threshold",
                self.event_settings.get("activity_threshold", 0.42),
            )
        )
        stop_threshold = float(
            self.event_settings.get("stop_threshold", start_threshold * 0.55)
        )
        if stop_threshold >= start_threshold:
            raise ValueError("stop_threshold 必须小于 start_threshold")
        active = _hysteresis_activity(
            [float(item["activity_score"]) for item in candidates],
            start_threshold,
            stop_threshold,
        )
        active = _close_short_gaps(
            active,
            max(
                1,
                round(
                    float(self.event_settings.get("max_gap_seconds", 0.375))
                    * self.candidate_fps
                ),
            ),
        )
        minimum_seconds = float(
            self.event_settings.get("minimum_duration_seconds", 0.25)
        )
        events: list[dict[str, Any]] = []
        for event_index, (start_index, end_index) in enumerate(_true_runs(active)):
            start_time = float(candidates[start_index]["timestamp"])
            end_time = float(candidates[end_index]["timestamp"])
            if end_time - start_time < minimum_seconds:
                continue
            indices = list(range(start_index, end_index + 1))
            first_half_end = start_index + max(1, len(indices) // 2)
            contact_indices = list(
                range(start_index, min(end_index, first_half_end) + 1)
            )
            contact_index = max(
                contact_indices,
                key=lambda idx: (
                    0.50 * candidates[idx]["local_change_norm"]
                    + 0.30 * candidates[idx]["edge_change_norm"]
                    + 0.20 * candidates[idx]["motion_area_norm"]
                ),
            )
            manipulate_index = max(
                indices,
                key=lambda idx: (
                    0.55 * candidates[idx]["activity_score"]
                    + 0.20 * candidates[idx]["residual_flow_norm"]
                    + 0.15 * candidates[idx]["motion_area_norm"]
                    + 0.10 * candidates[idx]["local_change_norm"]
                ),
            )
            rapid_change_indices = (
                range(start_index + 1, end_index + 1)
                if end_index > start_index
                else [start_index]
            )
            rapid_change_index = max(
                rapid_change_indices,
                key=lambda idx: _transition_score(candidates, idx),
            )
            pre_index = max(
                0,
                start_index
                - round(
                    float(self.event_settings.get("pre_context_seconds", 0.5))
                    * self.candidate_fps
                ),
            )
            post_index = min(
                len(candidates) - 1,
                end_index
                + round(
                    float(self.event_settings.get("post_context_seconds", 0.25))
                    * self.candidate_fps
                ),
            )
            events.append(
                {
                    "event_id": f"event_{event_index:04d}",
                    "start_time": start_time,
                    "end_time": end_time,
                    "confidence": round(
                        max(float(candidates[idx]["activity_score"]) for idx in indices),
                        4,
                    ),
                    "phases": {
                        "pre": float(candidates[pre_index]["timestamp"]),
                        "onset": float(candidates[start_index]["timestamp"]),
                        "contact": float(candidates[contact_index]["timestamp"]),
                        "manipulate": float(candidates[manipulate_index]["timestamp"]),
                        "rapid_change": float(
                            candidates[rapid_change_index]["timestamp"]
                        ),
                        "post": float(candidates[post_index]["timestamp"]),
                    },
                }
            )
        return events

    def _select_window_frames(
        self,
        candidates: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        if self.event_settings.get("coverage_guarantee_enabled", False):
            return select_context_frames(
                candidates, events, self.minimum_frames,
                self.maximum_frames, self.event_settings,
            )
        selected: dict[float, dict[str, Any]] = {}
        by_time = {round(float(item["timestamp"]), 3): item for item in candidates}
        candidate_index = {
            round(float(item["timestamp"]), 3): index
            for index, item in enumerate(candidates)
        }

        def add(
            timestamp: float,
            role: str,
            event: dict[str, Any] | None,
            *,
            reason: str | None = None,
        ) -> None:
            nearest_time = min(by_time, key=lambda value: abs(value - timestamp))
            source = by_time[nearest_time]
            score = min(
                1.0,
                0.78 * float(source.get("activity_score", 0.0))
                + 0.22 * float(source.get("sharpness_norm", 0.0)),
            )
            target = selected.setdefault(
                nearest_time,
                {
                    **source,
                    "selection_score": score,
                    "selection_roles": set(),
                    "event_ids": set(),
                    "selection_reasons": set(),
                },
            )
            target["selection_score"] = max(float(target["selection_score"]), score)
            target["selection_roles"].add(role)
            target["selection_reasons"].add(
                reason or f"motion_event_phase:{role}"
            )
            if event is not None:
                target["event_ids"].add(event["event_id"])

        ordered_events = sorted(
            events,
            key=lambda item: (
                -float(item.get("confidence", 0.0)),
                float(item.get("start_time", 0.0)),
            ),
        )

        # Allocate the fixed budget in phase rounds so every event gets its
        # onset and peak before a strong event can consume all available frames.
        # This protects short door/handle transitions without increasing the
        # number of frames sent to the VLM.
        for role in ("onset", "manipulate", "post", "pre"):
            for event in ordered_events:
                if len(selected) >= self.maximum_frames:
                    break
                timestamp = float(
                    event.get("phases", {}).get(
                        role,
                        event.get(
                            "start_time"
                            if role in {"pre", "onset", "manipulate"}
                            else "end_time",
                            0.0,
                        ),
                    )
                )
                if candidates[0]["timestamp"] <= timestamp <= candidates[-1]["timestamp"]:
                    add(timestamp, role, event)

        # Contact is a useful proxy but is less reliable than onset/peak/post,
        # so it consumes only spare budget.
        for event in ordered_events:
            if len(selected) >= self.maximum_frames:
                break
            timestamp = event.get("phases", {}).get("contact")
            if (
                timestamp is not None
                and candidates[0]["timestamp"]
                <= float(timestamp)
                <= candidates[-1]["timestamp"]
            ):
                add(float(timestamp), "contact", event)

        # When budget remains, fill long gaps inside detected events with the
        # strongest structural/score transition.  These guarded frames are
        # especially useful for fast open/close, grasp and release motions.
        maximum_gap = max(
            1.0 / self.candidate_fps,
            float(self.event_settings.get("rapid_change_max_gap_seconds", 0.5)),
        )
        for event in ordered_events:
            while len(selected) < self.maximum_frames:
                start = max(
                    float(candidates[0]["timestamp"]),
                    float(event.get("start_time", candidates[0]["timestamp"])),
                )
                end = min(
                    float(candidates[-1]["timestamp"]),
                    float(event.get("end_time", candidates[-1]["timestamp"])),
                )
                anchors = sorted(
                    {
                        start,
                        end,
                        *(
                            float(timestamp)
                            for timestamp in selected
                            if start <= float(timestamp) <= end
                        ),
                    }
                )
                gaps = [
                    (left, right)
                    for left, right in zip(anchors, anchors[1:], strict=False)
                    if right - left > maximum_gap
                ]
                if not gaps:
                    break
                left, right = max(gaps, key=lambda pair: pair[1] - pair[0])
                remaining = [
                    item
                    for item in candidates
                    if left < float(item["timestamp"]) < right
                    and round(float(item["timestamp"]), 3) not in selected
                ]
                if not remaining:
                    break
                best = max(
                    remaining,
                    key=lambda item: (
                        _transition_score(
                            candidates,
                            candidate_index[round(float(item["timestamp"]), 3)],
                        ),
                        min(
                            float(item["timestamp"]) - left,
                            right - float(item["timestamp"]),
                        ),
                    ),
                )
                add(
                    float(best["timestamp"]),
                    "manipulate",
                    event,
                    reason="rapid_change_gap_guard",
                )

        for timestamp in (
            float(candidates[0]["timestamp"]),
            float(candidates[-1]["timestamp"]),
        ):
            if len(selected) >= self.maximum_frames:
                break
            add(timestamp, "coverage", None, reason="window_boundary_coverage")
        while len(selected) < self.minimum_frames and len(selected) < len(candidates):
            existing = list(selected)
            remaining = [
                item for item in candidates if item["timestamp"] not in selected
            ]
            best = max(
                remaining,
                key=lambda item: min(
                    abs(float(item["timestamp"]) - timestamp)
                    for timestamp in existing
                )
                + 0.25 * float(item.get("sharpness_norm", 0.0)),
            )
            add(
                float(best["timestamp"]),
                "coverage",
                None,
                reason="temporal_coverage_fill",
            )
        ranked = list(selected.values())
        if len(ranked) > self.maximum_frames:
            ranked = sorted(
                ranked,
                key=lambda item: (
                    max(
                        ROLE_PRIORITY.get(role, 0)
                        for role in item["selection_roles"]
                    ),
                    float(item["selection_score"]),
                ),
                reverse=True,
            )[: self.maximum_frames]
        return sorted(ranked, key=lambda item: float(item["timestamp"]))

    def _export_selected_frames(
        self,
        video_path: Path,
        output_dir: Path,
        selected_by_window: list[tuple[str, float, float, list[dict[str, Any]]]],
    ) -> dict[float, Path]:
        import cv2

        timestamps = sorted(
            {
                round(float(item["timestamp"]), 3)
                for _, _, _, selected in selected_by_window
                for item in selected
            }
        )
        capture = cv2.VideoCapture(str(video_path))
        exported: dict[float, Path] = {}
        for timestamp in timestamps:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            success, frame = capture.read()
            if not success:
                continue
            path = output_dir / f"{_frame_id(timestamp)}.jpg"
            written = cv2.imwrite(
                str(path), frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if written and path.exists():
                exported[timestamp] = path
        capture.release()
        return exported


def select_global_event_frames(
    windows: list[VideoWindow], max_frames: int
) -> list[FrameReference]:
    merged: dict[float, FrameReference] = {}
    for window in windows:
        for frame in window.frames:
            key = round(frame.timestamp, 3)
            current = merged.get(key)
            if current is None:
                merged[key] = frame
                continue
            merged[key] = current.model_copy(
                update={
                    "selection_score": max(
                        current.selection_score, frame.selection_score
                    ),
                    "selection_roles": sorted(
                        set(current.selection_roles) | set(frame.selection_roles)
                    ),
                    "event_ids": sorted(set(current.event_ids) | set(frame.event_ids)),
                    "selection_reasons": sorted(
                        set(current.selection_reasons)
                        | set(frame.selection_reasons)
                    ),
                }
            )
    ordered = [merged[key] for key in sorted(merged)]
    limit = max(2, int(max_frames))
    if len(ordered) <= limit:
        return ordered
    selected = {0, len(ordered) - 1}
    ranked = sorted(
        range(1, len(ordered) - 1),
        key=lambda index: (
            max(
                (
                    ROLE_PRIORITY.get(role, 0)
                    for role in ordered[index].selection_roles
                ),
                default=0,
            ),
            ordered[index].selection_score,
        ),
        reverse=True,
    )
    for index in ranked:
        if len(selected) >= limit:
            break
        selected.add(index)
    return [ordered[index] for index in sorted(selected)]


def _compensated_motion_features(previous_gray: Any, current_gray: Any) -> dict[str, Any]:
    import cv2
    import numpy as np

    empty = {
        "residual_flow": 0.0,
        "motion_area": 0.0,
        "local_change": 0.0,
        "edge_change": 0.0,
        "global_motion": 0.0,
        "motion_bbox": None,
    }
    if previous_gray is None:
        return empty
    matrix, global_motion = _estimate_global_affine(previous_gray, current_gray)
    aligned = cv2.warpAffine(
        previous_gray,
        matrix,
        (current_gray.shape[1], current_gray.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    flow = cv2.calcOpticalFlowFarneback(
        aligned, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
    )
    magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
    difference = cv2.absdiff(aligned, current_gray)
    motion_mask = ((magnitude >= 0.7) & (difference >= 8)).astype(np.uint8) * 255
    kernel = np.ones((3, 3), dtype=np.uint8)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, kernel)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, kernel)
    active_magnitude = magnitude[motion_mask > 0]
    motion_area = float(np.count_nonzero(motion_mask) / motion_mask.size)
    residual_flow = (
        float(np.percentile(active_magnitude, 85))
        if active_magnitude.size
        else 0.0
    )
    previous_edges = cv2.Canny(aligned, 50, 150)
    current_edges = cv2.Canny(current_gray, 50, 150)
    bbox = None
    contours, _ = cv2.findContours(
        motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if contours:
        contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(contour) >= 0.002 * motion_mask.size:
            x, y, width, height = cv2.boundingRect(contour)
            bbox = [
                round(x / motion_mask.shape[1], 6),
                round(y / motion_mask.shape[0], 6),
                round((x + width) / motion_mask.shape[1], 6),
                round((y + height) / motion_mask.shape[0], 6),
            ]
    return {
        "residual_flow": residual_flow,
        "motion_area": motion_area,
        "local_change": float(np.mean(difference) / 255.0),
        "edge_change": float(
            np.count_nonzero(cv2.bitwise_xor(previous_edges, current_edges))
            / previous_edges.size
        ),
        "global_motion": global_motion,
        "motion_bbox": bbox,
    }


def _estimate_global_affine(previous_gray: Any, current_gray: Any) -> tuple[Any, float]:
    """Estimate camera translation/rotation/scale with classical feature tracks."""

    import cv2
    import numpy as np

    diagonal = max(
        1.0,
        math.hypot(current_gray.shape[1], current_gray.shape[0]),
    )
    corners = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=180,
        qualityLevel=0.01,
        minDistance=7,
        blockSize=7,
    )
    if corners is not None and len(corners) >= 8:
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray,
            current_gray,
            corners,
            None,
            winSize=(21, 21),
            maxLevel=3,
        )
        if tracked is not None and status is not None:
            valid = status.reshape(-1).astype(bool)
            source = corners.reshape(-1, 2)[valid]
            target = tracked.reshape(-1, 2)[valid]
            if len(source) >= 8:
                matrix, inliers = cv2.estimateAffinePartial2D(
                    source,
                    target,
                    method=cv2.RANSAC,
                    ransacReprojThreshold=2.5,
                )
                if matrix is not None:
                    mask = (
                        inliers.reshape(-1).astype(bool)
                        if inliers is not None
                        else np.ones(len(source), dtype=bool)
                    )
                    displacement = np.linalg.norm(target[mask] - source[mask], axis=1)
                    motion = (
                        float(np.median(displacement)) / diagonal
                        if displacement.size
                        else 0.0
                    )
                    return matrix.astype(np.float32), motion

    try:
        shift, _ = cv2.phaseCorrelate(
            previous_gray.astype(np.float32),
            current_gray.astype(np.float32),
        )
    except cv2.error:
        shift = (0.0, 0.0)
    matrix = np.float32([[1, 0, shift[0]], [0, 1, shift[1]]])
    return matrix, math.hypot(float(shift[0]), float(shift[1])) / diagonal


def _robust_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    import numpy as np

    array = np.asarray(values, dtype=float)
    low = float(np.percentile(array, 10))
    high = float(np.percentile(array, 90))
    if high <= low + 1e-9:
        return [0.0 for _ in values]
    return [
        float(max(0.0, min(1.0, (value - low) / (high - low))))
        for value in values
    ]


def _smooth_scores(
    values: list[float], *, median_radius: int, ema_alpha: float
) -> list[float]:
    if not values:
        return []
    alpha = max(0.0, min(1.0, ema_alpha))
    median_values = []
    for index in range(len(values)):
        start = max(0, index - median_radius)
        end = min(len(values), index + median_radius + 1)
        ordered = sorted(values[start:end])
        median_values.append(ordered[len(ordered) // 2])
    result = [median_values[0]]
    for value in median_values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def _transition_score(candidates: list[dict[str, Any]], index: int) -> float:
    """Score abrupt local changes without introducing a learned detector."""

    current = candidates[index]
    if index <= 0:
        return float(current.get("activity_score", 0.0))
    previous = candidates[index - 1]
    activity_rise = max(
        0.0,
        float(current.get("activity_score", 0.0))
        - float(previous.get("activity_score", 0.0)),
    )
    local_delta = abs(
        float(current.get("local_change_norm", 0.0))
        - float(previous.get("local_change_norm", 0.0))
    )
    edge_delta = abs(
        float(current.get("edge_change_norm", 0.0))
        - float(previous.get("edge_change_norm", 0.0))
    )
    area_delta = abs(
        float(current.get("motion_area_norm", 0.0))
        - float(previous.get("motion_area_norm", 0.0))
    )
    return (
        0.45 * activity_rise
        + 0.25 * local_delta
        + 0.20 * edge_delta
        + 0.10 * area_delta
    )


def _hysteresis_activity(
    scores: list[float], start_threshold: float, stop_threshold: float
) -> list[bool]:
    active = False
    result = []
    for score in scores:
        if not active and score >= start_threshold:
            active = True
        elif active and score < stop_threshold:
            active = False
        result.append(active)
    return result


def _close_short_gaps(values: list[bool], maximum_gap: int) -> list[bool]:
    result = list(values)
    index = 0
    while index < len(result):
        if result[index]:
            index += 1
            continue
        start = index
        while index < len(result) and not result[index]:
            index += 1
        end = index - 1
        if start > 0 and index < len(result) and end - start + 1 <= maximum_gap:
            for gap_index in range(start, end + 1):
                result[gap_index] = True
    return result


def _true_runs(values: list[bool]) -> list[tuple[int, int]]:
    runs = []
    start = None
    for index, value in enumerate([*values, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None
    return runs


def _window_bounds(
    duration: float, window_seconds: float, overlap_seconds: float
) -> list[tuple[float, float]]:
    if window_seconds <= overlap_seconds:
        raise ValueError("window_seconds 必须大于 overlap_seconds")
    bounds = []
    step = window_seconds - overlap_seconds
    start = 0.0
    while start < duration:
        end = min(duration, start + window_seconds)
        bounds.append((round(start, 6), round(end, 6)))
        if end >= duration:
            break
        start += step
    return bounds


def _frame_id(timestamp: float) -> str:
    return f"frame_t{round(timestamp * 1000):09d}"


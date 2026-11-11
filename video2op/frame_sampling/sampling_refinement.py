"""Bounded motion proposals and context-preserving sampling, not semantic labels."""
from __future__ import annotations

from typing import Any


def split_motion_events(candidates, events, settings):
    """Split long runs at motion valleys, falling back to a duration bound.

    A split is only a proposal for another model input. It does not establish
    an action, contact, grasp, or a semantic before/after state.
    """
    if not settings.get("enabled", False) or not candidates:
        return events
    threshold = float(settings.get("long_event_seconds", 4.0))
    core = float(settings.get("max_core_seconds", 3.0))
    minimum = float(settings.get("min_core_seconds", 1.0))
    if minimum <= 0 or core < minimum or threshold <= 0:
        raise ValueError("Invalid refinement segment duration settings")
    output = []
    for event in events:
        start, end = event["start_time"], event["end_time"]
        if end - start <= threshold:
            output.append(event)
            continue
        boundaries = [start]
        while end - boundaries[-1] > core and len(boundaries) < 256:
            left = boundaries[-1]
            target = min(left + core, end - minimum)
            nearby = [c for c in candidates
                      if max(left + minimum, target - 0.75) <= c["timestamp"] <= target]
            valleys = [c for c in nearby if _is_valley(candidates, c)]
            chosen = min(valleys, key=lambda c: (c["activity_score"],
                                                abs(c["timestamp"] - target))) if valleys else None
            boundary = float(chosen["timestamp"]) if chosen else target
            if boundary <= left:
                break
            boundaries.append(boundary)
        boundaries.append(end)
        for index, (left, right) in enumerate(zip(boundaries, boundaries[1:], strict=False)):
            segment = make_segment(candidates, left, right, settings)
            segment.update(event_id=f"{event['event_id']}_part_{index:03d}",
                           parent_event_id=event["event_id"],
                           boundary_kind="motion_valley_or_duration_proposal",
                           semantic_action_confirmed=False)
            output.append(segment)
    return output


def _is_valley(candidates, item):
    index = next((i for i, c in enumerate(candidates) if c is item), -1)
    return (0 < index < len(candidates) - 1
            and item["activity_score"] <= candidates[index - 1]["activity_score"]
            and item["activity_score"] <= candidates[index + 1]["activity_score"]
            and (item["activity_score"] < candidates[index - 1]["activity_score"]
                 or item["activity_score"] < candidates[index + 1]["activity_score"]))


def make_segment(candidates, start, end, settings):
    inside = [c for c in candidates if start <= c["timestamp"] <= end]
    peak = max(inside, key=lambda c: c["activity_score"]) if inside else min(
        candidates, key=lambda c: abs(c["timestamp"] - start))
    pre = min(candidates, key=lambda c: abs(c["timestamp"] -
              (start - float(settings.get("pre_context_seconds", 0.5)))))
    post = min(candidates, key=lambda c: abs(c["timestamp"] -
               (end + float(settings.get("post_context_seconds", 0.5)))))
    return {"start_time": start, "end_time": end,
            "confidence": float(peak["activity_score"]),
            "phases": {"pre": pre["timestamp"], "onset": start,
                       "manipulate": peak["timestamp"], "post": post["timestamp"]}}


def plan_refinement_windows(candidates, events, segments, settings):
    if not settings.get("enabled", False) or not candidates:
        return [], 0
    limit = max(0, int(settings.get("max_additional_windows", 8)))
    short = float(settings.get("short_event_seconds", 0.75))
    groups = {}
    for segment in segments:
        parent = segment.get("parent_event_id", segment["event_id"])
        if (not settings.get("include_all_events", False) and "parent_event_id" not in segment
                and segment["end_time"] - segment["start_time"] > short):
            continue
        groups.setdefault(parent, []).append(segment)
    # Round-robin over parent events prevents one long run consuming the cap.
    proposals = []
    while any(groups.values()):
        for group in groups.values():
            if group:
                proposals.append(group.pop(0))
    selected = proposals[:limit]
    plan = []
    for index, segment in enumerate(selected):
        start = max(candidates[0]["timestamp"], segment["phases"]["pre"])
        end = min(candidates[-1]["timestamp"], segment["phases"]["post"])
        if end > start:
            plan.append({"window_id": f"refine_{index:04d}", "start_time": start,
                         "end_time": end, "core_start": segment["start_time"],
                         "core_end": segment["end_time"], "event": segment,
                         "reason": "long_event_subdivision" if "parent_event_id" in segment
                                   else ("context_deficit_resampling" if settings.get("include_all_events")
                                         else "short_event_dense_resampling")})
    return plan, max(0, len(proposals) - limit)


def select_context_frames(candidates, events, minimum, maximum, settings):
    """Reserve context before peaks; use actual timestamps, never invented frames."""
    if not candidates:
        return []
    selected: dict[float, dict[str, Any]] = {}

    def add(item, role, event=None, reason="reserved_temporal_coverage"):
        timestamp = item["timestamp"]
        if timestamp not in selected and len(selected) >= maximum:
            return
        target = selected.setdefault(timestamp, {
            **item, "selection_score": min(1.0, 0.78 * item["activity_score"]
                    + 0.22 * item.get("sharpness_norm", 0.0)),
            "selection_roles": set(), "event_ids": set(), "selection_reasons": set(),
            "event_roles": {}})
        target["selection_roles"].add(role)
        target["selection_reasons"].add(reason)
        if event:
            target["event_ids"].add(event["event_id"])
            target["event_roles"].setdefault(event["event_id"], set()).add(role)

    add(candidates[0], "coverage")
    add(candidates[-1], "coverage")
    if int(settings.get("reserved_coverage_frames", 2)) >= 3 and maximum >= 6:
        midpoint = (candidates[0]["timestamp"] + candidates[-1]["timestamp"]) / 2
        add(min(candidates, key=lambda c: abs(c["timestamp"] - midpoint)), "coverage")
    ordered = sorted(events, key=lambda e: e["start_time"])
    for role in ("pre", "post", "onset", "manipulate"):
        for event in ordered:
            stamp = event.get("phases", {}).get(role)
            if stamp is None or not candidates[0]["timestamp"] <= stamp <= candidates[-1]["timestamp"]:
                continue
            nearest = min(candidates, key=lambda c: abs(c["timestamp"] - stamp))
            if role == "pre" and nearest["timestamp"] >= event["start_time"]:
                continue
            if role == "post" and nearest["timestamp"] <= event["end_time"]:
                continue
            add(nearest, role, event, f"context_guarantee:{role}")
    gap_limit = float(settings.get("rapid_change_max_gap_seconds", 0.5))
    while len(selected) < min(maximum, len(candidates)):
        times = sorted(selected)
        gaps = list(zip(times, times[1:], strict=False))
        if not gaps:
            break
        left, right = max(gaps, key=lambda pair: pair[1] - pair[0])
        if len(selected) >= minimum and right - left <= gap_limit:
            break
        remaining = [c for c in candidates if left < c["timestamp"] < right
                     and c["timestamp"] not in selected]
        if not remaining:
            break
        # Prefer temporal coverage, with a small bonus for structural changes.
        item = max(remaining, key=lambda c: min(c["timestamp"] - left, right - c["timestamp"])
                   + 0.10 * c.get("local_change_norm", 0.0)
                   + 0.05 * c.get("edge_change_norm", 0.0))
        add(item, "manipulate", reason="local_dense_gap_fill")
    return sorted(selected.values(), key=lambda c: c["timestamp"])


def coverage_diagnostics(selected, events):
    times = sorted(c["timestamp"] for c in selected)
    missing = []
    for event in events:
        roles = {role for c in selected if event["event_id"] in c["event_ids"]
                 for role in (c["event_roles"].get(event["event_id"], set())
                              if "event_roles" in c else c["selection_roles"])}
        absent = sorted({"pre", "onset", "manipulate", "post"} - roles)
        if absent:
            missing.append({"event_id": event["event_id"], "missing_roles": absent})
    return {"max_selected_gap_seconds": round(max(
                (b - a for a, b in zip(times, times[1:], strict=False)), default=0.0), 3),
            "missing_event_context": missing,
            "note": "Frame coverage only; semantic before/after states require VLM verification."}


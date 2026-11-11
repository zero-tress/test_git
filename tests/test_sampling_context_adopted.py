"""Sampling context regressions adapted from the colleague project."""
from video2op.frame_sampling.sampling_refinement import (
    coverage_diagnostics,
    make_segment,
    plan_refinement_windows,
    select_context_frames,
    split_motion_events,
)


def _timeline(seconds=20.0):
    return [{"timestamp": i / 8, "source_frame_index": i,
             "activity_score": 0.8, "sharpness_norm": 0.8,
             "local_change_norm": 0.3, "edge_change_norm": 0.3,
             "residual_flow_norm": 0.3, "motion_area_norm": 0.3,
             "global_motion_norm": 0.0}
            for i in range(int(seconds * 8) + 1)]


def _settings(**extra):
    return {"enabled": True, "long_event_seconds": 4.0,
            "max_core_seconds": 3.0, "min_core_seconds": 1.0,
            "short_event_seconds": 0.75, "pre_context_seconds": 0.5,
            "post_context_seconds": 0.5, "max_additional_windows": 8, **extra}


def _event(candidates, start, end, event_id="event_0000"):
    return {**make_segment(candidates, start, end, _settings()), "event_id": event_id}


def test_long_motion_run_is_subdivided_without_claiming_semantic_actions():
    candidates = _timeline()
    events = [_event(candidates, 0.5, 19.0)]
    segments = split_motion_events(candidates, events, _settings())
    assert len(segments) > 1
    assert segments[0]["start_time"] == 0.5
    assert segments[-1]["end_time"] == 19.0
    assert all(0 < s["end_time"] - s["start_time"] <= 3.0 for s in segments)
    assert all(s["parent_event_id"] == "event_0000" for s in segments)
    assert all(s["semantic_action_confirmed"] is False for s in segments)
    assert all(a["end_time"] == b["start_time"] for a, b in zip(segments, segments[1:], strict=False))


def test_valley_is_preferred_over_arbitrary_boundary():
    candidates = _timeline(8)
    candidates[22]["activity_score"] = 0.3  # 2.75 seconds
    segments = split_motion_events(candidates, [_event(candidates, 0.0, 8.0)], _settings())
    assert segments[0]["end_time"] == 2.75


def test_disabled_refinement_preserves_original_events():
    candidates = _timeline()
    events = [_event(candidates, 0, 19)]
    assert split_motion_events(candidates, events, {}) is events
    assert plan_refinement_windows(candidates, events, events, {}) == ([], 0)


def test_extra_window_cap_is_enforced_and_shared_between_events():
    candidates = _timeline()
    events = [_event(candidates, 0.5, 12), _event(candidates, 15, 15.5, "event_0001")]
    settings = _settings(max_additional_windows=2)
    segments = split_motion_events(candidates, events, settings)
    plan, skipped = plan_refinement_windows(candidates, events, segments, settings)
    assert len(plan) == 2 and skipped > 0
    assert {p["event"].get("parent_event_id", p["event"]["event_id"]) for p in plan} == {
        "event_0000", "event_0001"}


def test_short_event_gets_dense_context_window():
    candidates = _timeline(6)
    events = [_event(candidates, 2.0, 2.25)]
    plan, skipped = plan_refinement_windows(candidates, events, events, _settings())
    assert len(plan) == 1 and skipped == 0
    assert plan[0]["start_time"] == 1.5
    assert plan[0]["end_time"] == 2.75
    assert plan[0]["reason"] == "short_event_dense_resampling"


def test_context_frames_are_reserved_before_peaks():
    candidates = _timeline(6)
    event = _event(candidates, 1, 5)
    selected = select_context_frames(candidates, [event], 6, 10, {})
    times = {c["timestamp"] for c in selected}
    assert {0, 0.5, 1, 5.5, 6} <= times
    assert len(selected) <= 10
    assert not coverage_diagnostics(selected, [event])["missing_event_context"]


def test_video_edge_does_not_invent_unseen_pre_or_post_state():
    candidates = _timeline(3)
    event = _event(candidates, 0, 3)
    selected = select_context_frames(candidates, [event], 6, 10, {})
    missing = coverage_diagnostics(selected, [event])["missing_event_context"]
    assert {"pre", "post"} <= set(missing[0]["missing_roles"])
    assert all("pre" not in c["selection_roles"] and "post" not in c["selection_roles"]
               for c in selected)


def test_small_budget_reports_missing_context_instead_of_silent_guarantee():
    candidates = _timeline(6)
    event = _event(candidates, 1, 5)
    selected = select_context_frames(candidates, [event], 2, 2, {})
    assert len(selected) == 2
    assert coverage_diagnostics(selected, [event])["missing_event_context"]


def test_roles_from_another_event_do_not_hide_missing_context():
    selected = [{"timestamp": 1.0, "event_ids": {"a", "b"},
                 "selection_roles": {"pre", "post", "onset", "manipulate"},
                 "event_roles": {"a": {"onset"}, "b": {"pre", "post", "manipulate"}}}]
    diagnostics = coverage_diagnostics(selected, [{"event_id": "a"}])
    assert set(diagnostics["missing_event_context"][0]["missing_roles"]) == {
        "pre", "post", "manipulate"}


def test_zero_motion_still_has_temporal_coverage():
    candidates = _timeline(6)
    for item in candidates:
        item["activity_score"] = 0
    selected = select_context_frames(candidates, [], 6, 10, {})
    assert len(selected) >= 6
    assert selected[0]["timestamp"] == 0 and selected[-1]["timestamp"] == 6



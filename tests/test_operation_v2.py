from __future__ import annotations

import copy
from pathlib import Path

import pytest
import requests

from video2op import config, media
from video2op.abstraction import validate_semantics
from video2op.llm import LLMError, VLMClient
from video2op.pipeline import build_legacy_execution_graph as build_operation_graph
from video2op.stages import s02b_atomic, s02e_prior, s04_conditions


def action(i, executor, name, start=0, end=1, **kw):
    return dict(id=i, executor=executor, action=name, mode="motion",
                start=start, end=end, state_before="", state_after="",
                world_before=[], world_after=[], confidence=0.8,
                inferred=False, **kw)


def node(i, name, refs, parts, start=0, end=1):
    return dict(id=i, name=name, intent_role="到达下一操作所需的位置",
                required_capabilities=[name], time_range=[start, end], atomic_refs=refs,
                tuple={"X": {"subject": "操作者", "parts": parts}, "O": ["工作台"],
                       "C_pre": [], "C_const": [], "C_post": [],
                       "E": {"process": [], "completion": []}, "R": []})


@pytest.mark.parametrize("executor", ["腰", "躯干", "左腿", "右腿", "膝关节", "左脚"])
def test_legacy_anatomy_cannot_enter_new_extraction(executor):
    with pytest.raises(ValueError):
        s02b_atomic._validate({"atomic_actions": [action(1, executor, "改变位置")]})


@pytest.mark.parametrize("name", ["向目标移动", "上升", "下降"])
def test_overall_motion_survives_graph_and_contract(name):
    a = action(1, "整体", name, object="工作台")
    s02b_atomic._validate({"atomic_actions": [a]})
    b = {"atomic": {"atomic_actions": [a]}, "relations": [],
         "task_nodes": {"task_nodes": [node("n1", name, [1], ["整体"])]}}
    build_operation_graph(b)
    assert b["operations"]["nodes"][0]["executors"] == ["整体"]
    exported = [n for n in b["contract"]["nodes"].values()
                if n.get("x-video2op", {}).get("operation_id") == "n1"]
    assert exported and exported[0]["subject"] == "LocomotionSystem"


def test_arms_hands_and_target_object_anatomy_are_preserved():
    acts = [dict(action(i, p, "靠近椅脚" if p.endswith("臂") else "抓握椅脚"),
                 mode="motion" if p.endswith("臂") else "transition") for i, p in enumerate(
        ["左臂", "右臂", "左手", "右手"], 1)]
    s02b_atomic._validate({"atomic_actions": acts})
    validate_semantics({"condition": "桌腿与椅脚无碰撞"})
    assert [a["executor"] for a in s02b_atomic._normalize_window(
        {"atomic_actions": acts}, 1)["atomic_actions"]] == ["左臂", "右臂", "左手", "右手"]


def test_legacy_rebuild_rejected_without_mutating_observations():
    b = {"atomic": {"atomic_actions": [action(1, "腰", "弯曲")]}}
    before = copy.deepcopy(b)
    with pytest.raises(ValueError, match="重新分析"):
        build_operation_graph(b)
    assert b == before


def test_overall_motion_has_no_background_support_inference():
    acts = [action(1, "整体", "上升", 0, 2), action(2, "整体", "下降", 6, 8)]
    assert s02e_prior.run(acts, 10)["inferred_actions"] == []


def catalog_fixture():
    nodes = [node("n1", "抓取", [1], ["右手"]), node("n2", "放置", [2], ["右手"])]
    nodes[0]["tuple"]["C_pre"] = ["目标可达", "目标可达"]
    nodes[0]["tuple"]["C_post"] = ["物体已抓稳"]
    nodes[1]["tuple"]["C_pre"] = ["目标可达"]
    return nodes, s04_conditions.condition_catalog(nodes)


def compact_rows(catalog):
    return {"items": [{"id": c["id"], "verdict": "证据不足",
                       "positive": ["未观察到", "画面未覆盖"],
                       "negative_a": ["可能失败", "推理假设"],
                       "negative_b": ["可能未发起", "推理假设"], "confidence": 0.4}
                      for c in catalog]}


def test_condition_catalog_dedups_only_within_node_and_kind():
    nodes, cat = catalog_fixture()
    assert len(cat) == 3
    result = s04_conditions.expand_compact(compact_rows(cat), cat, nodes)
    assert result["condition_learning"][0]["C_pre_learning"][0]["condition"] == "目标可达"
    assert len(result["condition_learning"][1]["C_pre_learning"]) == 1


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unknown", "empty_evidence"])
def test_condition_coverage_cannot_be_silently_truncated(mode):
    nodes, cat = catalog_fixture()
    value = compact_rows(cat)
    if mode == "missing":
        value["items"].pop()
    elif mode == "duplicate":
        value["items"].append(copy.deepcopy(value["items"][0]))
    elif mode == "unknown":
        value["items"][0]["id"] = "c999"
    else:
        value["items"][0]["negative_a"] = ["", ""]
    with pytest.raises(ValueError):
        s04_conditions.expand_compact(value, cat, nodes)


class Response:
    status_code = 200

    def __init__(self, content='{"ok":true}', finish="stop"):
        self.content, self.finish = content, finish

    def json(self):
        return {"choices": [{"message": {"content": self.content},
                             "finish_reason": self.finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_client_rejects_truncated_json_and_expands_budget(tmp_path, monkeypatch):
    client = VLMClient(tmp_path)
    sent = []
    replies = iter([Response('{"ok":true}', "length"), Response()])
    def post(*args, **kw):
        sent.append(copy.deepcopy(kw["json"]))
        return next(replies)
    monkeypatch.setattr(client.session, "post", post)
    assert client.ask(stage="s01_viewpoint", system="s", user_text="u") == {"ok": True}
    assert sent[1]["max_tokens"] > sent[0]["max_tokens"]
    assert len(sent[1]["messages"]) == 3
    assert client.stats["calls"] == 2
    assert client.stats["attempts"][0]["status"] == "error"
    assert client.stats["attempts"][1]["usage"]["completion_tokens"] == 5


def test_client_never_repairs_incomplete_response_into_cached_success(tmp_path, monkeypatch):
    client = VLMClient(tmp_path)
    monkeypatch.setattr(client.session, "post", lambda *a, **k: Response('{"items":[{"id":1}'))
    with pytest.raises(LLMError):
        client.ask(stage="test", system="s", user_text="u", attempts=1)
    assert not list(tmp_path.glob("*.json"))


def test_video_content_and_budget_invalidate_request_cache(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"first")
    client = VLMClient(tmp_path / "cache")
    calls = []
    def post(*a, **kw):
        calls.append(kw)
        return Response()
    monkeypatch.setattr(client.session, "post", post)
    def ask(tokens=1024):
        return client.ask(stage="test", system="s", user_text="u", video=video,
                          video_id="same", max_tokens=tokens)
    ask()
    ask()
    assert len(calls) == 1
    video.write_bytes(b"second")
    ask()
    ask(2048)
    assert len(calls) == 3
    assert client.stats["cache_hits"] == 1


def test_failed_connection_is_measured_and_not_retried_three_times(tmp_path, monkeypatch):
    client = VLMClient(tmp_path)
    def post(*a, **kw):
        raise requests.exceptions.ConnectionError("offline")
    monkeypatch.setattr(client.session, "post", post)
    with pytest.raises(LLMError):
        client.ask(stage="test", system="s", user_text="u")
    assert client.stats["calls"] == 1
    assert client.stats["seconds"] >= 0
    assert client.stats["attempts"][0]["status"] == "error"


def test_clip_cache_changes_with_source_bytes_and_crf(tmp_path, monkeypatch):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"v1")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "clips")
    def run(cmd):
        Path(cmd[-1]).write_bytes(b"clip")
        return type("Done", (), {"returncode": 0})()
    monkeypatch.setattr(media, "_run", run)
    first = media.make_clip(src, 0, 1)
    assert media.make_clip(src, 0, 1) == first
    src.write_bytes(b"v2")
    second = media.make_clip(src, 0, 1)
    assert second != first
    monkeypatch.setattr(config, "CLIP_CRF", config.CLIP_CRF + 1)
    assert media.make_clip(src, 0, 1) != second


def test_visible_arm_is_not_silently_lost_in_hand_transport():
    payload = {"atomic_actions": [action(1, "右手", "右手将蔬菜移出抽屉")]}
    with pytest.raises(ValueError, match="分别记录"):
        s02b_atomic._validate_upper_limb_coverage(payload, ["右手臂"])
    payload["atomic_actions"].append(action(2, "右臂", "右臂向后收回"))
    s02b_atomic._validate_upper_limb_coverage(payload, ["右手臂"])


def test_unseen_or_occluded_arm_does_not_force_invented_observations():
    payload = {"atomic_actions": [action(1, "右手", "右手将蔬菜移出抽屉")]}
    s02b_atomic._validate_upper_limb_coverage(payload, [])
    payload["missing_or_unclear"] = "右臂受到遮挡，无法确认运动"
    s02b_atomic._validate_upper_limb_coverage(payload, ["右臂"])


@pytest.mark.parametrize("text, expected", [
    ("整体向冰箱移动", "向目标移动"),
    ("整体下降至操作高度", "下降"),
    ("整体上升", "上升"),
])
def test_descriptive_overall_motion_is_normalized_without_llm_retry(text, expected):
    a = action(1, "整体", text, object="冰箱")
    s02b_atomic._validate({"atomic_actions": [a]})
    result = s02b_atomic._normalize_window({"atomic_actions": [a]}, 1)
    assert result["atomic_actions"][0]["action"] == expected
    assert result["atomic_actions"][0]["world_after"] == []


def test_unknown_movement_target_is_not_invented():
    a = action(1, "整体", "整体移动", object=None)
    result = s02b_atomic._normalize_window({"atomic_actions": [a]}, 1)
    assert result["atomic_actions"][0]["action"] == "移动"
    assert result["atomic_actions"][0]["object"] is None

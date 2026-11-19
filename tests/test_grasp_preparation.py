from copy import deepcopy

import pytest

from video2op import grasp_preparation as gp
from video2op import semantic
from video2op.single_video.pipeline import build_learning_graph
from video2op.single_video.stages.common import atomic_table


def grasp(before="", source="observed"):
    return {"id": 3, "executor": "右手", "action": "右手收拢抓握杯子",
            "mode": "transition", "object": "杯子", "start": 3, "end": 4,
            "state_before": before, "state_before_from": source,
            "state_after": "右手握持杯子", "world_before": [], "world_after": [],
            "inferred": False}


def prior(text, action="右手张开", i=1, end=1, inferred=False):
    return {"id": i, "executor": "右手", "action": action, "mode": "transition",
            "start": end - 1, "end": end, "state_after": text, "inferred": inferred}


def bundle(actions):
    return {"meta": {"name": "准备动作测试", "duration": 5},
            "atomic": {"atomic_actions": actions}, "relations": [],
            "task_nodes": {"task_nodes": [{
                "id": "n1", "name": "抓取", "intent_role": "建立稳定抓持",
                "required_capabilities": ["抓取"], "atomic_refs": [3], "time_range": [0, 4],
                "tuple": {"X": {"subject": "操作者", "parts": ["右臂", "右手"]},
                          "O": ["杯子"], "C_pre": ["杯子位于桌上"], "C_const": ["物体不滑落"],
                          "C_post": ["右手握持杯子"], "E": {"process": [], "completion": []}, "R": []}
            }]}}


def test_open_state_does_not_invent_opening_action():
    r = gp.inspect([grasp("右手手指张开，未接触杯子")])[0]
    assert r["status"] == "satisfied"
    assert "candidate_action" not in r


def test_closed_state_adds_inferred_preparation_without_fake_times_or_facts():
    a = grasp("右手紧握成拳")
    before = deepcopy(a)
    r = gp.inspect([a])[0]
    assert a == before
    assert r["status"] == "inferred_preparation"
    candidate = r["candidate_action"]
    assert candidate["action"] == "张开"
    assert candidate["inferred"]
    assert candidate["observed_time"] is None
    assert not {"start", "end", "state_before", "state_after"} & candidate.keys()
    assert candidate["must_complete_before_atomic_ref"] == 3
    assert candidate["atomic_capability"] == "OperateGripper"
    assert candidate["control_mode"] == "MODE_SET_WIDTH"


@pytest.mark.parametrize("source", ["rest_state", "inherit", "inherit_action"])
def test_filled_or_inherited_open_is_not_video_evidence(source):
    r = gp.inspect([grasp("右手张开", source)])[0]
    assert r["status"] == "unknown"
    assert r["state_evidence"] == []
    assert r["candidate_action"]["applicability"]


def test_empty_hand_is_not_proof_of_open_aperture():
    assert gp.inspect([grasp("右手是空的，没有握着物体")])[0]["status"] == "unknown"


def test_already_holding_object_does_not_infer_open_and_drop_it():
    r = gp.inspect([grasp("右手握持另一个杯子")])[0]
    assert r["status"] == "conflict"
    assert "candidate_action" not in r


def test_previous_opening_with_observed_effect_satisfies_precondition():
    r = gp.inspect([prior("右手已张开"), grasp()])[0]
    assert r["status"] == "satisfied"
    assert r["state_evidence"][0]["atomic_ref"] == 1


def test_old_open_state_invalidated_by_later_closure():
    r = gp.inspect([prior("右手已张开"),
                    prior("右手紧握成拳", "右手握拳", i=2, end=2), grasp()])[0]
    assert r["status"] == "inferred_preparation"


def test_inferred_opening_does_not_prove_observed_readiness():
    r = gp.inspect([prior("右手已张开", inferred=True), grasp()])[0]
    assert r["status"] == "unknown"


def test_left_hand_open_does_not_prepare_right_hand():
    left = prior("左手已张开")
    left["executor"] = "左手"
    assert gp.inspect([left, grasp()])[0]["status"] == "unknown"


def test_annotated_requirements_are_idempotent_and_do_not_add_actions():
    b = bundle([grasp("右手紧握成拳")])
    original_actions = len(b["atomic"]["atomic_actions"])
    gp.annotate(b)
    expected = deepcopy(b)
    gp.annotate(b)
    assert b == expected
    assert len(b["atomic"]["atomic_actions"]) == original_actions
    assert "inferred_preparation" in atomic_table(b["atomic"]["atomic_actions"])


def test_learning_graph_exports_preparation_and_shows_it_only_in_details(tmp_path):
    b = bundle([grasp("右手紧握成拳")])
    build_learning_graph(b)
    assert len(b["operations"]["nodes"]) == 3
    assert len(b["atomic"]["atomic_actions"]) == 1
    check = next(c for c in b["reasoning"]["checks"] if c["kind"] == "grasp_preparation")
    assert check["verdict"] == "inferred_preparation"
    nid = next(k for k, n in b["semantic_graph"]["nodes"].items() if n["name"] == "抓取")
    req = b["semantic_graph"]["evidence"][nid]["preparation_requirements"][0]
    assert req["candidate_action"]["inferred"]
    result = semantic.validate(b)
    assert next(c for c in result["checks"] if c["id"] == "grasp_preparation")["status"] == "warn"
    assert result["needs_review"]
    semantic.render(b, tmp_path)
    page = (tmp_path / "workbench.html").read_text()
    assert "抓握准备 · 因果校验" in page
    assert "本动作未被观察；不指定视频时间" in page
    assert 'data-id="step_1" hidden' in page
    assert "ArmGripperSystem" not in page

@pytest.mark.parametrize("state", ["右手半张开", "右手开度不足", "右手未充分张开"])
def test_insufficient_aperture_is_not_accepted_as_ready(state):
    r = gp.inspect([grasp(state)])[0]
    assert r["status"] == "inferred_preparation"
    assert r["candidate_action"]["inferred"]

import re
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from video2op import arm_hand, semantic
from video2op.pipeline import build_learning_graph
from video2op.stages import s02b_atomic


def action(i, executor, name, start, end, obj="杯子", after="", before="", inferred=False):
    return dict(id=i, executor=executor, action=name, mode="transition" if executor.endswith("手") else "motion",
                object=obj, start=start, end=end, state_before=before, state_after=after,
                world_before=[], world_after=[], inferred=inferred)


def example():
    actions = [
        action(1, "右臂", "右臂靠近杯子", 0, 1, after="右手已到达抓取位置"),
        action(2, "右手", "右手抓握杯子", 1, 2, after="右手握住杯子", before="右手已张开"),
        action(3, "右臂", "右臂抬起杯子", 2, 3),
        action(4, "右臂", "右臂移动杯子", 3, 4),
        action(5, "右臂", "右臂下降放下杯子", 4, 5, after="杯底接触桌面"),
        action(6, "右手", "右手释放杯子", 5, 6, after="手已张开"),
        action(7, "右臂", "右臂撤回", 6, 7),
    ]
    nodes = []
    for nid, name, refs, parts, times in [
        ("n1", "抓取", [1, 2, 3], ["右臂", "右手"], [0, 3]),
        ("n2", "搬运", [4], ["右臂"], [3, 4]),
        ("n3", "放置", [5, 6], ["右臂", "右手"], [4, 6]),
        ("n4", "撤回", [7], ["右臂"], [6, 7]),
    ]:
        nodes.append(dict(id=nid, name=name, atomic_refs=refs, time_range=times,
            intent_role="完成杯子取放", required_capabilities=[name],
            tuple={"X": {"subject": "操作者", "parts": parts}, "O": ["杯子"],
                   "C_pre": [], "C_post": [], "C_const": ["右手保持抓握杯子", "不碰撞"],
                   "E": {"process": [], "completion": []}, "R": []}))
    return {"meta": {"name": "分工测试", "duration": 7},
            "atomic": {"atomic_actions": actions}, "relations": [],
            "task_nodes": {"task_nodes": nodes}}


@pytest.mark.parametrize("executor,name", [
    ("右手", "右手靠近杯子"), ("左手", "左手搬运杯子"),
    ("右手", "右手抓紧杯子向左移动"), ("右臂", "右臂抓握杯子"),
])
def test_extraction_rejects_wrong_actor_functions(executor, name):
    a = action(1, executor, name, 0, 1)
    with pytest.raises(ValueError, match="手只负责"):
        s02b_atomic._validate({"atomic_actions": [a]})


def test_actual_arm_and_hand_functions_map_to_real_capabilities():
    b = example()
    arm_hand.annotate(b)
    actions = b["atomic"]["atomic_actions"]
    assert [a["functional_role"]["function"] for a in actions] == [
        "靠近", "抓握", "带载移动", "带载移动", "带载移动", "释放", "撤回"]
    assert actions[0]["functional_role"]["atomic_capability"] == "move_chain_client"
    assert actions[1]["functional_role"]["control_mode"] == "MODE_GRASP"
    assert actions[5]["functional_role"]["control_mode"] == "MODE_RELEASE"
    r = b["arm_hand_coordination"]["reach_requirements"][0]
    assert r["executor"] == "右臂" and r["hand"] == "右手"
    assert r["approach_ref"] == 1 and r["status"] == "satisfied"


def test_grip_scope_ends_at_release_start_not_table_contact_or_release_end():
    b = example()
    b["atomic"]["atomic_actions"][4]["end"] = 4.5  # table contact is earlier than release
    arm_hand.annotate(b)
    g = b["arm_hand_coordination"]["grip_intervals"][0]
    assert g["begin"]["demonstration_time"] == 2
    assert g["end"]["demonstration_time"] == 5
    assert g["interval_semantics"] == "[grasp_succeeded, release_starts)"
    assert g["continuous_state_status"] == "unverified"
    nodes = b["task_nodes"]["task_nodes"]
    assert all(n["scoped_grip_constraints"] for n in nodes[:3])
    assert not nodes[3]["scoped_grip_constraints"]
    assert g["constraint_text"] not in nodes[3]["tuple"]["C_const"]


def test_release_only_node_has_no_grip_requirement_during_opening():
    b = example()
    n = b["task_nodes"]["task_nodes"][2]
    n.update(name="释放", atomic_refs=[6], time_range=[5, 6])
    arm_hand.annotate(b)
    assert not n["scoped_grip_constraints"]
    assert n["tuple"]["C_const"] == ["不碰撞"]


def test_scoping_is_idempotent_and_preserves_original_constraints_for_review():
    b = example()
    arm_hand.annotate(b)
    expected = deepcopy(b)
    arm_hand.annotate(b)
    assert b == expected
    assert b["task_nodes"]["task_nodes"][0]["constraint_revisions"][0]["original"] == "右手保持抓握杯子"


def test_missing_approach_is_conditional_candidate_not_fake_video_action():
    b = example()
    b["atomic"]["atomic_actions"] = b["atomic"]["atomic_actions"][1:]
    before = len(b["atomic"]["atomic_actions"])
    arm_hand.annotate(b)
    r = b["arm_hand_coordination"]["reach_requirements"][0]
    assert r["status"] == "unknown"
    assert r["candidate_action"]["executor"] == "右臂"
    assert r["candidate_action"]["inferred"]
    assert r["candidate_action"]["observed_time"] is None
    assert len(b["atomic"]["atomic_actions"]) == before


def test_approach_motion_does_not_itself_prove_grasp_pose():
    b = example()
    b["atomic"]["atomic_actions"][0]["state_after"] = "右臂正在靠近杯子"
    arm_hand.annotate(b)
    assert b["arm_hand_coordination"]["reach_requirements"][0]["status"] == "approach_observed"


def test_no_release_does_not_invent_a_release_time():
    b = example()
    b["atomic"]["atomic_actions"] = [a for a in b["atomic"]["atomic_actions"] if a["id"] != 6]
    arm_hand.annotate(b)
    g = b["arm_hand_coordination"]["grip_intervals"][0]
    assert g["release_ref"] is None
    assert g["end"]["demonstration_time"] is None


@pytest.mark.parametrize("state,expected", [("杯子滑落", "violated"), ("杯子没有滑落", "unverified")])
def test_actual_grip_loss_is_not_confused_with_negative_safety_text(state, expected):
    b = example()
    b["atomic"]["atomic_actions"][3]["state_after"] = state
    arm_hand.annotate(b)
    assert b["arm_hand_coordination"]["grip_intervals"][0]["continuous_state_status"] == expected


def test_graph_has_no_visible_time_labels_but_retains_evidence_times(tmp_path):
    b = example()
    build_learning_graph(b)
    semantic.render(b, tmp_path)
    tree = ET.fromstring((tmp_path / "operations.svg").read_text())
    labels = [e.text or "" for e in tree.iter() if e.tag.endswith("}text")]
    assert not any(re.search(r"\d+(?:\.\d+)?(?:[–~\-]\d+(?:\.\d+)?)?s", t) for t in labels)
    assert not any("示范 " in t for t in labels)
    assert b["atomic"]["atomic_actions"][0]["start"] == 0
    graph = b["semantic_graph"]
    assert graph["evidence"]["N1"]["time_range"] == [0, 1]
    assert graph["evidence"]["N1"]["functional_roles"][0]["executor"] == "右臂"
    assert graph["evidence"]["N3"]["scoped_grip_constraints"][0]["end"]["atomic_ref"] == 6
    html = (tmp_path / "workbench.html").read_text()
    assert "臂手分工与握持约束" in html
    assert "释放动作开始前" in html
    assert 'data-id="step_1" hidden' in html
    assert "ArmGripperSystem" not in html

@pytest.mark.parametrize("state", ["右手不在可触范围", "右手尚未到达抓取位姿", "右手够不着杯子"])
def test_negative_reachability_is_not_mistaken_for_ready_pose(state):
    b = example()
    b["atomic"]["atomic_actions"][1]["state_before"] = state
    arm_hand.annotate(b)
    r = b["arm_hand_coordination"]["reach_requirements"][0]
    assert r["status"] != "satisfied"


def test_multiple_grasp_cycles_keep_each_scoped_constraint():
    b = example()
    extra = deepcopy(b["atomic"]["atomic_actions"])
    for a in extra:
        a["id"] += 10
        a["start"] += 8
        a["end"] += 8
    b["atomic"]["atomic_actions"].extend(extra)
    n = deepcopy(b["task_nodes"]["task_nodes"][0])
    n.update(id="n5", atomic_refs=[11, 12, 13], time_range=[8, 11])
    b["task_nodes"]["task_nodes"].append(n)
    arm_hand.annotate(b)
    first, last = b["task_nodes"]["task_nodes"][0], b["task_nodes"]["task_nodes"][-1]
    assert first["scoped_grip_constraints"][0]["grasp_ref"] == 2
    assert last["scoped_grip_constraints"][0]["grasp_ref"] == 12
    assert first["scoped_grip_constraints"][0]["constraint_text"] in first["tuple"]["C_const"]
    assert last["scoped_grip_constraints"][0]["constraint_text"] in last["tuple"]["C_const"]

def test_target_directed_motion_before_grasp_is_annotated_as_arm_approach():
    b = example()
    a = b["atomic"]["atomic_actions"][0]
    a["action"] = "右臂向杯子移动"
    arm_hand.annotate(b)
    assert a["action"] == "右臂向杯子移动"  # observation is not rewritten
    assert a["functional_role"]["function"] == "靠近"
    assert a["functional_role"]["atomic_capability"] == "move_chain_client"

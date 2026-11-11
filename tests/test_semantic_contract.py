"""Regression cases from the operation-graph review, independent of a model server."""
from copy import deepcopy
import pytest

from video2op import operations, program, reasoning
from video2op.pipeline import build_legacy_execution_graph as build_operation_graph
from video2op.stages import s02c_task, s02b_merge, s02b_atomic
from video2op.stages.common import atomic_table


def action(i, before=None, after=None, inferred=False, start=0, end=1):
    return dict(id=i, executor="左手", action="靠近目标", mode="motion",
                start=start, end=end, state_before=before, state_after=after,
                inferred=inferred)


def node(i, refs, pre=(), post=(), start=0, end=1, invariants=()):
    return dict(id=i, name="操作" + i, intent_role="为后续操作建立条件",
                required_capabilities=["操作目标"], atomic_refs=refs,
                time_range=[start, end], tuple={
                    "X": {"parts": ["左手"]}, "O": ["目标"],
                    "C_pre": list(pre), "C_post": list(post), "C_const": list(invariants)})


def build(nodes, actions):
    b = {"task_nodes": {"task_nodes": nodes}, "atomic": {"atomic_actions": actions}, "relations": []}
    build_operation_graph(b)
    return b


def test_capability_and_expected_effect_are_not_observation():
    b = build([node("a", [1], post=["目标已移开"]),
               node("b", [2], pre=["目标已移开"], start=1, end=2)],
              [action(1, after="靠近目标"), action(2, start=1, end=2)])
    e = b["operations"]["edges"][0]
    assert e["basis"] == "observed_order"
    assert b["operations"]["intent_chain"] == []
    assert b["operations"]["nodes"][0]["purpose"] == ""
    assert b["operations"]["stats"]["enables"] == 0
    assert b["reasoning"]["gaps"]


def test_later_effect_cannot_satisfy_earlier_precondition():
    b = build([node("a", [1], pre=["箱子已稳定支撑"]),
               node("b", [2], post=["箱子已稳定支撑"], start=2, end=3)],
              [action(1), action(2, after="箱子已稳定支撑", start=2, end=3)])
    assert any(g["node"] == "a" for g in b["reasoning"]["gaps"])


def test_first_precondition_is_not_assumed_true():
    b = build([node("a", [1], pre=["杯内装满水"])], [action(1)])
    assert b["program"]["operations"][0]["startable"] is False
    assert b["reasoning"]["gaps"]


def test_inferred_inherited_and_before_states_do_not_prove_success():
    for a in [action(1, after="门已打开", inferred=True),
              dict(action(1, after="门已打开"), state_after_from="inherit"),
              action(1, before="门已打开", after="门已关闭")]:
        b = build([node("a", [1], post=["门已打开"])], [a])
        assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "unverified"


def test_all_effects_require_evidence_and_polarity_matters():
    b = build([node("a", [1], post=["门已打开", "目标已取出"])],
              [action(1, after="门已打开")])
    ev = b["operations"]["nodes"][0]["effect_evidence"]
    assert [e["status"] for e in ev] == ["observed", "unverified"]
    b = build([node("a", [1], post=["门已打开"])], [action(1, after="门未打开")])
    assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "unverified"


def test_unrelated_hold_does_not_cover_grasp_and_invariants_survive():
    a = dict(action(1, after="站立支撑", end=4), mode="maintain")
    b = build([node("a", [1], end=4, invariants=["保持抓握杯子"])], [a])
    assert any(c["verdict"] == "uncovered" for c in b["reasoning"]["checks"])
    assert b["program"]["operations"][0]["invariants"] == ["保持抓握杯子"]


def test_supported_dependency_becomes_event_guard_not_live_start_permission():
    b = build([node("a", [1], post=["箱子已稳定抓持"]),
               node("b", [2], pre=["箱子已稳定抓持"], post=["箱子到达目标"], start=1, end=2)],
              [action(1, after="箱子已稳定抓持"), action(2, after="箱子到达目标", start=1, end=2)])
    r = b["program"]["operations"][1]
    assert r["start_guard"]["dependencies"][0]["event"]["ref"] == "a"
    assert r["startable"] is None
    assert r["command"]["binding"]["status"] == "unbound"
    original = deepcopy(b)
    build_operation_graph(b)
    assert b == original


def test_no_completion_fallback_to_video_clock():
    b = build([node("a", [1])], [action(1)])
    code = "\n".join(b["program"]["code"])
    assert "UNTIL （完成条件未知" in code
    assert "UNTIL （动作结束时刻" not in code
    assert b["program"]["time_basis"] == "demonstration_only"


def test_intermediate_success_followed_by_failure_is_not_completion():
    b = build([node("a", [1, 2], post=["稳定握持杯子"], end=2)],
              [action(1, after="稳定握持杯子"), action(2, after="杯子已滑落", start=1, end=2)])
    assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "unverified"


def test_inferred_hold_cannot_prove_invariant():
    b = build([node("a", [1], end=4, invariants=["保持抓握杯子"])],
              [dict(action(1, after="保持抓握杯子", end=4, inferred=True), mode="maintain")])
    assert any(c["verdict"] == "uncovered" for c in b["reasoning"]["checks"])


def test_parallel_does_not_mean_synchronized_endpoints():
    b = {"task_nodes": {"task_nodes": [node("a", [1], end=3), node("b", [2], start=1, end=2)]},
         "atomic": {"atomic_actions": [action(1, end=3), action(2, start=1, end=2)]},
         "relations": [{"from": 1, "to": 2, "relation": "parallel"}]}
    build_operation_graph(b)
    assert "不代表同时开始或结束" in "\n".join(b["program"]["code"])
    assert len(b["program"]["demonstration_graph"]["nodes"]) == 2


def test_ungrounded_paraphrase_is_candidate_not_proven_fact():
    b = build([node("a", [1], post=["左手稳定握持杯子"])],
              [action(1, after="左手抓着杯子")])
    assert b["program"]["operations"][0]["startable"] is False


def test_world_state_supports_object_effect_without_using_body_pose():
    a = dict(action(1, after="手臂抬起"), world_after=["纸箱已离开地面"])
    b = build([node("a", [1], post=["纸箱已离开地面"])], [a])
    assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "observed"
    assert any(e["state"] == "纸箱已离开地面" for e in b["operations"]["nodes"][0]["observed_effects"])


def test_window_merge_world_effect_uses_last_end_not_last_start():
    outer = dict(action(1, start=0, end=4), world_after=["纸箱位于货架上"])
    inner = dict(action(2, start=1, end=2), world_after=["纸箱仍在移动"])
    merged = s02b_merge._merge_two(outer, inner)
    assert merged["world_after"] == ["纸箱位于货架上"]


def test_inferred_world_states_cannot_prove_outcome():
    a = dict(action(1, inferred=True), world_after=["纸箱已离开地面"])
    b = build([node("a", [1], post=["纸箱已离开地面"])], [a])
    assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "unverified"


def test_atomic_leaf_rejects_multiple_executors():
    a = dict(action(1), executor="双手", world_before=[], world_after=[])
    with pytest.raises(ValueError, match="一个明确执行器"):
        s02b_atomic._validate({"atomic_actions": [a]})


def test_unsupported_overlapping_dependency_remains_overlap_not_sequence():
    b = {"task_nodes": {"task_nodes": [node("a", [1], post=["目标已移开"], end=3),
                                       node("b", [2], pre=["目标已移开"], start=1, end=2)]},
         "atomic": {"atomic_actions": [action(1, end=3), action(2, start=1, end=2)]},
         "relations": [{"from": 1, "to": 2, "relation": "enables"}]}
    build_operation_graph(b)
    edge = b["operations"]["edges"][0]
    assert edge["relation"] == "parallel" and edge["mutual"]
    assert edge["basis"] == "observed_overlap"
    assert not b["program"]["operations"][1]["start_guard"]["dependencies"]


def test_task_prompt_receives_intent_and_evidence_provenance():
    class Client:
        def ask(self, **kwargs):
            assert "清除遮挡以取物" in kwargs["user_text"]
            assert "inferred（待核实）" in kwargs["user_text"]
            assert "after=inherit" in kwargs["user_text"]
            return {"task_nodes": []}
    s02c_task.run(Client(), {"meta": {"duration": 2},
                           "intents": {"intents": [{"statement": "清除遮挡以取物"}]},
                           "atomic": {"atomic_actions": [dict(action(1, inferred=True), state_after_from="inherit")]}})

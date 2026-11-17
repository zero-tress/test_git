"""Model contract boundaries: preserve uncertainty, local trials and source identity."""
import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from video2op.case_graph import _svg_text_lines, _svg_text_width, export, learn, svg, validate


def fixture():
    bundle = {
        "pipeline": {"model": "qwen3.8-27b", "base_url": "http://127.0.0.1:8032"},
        "source_video_sha256": "abc123",
        "intents": {"intents": [{"id": "task", "statement": "取目标", "confidence": 0.7}]},
        "atomic": {"atomic_actions": [
            {"id": 1, "inferred": False, "start": 0, "end": 1},
            {"id": 2, "inferred": False, "start": 1, "end": 2},
            {"id": 3, "inferred": True, "start": 0, "end": 0},
        ]},
        "operations": {"nodes": [
            {"id": "step_1", "atomic_refs": [1], "name": "抓取"},
            {"id": "step_2", "atomic_refs": [2], "name": "抓取"},
            {"id": "step_3", "atomic_refs": [], "name": "打开", "already_satisfied": True},
        ]},
    }
    def node(i, outcome):
        return {"id": f"S{i}", "name": "抓取目标", "purpose": "取得目标", "expected_effects": ["目标被持有"],
                "status": "observed", "X": {"role": "执行者"}, "O": {"target": "笔"},
                "C_pre": ["目标可接近"], "C_const": [], "C_post": ["目标被持有"],
                "E": {"completion": ["持有目标"], "process_constraint": [], "implementation_applicability": [],
                      "binding_status": "unbound", "detector_ref": None, "controller_ref": None},
                "R": [{"id": f"S{i}_R1", "name": "抓取", "operation_refs": [f"step_{i}"],
                       "atomic_refs": [i], "status": "observed"}],
                "outcome": outcome, "evidence_refs": [i], "intent_refs": ["task"]}
    graph = {"schema_version": "case_graph.v1", "nodes": [node(1, "failure"), node(2, "success")],
             "relations": [{"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order",
                            "source_refs": [1, 2], "status": "observed"}],
             "task_outcome": {"value": "success", "evidence_refs": [2], "reason": "后一次尝试成功"},
             "condition_observations": [{"skill_id": "S1", "kind": "C_pre", "text": "目标可接近", "truth": "U",
                                          "phase": "pre", "outcome": "failure", "evidence_refs": []}],
             "unresolved": ["因果必要性未建立"]}
    return bundle, graph


def test_local_failure_survives_overall_success_and_export_keeps_originals(tmp_path):
    bundle, graph = fixture()
    bundle["case_graph"] = graph
    for name in ("operations.svg", "workbench.html"):
        (tmp_path / name).write_text("existing-original")
    export(bundle, tmp_path)
    result = json.loads((tmp_path / "G_case.json").read_text())
    assert result["task_outcome"]["value"] == "success"
    assert [n["outcome"] for n in result["nodes"]] == ["failure", "success"]
    assert all((tmp_path / name).read_text() == "existing-original" for name in ("operations.svg", "workbench.html"))
    ET.fromstring((tmp_path / "G_case.svg").read_text())


@pytest.mark.parametrize("change", ["inferred_evidence", "state_only_realization", "unknown_operation",
                                   "uncovered_atomic", "invented_controller", "wrong_local_outcome",
                                   "truth_without_evidence", "sequence_cycle", "unguarded_branch",
                                   "bad_join", "candidate_overlap_as_observed", "no_effect", "unknown_intent"])
def test_invalid_model_claims_fail_closed(change):
    bundle, graph = fixture()
    n = graph["nodes"][0]
    r = n["R"][0]
    if change == "inferred_evidence":
        n["evidence_refs"] = [3]
    elif change == "state_only_realization":
        r["operation_refs"].append("step_3")
    elif change == "unknown_operation":
        r["operation_refs"] = ["invented"]
    elif change == "uncovered_atomic":
        r["atomic_refs"] = [2]
    elif change == "invented_controller":
        n["E"]["controller_ref"] = "made-up-policy"
    elif change == "wrong_local_outcome":
        graph["condition_observations"][0]["outcome"] = "success"
    elif change == "truth_without_evidence":
        graph["condition_observations"][0]["truth"] = "T"
    elif change == "sequence_cycle":
        graph["relations"].append({**graph["relations"][0], "from": "S2", "to": "S1"})
    elif change == "unguarded_branch":
        graph["relations"][0]["relation"] = "branch"
    elif change == "bad_join":
        graph["relations"][0].update(relation="synchronization", join="all", members=["S1", "S2"])
    elif change == "candidate_overlap_as_observed":
        graph["relations"][0].update(relation="parallel", basis="candidate_parallelism")
    elif change == "no_effect":
        n["expected_effects"] = []
    elif change == "unknown_intent":
        n["intent_refs"] = ["invented"]
    with pytest.raises(ValueError):
        validate(graph, bundle)


def test_nonexecution_is_censored_and_has_no_observed_realization():
    bundle, graph = fixture()
    n = graph["nodes"][0]
    n.update(status="not_executed", outcome="not_executed", evidence_refs=[], R=[])
    graph["condition_observations"] = []
    assert validate(graph, bundle)["structure_valid"]
    n["outcome"] = "failure"
    with pytest.raises(ValueError):
        validate(graph, bundle)


def test_legacy_observation_independence_is_explicit_and_model_semantics_are_unchanged():
    bundle, graph = fixture()
    class Client:
        model = "qwen3.8-27b"
        base_url = "http://127.0.0.1:8032"
        def ask(self, **kwargs):
            assert kwargs["stage"] == "s09_case_graph"
            kwargs["validator"](graph)
            return deepcopy(graph)
    result = learn(Client(), bundle)
    assert result["nodes"] == graph["nodes"]
    assert result["provenance"]["observation_independence"] == "legacy_not_established"
    assert result["intent_hypotheses"] == bundle["intents"]["intents"]
    bundle["observed_operation_graph"] = {"nodes": bundle["atomic"]["atomic_actions"][:2]}
    assert learn(Client(), bundle)["provenance"]["observation_independence"] == "frozen_pre_sync"
    bundle["pipeline"]["base_url"] = "http://127.0.0.1:8033"
    with pytest.raises(ValueError, match="authorized"):
        learn(Client(), bundle)


def test_empty_graph_keeps_unknown_and_visible_gap():
    bundle, _ = fixture()
    graph = {"schema_version": "case_graph.v1", "nodes": [], "relations": [], "condition_observations": [],
             "unresolved": ["不可见"], "task_outcome": {"value": "unknown", "evidence_refs": []}}
    assert validate(graph, bundle)["causal_status"] == "not_established"
    ET.fromstring(svg(graph))


def test_cjk_card_text_fits_pixel_budget_and_truncation_has_full_tooltip():
    _, graph = fixture()
    full = "观察清障前后目标物体的可接近状态与遮挡关系" * 7
    graph["nodes"][0]["purpose"] = full
    lines = _svg_text_lines(full + " mixed ASCII label", 16, 270)
    assert len(lines) > 2
    assert all(_svg_text_width(line, 16) <= 270 for line in lines)
    assert len(lines[0]) <= 16
    rendered = ET.fromstring(svg(graph))
    namespace = {"s": "http://www.w3.org/2000/svg"}
    assert full in [title.text for title in rendered.findall(".//s:title", namespace)]
    assert any("…" in (text.text or "") for text in rendered.findall(".//s:text", namespace))


def test_gcase_svg_uses_operations_style_with_visible_seven_tuple():
    _, graph = fixture()
    rendered = svg(graph, name="样例视频")
    # 圆形技能节点与前置条件门控，沿用 operations.svg 的图形语言
    assert 'class="gs-node"' in rendered and 'class="gs-gate"' in rendered
    assert "门控 ①" in rendered
    # 每个节点的七元组在面板上直接可读，不只藏在悬停详情里
    for label in ("目的", "X", "O", "C_pre", "C_const", "E 完成", "E 过程", "E 适用", "C_post", "R S1_R1"):
        assert label in rendered
    assert "角色：执行者" in rendered and "目标：笔" in rendered
    # 节点标题保留完整七元组，供悬停核对
    titles = [node.find("{http://www.w3.org/2000/svg}title").text for node in
              ET.fromstring(rendered).findall(".//{http://www.w3.org/2000/svg}g[@class='gs-node']")]
    assert any("C_pre 进入条件：目标可接近" in title and "E 完成：持有目标" in title for title in titles)

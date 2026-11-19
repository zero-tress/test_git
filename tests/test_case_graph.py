"""Model contract boundaries: preserve uncertainty, local trials and source identity."""
import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from video2op.single_video.case_graph import export, learn, svg, validate
from video2op.presentation.case_graph_render import _svg_text_lines, _svg_text_width
from video2op.presentation.case_graph_render import _operation_flow as case_graph_flow


def scope_stub(request, scope="goal"):
    operations = json.loads(request["user_text"])["observed_operations"]
    result = {"groups": [{"operation_refs": [op["id"]], "scope": scope,
                          "reason": "Synthetic scope test", "downstream_refs": []} for op in operations]}
    request["validator"](result)
    return result


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
    # 未执行尝试仍必须交代其动作归属，不能从实现里消失而不说明。
    with pytest.raises(ValueError, match="missing from every skill realization"):
        validate(graph, bundle)
    graph["excluded_operations"] = [{"operation_ref": "step_1", "reason": "该动作属于未执行的局部尝试"}]
    assert validate(graph, bundle)["structure_valid"]
    n["outcome"] = "failure"
    with pytest.raises(ValueError):
        validate(graph, bundle)


def test_legacy_observation_independence_is_explicit_and_model_semantics_are_unchanged():
    bundle, graph = fixture()
    graph["contract_version"] = "video_learning.logic.v2"
    for node in graph["nodes"]:
        node.update(attempt_id=node["id"], actual_postconditions=["synthetic observed result"])
        for r in node["R"]:
            r.update(completeness="complete", effect_evidence_refs=r["atomic_refs"])
    class Client:
        model = "qwen3.8-27b"
        base_url = "http://127.0.0.1:8032"
        def ask(self, **kwargs):
            if kwargs["stage"] == "s09_scope_roles":
                return scope_stub(kwargs)
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


def ordered_fixture():
    """Three skills over five observed steps, with one internal parallel and one hold."""
    bundle = {
        "pipeline": {"model": "qwen3.8-27b", "base_url": "http://127.0.0.1:8032"},
        "source_video_sha256": "abc123",
        "intents": {"intents": [{"id": "task", "statement": "取目标", "confidence": 0.7}]},
        "atomic": {"atomic_actions": [
            {"id": i, "inferred": False, "start": i - 1, "end": i} for i in range(1, 6)
        ]},
        "operations": {
            "nodes": [
                {"id": "step_1", "name": "靠近", "atomic_refs": [1]},
                {"id": "step_2", "name": "抓取", "atomic_refs": [2]},
                {"id": "step_3", "name": "移动", "atomic_refs": [3]},
                {"id": "step_4", "name": "释放", "atomic_refs": [4]},
                {"id": "step_5", "name": "打开", "atomic_refs": [5]},
            ],
            "edges": [
                {"from": "step_1", "to": "step_2", "relation": "sequence"},
                {"from": "step_2", "to": "step_3", "relation": "sequence"},
                {"from": "step_3", "to": "step_4", "relation": "sequence"},
                {"from": "step_1", "to": "step_5", "relation": "parallel"},
                {"from": "step_2", "to": "step_4", "relation": "maintain_until"},
            ],
        },
    }

    def node(sid, name, ops, atoms):
        return {"id": sid, "name": name, "purpose": f"{name}的目的",
                "expected_effects": ["效果"], "status": "observed",
                "X": {"role": "左手"}, "O": {"target": "笔"},
                "C_pre": [], "C_const": [], "C_post": ["效果"],
                "E": {"completion": [], "process_constraint": [],
                      "implementation_applicability": ["适用"], "binding_status": "unbound",
                      "detector_ref": None, "controller_ref": None},
                "R": [{"id": f"R_{sid}", "name": f"{name}实现", "operation_refs": ops,
                       "atomic_refs": atoms, "status": "observed"}],
                "outcome": "success", "evidence_refs": atoms, "intent_refs": ["task"]}

    graph = {"schema_version": "case_graph.v1",
             "nodes": [node("S1", "靠近", ["step_1", "step_5"], [1, 5]),
                       node("S2", "持笔", ["step_2", "step_3"], [2, 3]),
                       node("S3", "释放", ["step_4"], [4])],
             "relations": [
                 {"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order",
                  "source_refs": [1, 2], "status": "observed", "reason": "先靠近后抓取"},
                 {"from": "S2", "to": "S3", "relation": "sequence", "basis": "observed_order",
                  "source_refs": [2, 4], "status": "observed", "reason": "抓取后释放"},
                 {"from": "S2", "to": "S3", "relation": "maintain_until", "basis": "observed_order",
                  "source_refs": [2, 4], "status": "observed", "reason": "握持保持到释放开始"},
             ],
             "task_outcome": {"value": "success", "evidence_refs": [2, 3, 4], "reason": "目标被取走"},
             "condition_observations": [], "unresolved": []}
    return bundle, graph


def test_operation_relations_cannot_be_silently_dropped():
    bundle, graph = ordered_fixture()
    graph["relations"] = [row for row in graph["relations"] if row["relation"] != "maintain_until"]
    with pytest.raises(ValueError, match="maintain_until"):
        validate(graph, bundle)


def test_unmapped_relation_needs_a_reason_and_is_then_accepted():
    bundle, graph = ordered_fixture()
    graph["relations"] = [row for row in graph["relations"] if row["relation"] != "maintain_until"]
    graph["unmapped_relations"] = [{"operation_from": "step_2", "operation_to": "step_4",
                                    "relation": "maintain_until"}]
    with pytest.raises(ValueError, match="unmapped operation relation"):
        validate(graph, bundle)
    graph["unmapped_relations"][0]["reason"] = "握持属于该实现内部约束，已在 C_const 记录"
    assert validate(graph, bundle)["structure_valid"]


def test_internal_parallel_is_kept_without_forcing_a_skill_relation():
    bundle, graph = ordered_fixture()
    result = validate(graph, bundle)
    assert result["structure_valid"]
    assert any(row["relation"] == "maintain_until" for row in result["mapped_operation_relations"])


def test_maintain_until_is_a_hold_not_a_precedence_cycle():
    bundle, graph = ordered_fixture()
    graph["relations"].append({"from": "S3", "to": "S2", "relation": "maintain_until",
                               "basis": "observed_order", "source_refs": [2, 4],
                               "status": "observed", "reason": "反向保持不构成前置环"})
    assert validate(graph, bundle)["structure_valid"]
    graph["relations"][2]["reason"] = ""
    with pytest.raises(ValueError, match="maintain_until"):
        validate(graph, bundle)


def test_observed_operation_must_be_traced_or_excluded():
    bundle, graph = ordered_fixture()
    graph["nodes"][2]["R"] = []
    graph["nodes"][2].update(status="not_executed", outcome="not_executed", evidence_refs=[])
    graph["relations"] = [row for row in graph["relations"] if "S3" not in (row["from"], row["to"])]
    graph["task_outcome"]["evidence_refs"] = [2, 3]
    with pytest.raises(ValueError, match="missing from every skill realization"):
        validate(graph, bundle)
    graph["excluded_operations"] = [{"operation_ref": "step_4", "reason": "释放未被观察到"}]
    assert validate(graph, bundle)["structure_valid"] is True


def test_svg_shows_operation_subgraph_with_hold_and_parallel_marks():
    bundle, graph = ordered_fixture()
    rendered = svg(graph, name="样例", operations=bundle["operations"])
    ET.fromstring(rendered)
    assert "实现子图" in rendered
    assert 'class="gs-hold"' in rendered
    assert 'class="gs-op"' in rendered
    # 图上不再出现“保持”字样：持续关系只用线与悬停说明表达
    assert "保持" not in rendered


def test_flow_layers_follow_global_sequence_not_just_skill_members():
    """隔着被排除步骤的两个操作不能因为缺直接边就被误画成并行。"""
    bundle, graph = ordered_fixture()
    bundle["operations"]["nodes"].append({"id": "step_6", "name": "中继", "atomic_refs": [],
                                          "already_satisfied": True})
    bundle["operations"]["edges"].extend([
        {"from": "step_3", "to": "step_6", "relation": "sequence"},
        {"from": "step_6", "to": "step_4", "relation": "sequence"},
    ])
    graph["excluded_operations"] = [{"operation_ref": "step_6", "reason": "状态已满足的中继步骤"}]
    assert validate(graph, bundle)["structure_valid"]
    node = graph["nodes"][1]
    _, _, _, columns = case_graph_flow(node, bundle["operations"])
    assert [refs for _, refs in sorted(columns.items())] == [["step_2"], ["step_3"]]


def test_hold_lane_and_parallel_marks_are_rendered():
    bundle, graph = ordered_fixture()
    rendered = svg(graph, name="样例", operations=bundle["operations"])
    ET.fromstring(rendered)
    assert "保持" not in rendered
    assert "gs-hold" in rendered
    assert "∥" in rendered or "平行" in rendered
    assert "经未显示的中间步骤" in rendered or "step_2" in rendered


def test_rule_only_skill_is_candidate_and_never_counts_as_observation():
    bundle, graph = fixture()
    rule = deepcopy(graph["nodes"][0])
    rule.update(id="S0", name="靠近目标", status="candidate", outcome="unknown",
                evidence_refs=[], occurrence="rule_only", R=[],
                reason="入口政策要求且执行器确有接近移动；模型未识别到独立原子动作段，未计为已观察")
    graph["nodes"].insert(0, rule)
    graph["relations"].insert(0, {"from": "S0", "to": "S1", "relation": "sequence",
                                  "basis": "declared_rule", "source_refs": [], "status": "candidate",
                                  "reason": "入口政策要求的初始靠近"})
    result = validate(graph, bundle)
    assert result["rule_only_skills"] == ["S0"]
    rendered = svg(graph, name="样例")
    assert "规则补充 · 未直接观察" in rendered


def test_rule_only_skill_cannot_borrow_evidence_or_claim_success():
    bundle, graph = fixture()
    rule = deepcopy(graph["nodes"][0])
    rule.update(id="S0", name="靠近目标", status="candidate", outcome="unknown",
                evidence_refs=[], occurrence="rule_only", R=[],
                reason="入口政策要求但模型未识别到独立原子动作段")
    graph["nodes"].insert(0, rule)
    graph["relations"].insert(0, {"from": "S0", "to": "S1", "relation": "sequence",
                                  "basis": "declared_rule", "source_refs": [], "status": "candidate",
                                  "reason": "入口政策要求的初始靠近"})
    for change in ("evidence", "observed_relation", "success"):
        bad = deepcopy(graph)
        if change == "evidence":
            bad["nodes"][0]["evidence_refs"] = [1]
        elif change == "observed_relation":
            bad["relations"][0].update(basis="observed_order", status="observed", source_refs=[1])
        else:
            bad["nodes"][0].update(status="observed", outcome="success")
        with pytest.raises(ValueError, match="rule-only"):
            validate(bad, bundle)


def test_gcase_svg_is_a_start_to_end_flow_with_gates():
    _, graph = fixture()
    rendered = svg(graph, name="样例")
    ET.fromstring(rendered)
    assert "开始" in rendered and "结束" in rendered
    assert 'class="gs-node"' in rendered and 'class="gs-gate"' in rendered
    assert "门控 ①" in rendered
    # 开始/结束固定画在链路两端，而不是只画技能集合
    assert rendered.count('data-skill="__start__"') == 1
    assert rendered.count('data-skill="__end__"') == 1


def policy_fixture():
    """抓取1 形态：开始 → 靠近(规则补充) → 清障 → 靠近(观察) → 抓取 → 搬运。"""
    bundle = {
        "pipeline": {"model": "qwen3.8-27b", "base_url": "http://127.0.0.1:8032"},
        "source_video_sha256": "abc123",
        "intents": {"intents": [{"id": "task", "statement": "取目标", "confidence": 0.7}]},
        "atomic": {"atomic_actions": [
            {"id": i, "inferred": False, "start": i - 1, "end": i} for i in range(1, 6)
        ]},
        "operations": {
            "nodes": [
                {"id": "step_1", "name": "靠近玻璃杯", "atomic_refs": [1]},
                {"id": "step_2", "name": "抓取玻璃杯", "atomic_refs": [2]},
                {"id": "step_3", "name": "移动玻璃杯", "atomic_refs": [3]},
                {"id": "step_4", "name": "放开玻璃杯", "atomic_refs": [4]},
                {"id": "step_5", "name": "靠近红笔", "atomic_refs": [5]},
            ],
            "edges": [
                {"from": "step_1", "to": "step_2", "relation": "sequence"},
                {"from": "step_2", "to": "step_3", "relation": "sequence"},
                {"from": "step_3", "to": "step_4", "relation": "sequence"},
            ],
        },
    }

    def node(sid, name, role, atoms):
        ops = [f"step_{a}" for a in atoms]
        return {"id": sid, "name": name, "role": role, "purpose": f"{name}的目的",
                "expected_effects": ["效果"], "status": "observed", "occurrence": "observed",
                "X": {"role": "左手"}, "O": {"target": "红笔"},
                "C_pre": ["进入条件"], "C_const": [], "C_post": ["效果"],
                "E": {"completion": ["完成"], "process_constraint": [],
                      "implementation_applicability": ["适用"], "binding_status": "unbound",
                      "detector_ref": None, "controller_ref": None},
                "R": [{"id": f"R_{sid}", "name": f"{name}实现", "operation_refs": ops,
                       "atomic_refs": atoms, "status": "observed"}],
                "outcome": "success", "evidence_refs": atoms, "intent_refs": ["task"]}

    clearance = node("S2", "清障", "clearance", [1, 2, 3, 4])
    approach2 = node("S3", "靠近", "approach", [5])
    # Target trials occur after reapproach; do not borrow obstacle actions 2/3.
    bundle["atomic"]["atomic_actions"].extend(
        {"id": i, "inferred": False, "start": i - 1, "end": i} for i in (6, 7))
    bundle["operations"]["nodes"].extend([
        {"id": "step_6", "name": "抓取红笔", "atomic_refs": [6]},
        {"id": "step_7", "name": "搬运红笔", "atomic_refs": [7]}])
    grasp = node("S4", "抓取", "grasp", [6])
    transport = node("S5", "搬运", "transport", [7])
    rule = {**node("S1", "靠近", "approach", []), "status": "candidate", "outcome": "unknown",
            "evidence_refs": [], "occurrence": "rule_only", "R": [], "C_pre": [],
            "reason": "执行器确有接近移动，但模型未识别到独立原子动作段；未计为已观察"}
    graph = {"schema_version": "case_graph.v1",
             "nodes": [rule, clearance, approach2, grasp, transport],
             "relations": [
                 {"from": "S1", "to": "S2", "relation": "sequence", "basis": "declared_rule",
                  "source_refs": [], "status": "candidate", "reason": "起点后的第一步清障"},
                 {"from": "S2", "to": "S3", "relation": "sequence", "basis": "observed_order",
                  "source_refs": [4, 5], "status": "observed", "reason": "清障后再次靠近"},
                 {"from": "S3", "to": "S4", "relation": "sequence", "basis": "observed_order",
                   "source_refs": [5, 6], "status": "observed", "reason": "靠近后抓取"},
                 {"from": "S4", "to": "S5", "relation": "sequence", "basis": "observed_order",
                   "source_refs": [6, 7], "status": "observed", "reason": "抓取后搬运"},
             ],
              "task_outcome": {"value": "success", "evidence_refs": [6, 7], "reason": "目标被取走"},
             "condition_observations": [], "unresolved": []}
    return bundle, graph


def test_single_video_policy_requires_a_linear_chain():
    bundle, graph = policy_fixture()
    requirements = {"single_video": {"chain": "linear", "start_role": "approach",
                                     "add_approach_when_unobserved": True},
                    "task_policy": {"forbidden_roles": ["release", "place"]}}
    assert validate(graph, bundle, requirements)["rule_only_skills"] == ["S1"]
    # 单视频不画条件分支
    bad = deepcopy(graph)
    bad["relations"][0].update(relation="branch", guard="条件", guard_truth="U", gate_outcome="F")
    with pytest.raises(ValueError, match="单个视频只画一条链"):
        validate(bad, bundle, requirements)
    # 起点必须是靠近
    bad = deepcopy(graph)
    bad["relations"] = [r for r in bad["relations"] if r["from"] != "S1"]
    with pytest.raises(ValueError, match="第一个技能应为|起点"):
        validate(bad, bundle, requirements)
    # 释放/放置超出任务范围
    bad = deepcopy(graph)
    release = deepcopy(bad["nodes"][-1])
    release.update(id="S6", name="释放", role="release", evidence_refs=[8])
    release["R"] = [{"id": "R_S6", "name": "释放实现", "operation_refs": ["step_8"], "atomic_refs": [8], "status": "observed"}]
    bundle["atomic"]["atomic_actions"].append({"id": 8, "start": 7, "end": 8})
    bundle["operations"]["nodes"].append({"id": "step_8", "name": "释放红笔", "atomic_refs": [8]})
    bad["nodes"].append(release)
    bad["relations"].append({"from": "S5", "to": "S6", "relation": "sequence",
                             "basis": "observed_order", "source_refs": [7, 8],
                             "status": "observed", "reason": "任务后放开"})
    with pytest.raises(ValueError, match="任务范围 policy 禁止"):
        validate(bad, bundle, requirements)


def test_gcase_renders_gate_to_clearance_only_in_a_single_video():
    bundle, graph = policy_fixture()
    template = svg(graph, name="抓取1", operations=bundle["operations"])
    import re
    edges = re.findall(r'data-from="([^"]+)" data-to="([^"]+)"', template)
    gate_to = {b for a, b in edges if a.startswith("__gate_")}
    # 单视频：每个门控只有一条出边，且不去抓取之外凭空分支
    assert len([a for a, _ in edges if a.startswith("__gate_")]) == len(gate_to)
    assert "抓取" in template

import json
from copy import deepcopy

import jsonschema
import pytest
import yaml

from video2op import semantic
from video2op.pipeline import build_learning_graph
from video2op.stages import s02b_atomic, s02d_link
from video2op.stages.common import load_prompt


def fixture():
    actors = [
        ("右臂", "右臂靠近杯子", "右臂在桌旁", "右手已到达抓取位置"),
        ("右手", "右手抓握杯子", "右手已张开", "右手稳定握住杯子"),
        ("右臂", "右臂移动杯子", "右手稳定握住杯子", "杯子已到达目标桌面"),
        ("右手", "右手释放杯子", "右手握住杯子", "杯子在桌面，右手已松开"),
        ("右臂", "右臂撤回", "右臂在桌旁", "右臂返回原位"),
    ]
    actions = [dict(id=i, executor=ex, action=name,
                    mode="transition" if ex.endswith("手") else "motion",
                    object="杯子", start=i-1, end=i, state_before=before,
                    state_after=after, world_before=[before], world_after=[after], inferred=False)
               for i, (ex, name, before, after) in enumerate(actors, 1)]
    nodes = []
    for i, (name, refs, parts) in enumerate([
        ("抓取", [1, 2], ["右臂", "右手"]), ("搬运", [3], ["右臂"]),
        ("放置", [4], ["右手"]), ("撤回", [5], ["右臂"])], 1):
        nodes.append(dict(id=f"n{i}", name=name, intent_role="完成取放任务",
            required_capabilities=[name], atomic_refs=refs, time_range=[refs[0]-1, refs[-1]],
            tuple={"X": {"subject": "操作者", "parts": parts}, "O": ["杯子"],
                   "C_pre": [], "C_post": [], "C_const": ["物体不得滑落"],
                   "E": {"process": [], "completion": []}, "R": []}))
    return {"meta": {"name": "取放测试", "duration": 5}, "atomic": {"atomic_actions": actions},
            "task_nodes": {"task_nodes": nodes}, "relations": [],
            "intents": {"intents": [{"statement": "把杯子搬到台面"}]}}


@pytest.mark.parametrize("name", ["捡起", "抬起", "举起", "拿起", "抓握", "抓取目标"])
def test_grasp_aliases(name):
    assert semantic.canonical(name) == "抓取"


def test_closed_vocabulary_rejects_unknown_and_hold():
    for name in ("保持抓握", "maintain", "神奇移动", "先抓取再烧水"):
        with pytest.raises(ValueError):
            semantic.canonical(name)
    assert semantic.canonical("上升") == "上升"


def test_final_graph_matches_project_actor_schema_and_preserves_evidence(tmp_path):
    b = fixture()
    build_learning_graph(b)
    graph = b["semantic_graph"]
    schema = yaml.safe_load(semantic.SCHEMA.read_text())
    jsonschema.validate(graph, schema)
    assert semantic.validate(b)["passed"]
    assert [n["name"] for k, n in graph["nodes"].items() if k not in ("START", "END")] == ["靠近", "打开", "抓取", "移动", "释放", "撤回"]
    assert graph["nodes"]["N1"]["skill"]["X"] == {"subject": "右臂", "parts": ["右臂"]}
    assert graph["evidence"]["N1"]["demonstration_executor"] == ["右臂"]
    assert graph["evidence"]["N1"]["source_node_ids"] == ["n1"]
    for n in graph["nodes"].values():
        assert not ({"mode", "dependencies", "implementation", "params"} & n.keys())
        assert not any(r.get("preferred") for r in n["skill"]["R"])
    semantic.export(b, tmp_path)
    semantic.render(b, tmp_path)
    assert not (tmp_path / "execution_policy.yaml").exists()
    assert not (tmp_path / "program.json").exists()
    assert 'class="gs-node' in (tmp_path / "operations.svg").read_text()
    assert "C_pre 前置条件" not in (tmp_path / "operations.svg").read_text()
    page = (tmp_path / "workbench.html").read_text()
    assert 'data-id="step_1" hidden' in page
    assert "点击操作节点展开七元组" in page
    assert "selectNode(id)" in page
    assert "ArmGripperSystem" not in page
    assert "Grasp" not in json.dumps(graph["predicates"], ensure_ascii=False)  # original conditions, no invented success
    assert not any(k in b for k in ("program", "contract", "execution_policy", "expansion"))


def test_hold_migration_moves_to_constraints_and_cleans_references_idempotently():
    b = fixture()
    hold = dict(id=9, executor="右手", action="保持抓握杯子", object="杯子",
                mode="maintain", start=0, end=3, inferred=True)
    b["atomic"]["atomic_actions"].append(hold)
    b["task_nodes"]["task_nodes"][0]["atomic_refs"].append(9)
    b["relations"].append({"from": 9, "to": 3, "relation": "maintain_until"})
    build_learning_graph(b)
    assert any(r["original"] == "保持抓握杯子" for n in b["task_nodes_source"]["task_nodes"] for r in n.get("constraint_revisions") or [])
    assert b["atomic"]["state_evidence"] == [hold]
    assert all(a["mode"] != "maintain" for a in b["atomic"]["atomic_actions"])
    assert len(b["operations"]["nodes"]) == 6
    first = deepcopy(b["semantic_graph"])
    build_learning_graph(b)
    assert b["semantic_graph"] == first
    assert b["atomic"]["state_evidence"] == [hold]


def test_model_cannot_produce_or_infer_hold_actions():
    a = fixture()["atomic"]["atomic_actions"][0]
    a.update(mode="maintain", action="保持抓握")
    with pytest.raises(ValueError):
        s02b_atomic._validate({"atomic_actions": [a]})
    with pytest.raises(ValueError):
        s02d_link._validate({"links": [], "missing_actions": [a]})


def test_semantic_functions_do_not_require_robot_template_binding():
    b = fixture()
    build_learning_graph(b)
    assert not b["semantic_graph"]["x-meta"]["capability_gaps"]
    for n in b["semantic_graph"]["nodes"].values():
        assert n["skill"]["R"]
        assert "PlannedMove" not in json.dumps(n)
        assert not any(r.get("preferred") for r in n["skill"]["R"])


def test_task_effect_is_not_success_evidence():
    b = fixture()
    a = b["atomic"]["atomic_actions"][0]
    a["world_after"], a["state_after"] = ["杯子滑落"], "杯子滑落"
    build_learning_graph(b)
    assert b["operations"]["nodes"][0]["effect_evidence"][0]["status"] == "unverified"
    assert b["semantic_graph"]["nodes"]["N1"]["skill"]["C_post"]


def test_all_model_prompts_receive_same_closed_catalog():
    for stage in ("s02b_atomic", "s02c_task", "s02d_link", "s03_sync", "s04_conditions", "s05_rules"):
        prompt = load_prompt(stage)
        assert "单执行主体语义图 v4" in prompt
        assert "禁止保持动作节点" in prompt

def test_semantic_audit_never_requests_hold_action_completion():
    b = fixture()
    b["task_nodes"]["task_nodes"][1]["tuple"]["C_const"] = ["全程保持抓握杯子"]
    build_learning_graph(b)
    checks = b["reasoning"]["checks"]
    assert any(c["kind"] == "grip_scope" for c in checks)
    assert not any(c["kind"] == "hold" for c in checks)
    assert "补一条保持动作" not in json.dumps(b["reasoning"], ensure_ascii=False)


def test_state_evidence_survives_pre_task_normalization():
    b = fixture()
    hold = dict(id=9, executor="右手", action="保持抓握杯子", object="杯子",
                mode="maintain", start=0, end=3, inferred=True)
    b["atomic"]["atomic_actions"].append(hold)
    tasks = b.pop("task_nodes")
    semantic.normalize_observations(b)
    b["task_nodes"] = tasks
    build_learning_graph(b)
    assert b["atomic"]["state_evidence"] == [hold]


def test_public_operation_builder_delivers_semantic_layer():
    from video2op.pipeline import build_operation_graph
    b = fixture()
    build_operation_graph(b)
    assert b["learning_layer"] == "semantic"
    assert "semantic_graph" in b
    assert "program" not in b

@pytest.mark.parametrize("name", ["调整操作位置", "整体前倾调整位置", "整体抓取物体", "整体保持抓握"])
def test_overall_actor_rejects_posture_grasp_and_hold(name):
    a = fixture()["atomic"]["atomic_actions"][0]
    a.update(executor="整体", action=name, mode="motion")
    with pytest.raises(ValueError):
        s02b_atomic._validate({"atomic_actions": [a]})


@pytest.mark.parametrize("name", ["上升", "下降", "向目标移动", "移动"])
def test_overall_actor_preserves_vertical_and_horizontal_translation(name):
    a = fixture()["atomic"]["atomic_actions"][0]
    a.update(executor="整体", action=name, mode="motion", object=None if name == "移动" else "工作台")
    s02b_atomic._validate({"atomic_actions": [a]})
    out = s02b_atomic._normalize_window({"atomic_actions": [a]}, 1)
    assert out["atomic_actions"][0]["executor"] == "整体"
    assert out["atomic_actions"][0]["action"] == name


def test_task_cannot_assign_arm_operation_to_overall_actor():
    b = fixture()
    b["task_nodes"]["task_nodes"][0]["tuple"]["X"]["parts"] = ["整体"]
    with pytest.raises(ValueError, match="整体"):
        build_learning_graph(b)


def test_render_uses_original_geometry_and_hidden_tuple_sections(tmp_path):
    import xml.etree.ElementTree as ET

    from video2op import render, workbench
    b = fixture()
    build_learning_graph(b)
    semantic.render(b, tmp_path)
    actual = (tmp_path / "operations.svg").read_text()
    expected = render.gate_svg(b, show_node_details=False)
    assert actual == expected.replace('<svg ', '<svg style="background:#fff" ', 1)
    ET.fromstring(actual)
    data = workbench.build(tmp_path, bundle=b)
    for node in data["nodes"]:
        assert node["tuple"]["X"]["parts"] == [node["tuple"]["X"]["subject"]]
    html = (tmp_path / "workbench.html").read_text()
    assert html.count('class="detail" data-id=') == 6
    assert "七元组 Si" in html
    assert "子操作展开（执行单元）" not in html
    assert "执行层对接" not in html

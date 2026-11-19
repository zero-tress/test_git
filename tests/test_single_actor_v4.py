import re
import xml.etree.ElementTree as ET
from copy import deepcopy

import jsonschema
import pytest
import yaml
from test_arm_hand_scope import action, example

from video2op import semantic
from video2op.single_video.pipeline import build_learning_graph
from video2op.single_video.stages import s02c_task


def graph():
    b = example()
    build_learning_graph(b)
    return b


def by_name(b, name):
    return next(n for n in b["task_nodes"]["task_nodes"] if n["name"] == name)


def test_six_nodes_each_have_exactly_one_subject():
    b = graph()
    assert [n["name"] for n in b["task_nodes"]["task_nodes"]] == ["靠近", "打开", "抓取", "移动", "释放", "撤回"]
    assert [n["tuple"]["X"]["subject"] for n in b["task_nodes"]["task_nodes"]] == ["右臂", "右手", "右手", "右臂", "右手", "右臂"]
    for n in b["task_nodes"]["task_nodes"]:
        assert n["tuple"]["X"]["parts"] == [n["tuple"]["X"]["subject"]]
    assert len(b["task_nodes_source"]["task_nodes"][0]["tuple"]["X"]["parts"]) == 2
    jsonschema.validate(b["semantic_graph"], yaml.safe_load(semantic.SCHEMA.read_text()))


def test_start_forks_to_two_preparations_then_and_join_before_grasp():
    b = graph()
    near, opened, grasp = [by_name(b, x)["id"] for x in ("靠近", "打开", "抓取")]
    assert set(b["gates"]["columns"][0]) == {near, opened}
    join = b["gates"]["gates"][0]
    assert set(join["from"]) == {near, opened}
    assert join["to"] == [grasp]
    assert set(join["from_names"]) == {"靠近", "打开"}
    assert len(by_name(b, "抓取")["tuple"]["C_pre"]) == 2
    assert any(e["relation"] == "parallel" and {e["from"], e["to"]} == {near, opened}
               for e in b["operations"]["edges"])
    semantic_graph = b["semantic_graph"]
    start_targets = [r["to"] for r in semantic_graph["relations"] if r["from"] == "START"]
    assert {semantic_graph["nodes"][nid]["name"] for nid in start_targets} == {"靠近", "打开"}


def test_demonstration_serial_opening_does_not_force_semantic_serial_preparation():
    b = example()
    opened = action(8, "右手", "右手张开手指", 0.8, 0.9, after="右手已张开")
    b["atomic"]["atomic_actions"][0]["end"] = 0.7
    b["atomic"]["atomic_actions"].append(opened)
    b["relations"] = [{"from": 1, "to": 8, "relation": "sequence"}]
    build_learning_graph(b)
    near, hand = by_name(b, "靠近")["id"], by_name(b, "打开")["id"]
    assert set(b["gates"]["columns"][0]) == {near, hand}
    assert not any(e["relation"] == "sequence" and {e["from"], e["to"]} == {near, hand}
                   for e in b["operations"]["edges"])
    assert by_name(b, "打开")["atomic_refs"] == [8]


def test_open_state_goal_has_no_invented_action_or_timestamps():
    b = graph()
    opened = by_name(b, "打开")
    assert opened["origin"] == "observed_state_goal"
    assert opened["already_satisfied"]
    assert opened["atomic_refs"] == []
    assert opened["time_range"] is None
    assert len(b["atomic"]["atomic_actions"]) == 7


def test_unknown_hand_state_adds_explicit_inferred_open_goal():
    b = example()
    b["atomic"]["atomic_actions"][1]["state_before"] = ""
    build_learning_graph(b)
    opened = by_name(b, "打开")
    assert opened["inferred"]
    assert opened["origin"] == "semantic_precondition"
    assert opened["time_range"] is None
    assert not opened.get("already_satisfied")


def test_one_move_contains_lift_carry_lower_with_source_trace():
    b = graph()
    move = by_name(b, "移动")
    assert move["atomic_refs"] == [3, 4, 5]
    assert set(move["source_node_ids"]) == {"n1", "n2", "n3"}
    assert move["tuple"]["X"]["subject"] == "右臂"


def test_persistent_grip_is_relation_until_release_starts_not_hold_node():
    b = graph()
    g, release = by_name(b, "抓取")["id"], by_name(b, "释放")["id"]
    persistent = [e for e in b["operations"]["edges"] if e["relation"] == "maintain_until"]
    assert len(persistent) == 1
    assert persistent[0]["from"] == g and persistent[0]["to"] == release
    assert persistent[0]["until_event"] == "target_starts"
    assert not any("保持" in n["name"] or n.get("mode") == "maintain" for n in b["operations"]["nodes"])
    exported = next(r for r in b["semantic_graph"]["relations"] if r["relation"] == "maintain_until")
    assert exported["when"] in b["semantic_graph"]["predicates"]
    assert exported["until_event"] == "target_starts"


def test_rebuild_preserves_atomic_evidence_and_semantic_structure():
    b = example()
    original = [(a["id"], a["action"], a["executor"], a["start"], a["end"]) for a in b["atomic"]["atomic_actions"]]
    build_learning_graph(b)
    before = deepcopy(b["semantic_graph"])
    build_learning_graph(b)
    assert b["semantic_graph"] == before
    assert [(a["id"], a["action"], a["executor"], a["start"], a["end"]) for a in b["atomic"]["atomic_actions"]] == original


def test_actor_classifier_is_enforced_by_model_task_validator():
    payload = {"task_nodes": [{"id": "n", "name": "抓取", "intent_role": "抓住杯子",
                              "required_capabilities": ["抓取"],
                              "tuple": {"X": {"subject": "操作者", "parts": ["右臂", "右手"]},
                                        "O": ["杯子"], "C_pre": [], "C_const": [], "C_post": [],
                                        "E": {"process": [], "completion": []}, "R": []}}]}
    with pytest.raises(ValueError, match="一个节点"):
        s02c_task._validate(payload)


def test_labels_are_centered_and_no_visible_times_or_multiactor_nodes(tmp_path):
    b = graph()
    semantic.render(b, tmp_path)
    tree = ET.fromstring((tmp_path / "operations.svg").read_text())
    ns = {"s": "http://www.w3.org/2000/svg"}
    op_groups = tree.findall(".//s:g[@class='gs-node']", ns)
    assert len(op_groups) == 6
    for group in op_groups:
        circle = group.find("s:circle", ns)
        texts = group.findall("s:text", ns)
        assert len(texts) == 1
        text = texts[0]
        assert float(text.get("x")) == float(circle.get("cx"))
        assert float(text.get("y")) == float(circle.get("cy"))
        assert text.get("text-anchor") == "middle"
        assert text.get("dominant-baseline") == "central"
    visible = [e.text or "" for e in tree.findall(".//s:text", ns)]
    assert not any(re.search(r"\d+(?:\.\d+)?[–~\-]?\d*(?:\.\d+)?s", text) for text in visible)
    html = (tmp_path / "workbench.html").read_text()
    assert html.count('class="detail" data-id=') == 6
    assert "该语义目标已有状态证据满足" in html
    assert "未观察到独立动作时间" in html
    from video2op import workbench
    opened = next(n for n in workbench.build(tmp_path, bundle=b)["nodes"] if n["name"] == "打开")
    assert opened["time"] == [None, None]
    assert not (tmp_path / "execution_policy.yaml").exists()


def test_missing_approach_is_goal_not_fake_observation():
    b = example()
    b["atomic"]["atomic_actions"] = [a for a in b["atomic"]["atomic_actions"] if a["id"] != 1]
    build_learning_graph(b)
    near = by_name(b, "靠近")
    assert near["inferred"] and near["atomic_refs"] == []
    assert near["time_range"] is None
    assert near["tuple"]["X"]["subject"] == "右臂"


def test_two_grasp_cycles_do_not_open_next_grip_while_holding_first_object():
    b = example()
    extra = deepcopy(b["atomic"]["atomic_actions"])
    for a in extra:
        a["id"] += 10
        a["start"] += 8
        a["end"] += 8
    b["atomic"]["atomic_actions"].extend(extra)
    build_learning_graph(b)
    openings = [n for n in b["task_nodes"]["task_nodes"] if n["name"] == "打开"]
    releases = [n for n in b["task_nodes"]["task_nodes"] if n["name"] == "释放"]
    assert len(openings) == len(releases) == 2
    edges = b["operations"]["edges"]
    assert any(e["from"] == releases[0]["id"] and e["to"] == openings[1]["id"]
               and e["relation"] == "sequence" for e in edges)

def test_hold_relation_predicate_and_actor_aware_alias_catalog():
    b = graph()
    relation = next(r for r in b["semantic_graph"]["relations"] if r["relation"] == "maintain_until")
    predicate = b["semantic_graph"]["predicates"][relation["when"]]
    assert predicate["kind"] == "hold"
    assert predicate["hold_scope"] == "cross_node"
    catalog = semantic.catalog()
    assert "抬起" in catalog["移动"]["aliases"]
    assert "抬起" not in catalog["抓取"]["aliases"]
    assert catalog["抓取"]["allowed_subjects"] == ["左手", "右手"]


def test_actual_click_interaction_opens_tuple_join_and_grip_relation(tmp_path):
    import subprocess
    b = graph()
    semantic.render(b, tmp_path)
    script = r'''
const fs = require("fs"), {JSDOM} = require("jsdom");
const dom = new JSDOM(fs.readFileSync(process.argv[1], "utf8"), {runScripts:"dangerously"});
const d = dom.window.document;
function clear(){d.dispatchEvent(new dom.window.KeyboardEvent("keydown",{key:"Escape"}));}
for(const node of d.querySelectorAll("g.gs-node[data-op]")){
 const section = [...d.querySelectorAll(".detail[data-id]")].find(x=>x.dataset.id===node.getAttribute("data-op"));
 if(!section || !section.hidden) throw Error("detail not initially hidden");
 node.dispatchEvent(new dom.window.MouseEvent("click",{bubbles:true}));
 if(section.hidden || !section.textContent.includes("七元组")) throw Error("node click failed");
 clear(); if(!section.hidden) throw Error("escape failed");
}
const gate = d.querySelector("g.gs-gate");
gate.dispatchEvent(new dom.window.MouseEvent("click",{bubbles:true}));
const join = [...d.querySelectorAll(".detail[data-gate]")].find(x=>!x.hidden);
if(!join || !join.textContent.includes("靠近") || !join.textContent.includes("打开")) throw Error("AND join missing");
clear();
d.querySelector("path.gs-line.hold").dispatchEvent(new dom.window.MouseEvent("click",{bubbles:true}));
const edge = [...d.querySelectorAll(".detail[data-edge]")].find(x=>!x.hidden);
if(!edge || !edge.textContent.includes("开始前")) throw Error("hold relation failed");
dom.window.close();
'''
    result = subprocess.run(["node", "-e", script, str(tmp_path / "workbench.html")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_merge_does_not_promote_failed_arm_motion_to_success():
    b = example()
    last_move = next(a for a in b["atomic"]["atomic_actions"] if a["id"] == 5)
    last_move["state_after"] = "杯子滑落"
    build_learning_graph(b)
    move = next(n for n in b["operations"]["nodes"] if n["name"] == "移动")
    assert all(e["status"] == "unverified" for e in move["effect_evidence"])

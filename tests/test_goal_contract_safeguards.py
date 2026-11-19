
from test_goal_effect_learning import scoped_case

from video2op import knowledge


def test_acquisition_without_lift_or_transport_keeps_goal_but_not_success():
    b = scoped_case()
    b["semantic_scope"]["subtasks"][0].update(atomic_refs=[1, 2], outcome="success",
        outcome_evidence=[{"atomic_ref": 2, "field": "state_after", "quote": "握住目标"}])
    item = next(i for i in knowledge.extract(b, "case/result.json")["instances"]
                if i["goal_key"] == "acquire_object")
    assert item["goal_effect_audit"]["issues"]
    assert item["outcome"] == "unknown"
    assert item["original_model_outcome"] == "success"


def test_different_reanalysis_of_same_video_does_not_create_extra_realizations():
    a, b = scoped_case(), scoped_case()
    b["atomic"]["atomic_actions"][0]["action"] = "模型的另一种动作描述"
    result = knowledge.aggregate([knowledge.extract(a, "a/result.json"),
                                  knowledge.extract(b, "b/result.json")])
    skill = next(s for s in result["skills"] if s["goal_key"] == "acquire_object")
    assert len(skill["realizations"]) == 1
    assert result["sources"][0]["alternate_analyses"]


def test_invalid_source_graph_cannot_be_hidden_by_valid_cross_video_schema():
    case = knowledge.extract(scoped_case(), "case/result.json")
    case["case_validation"] = {"passed": False}
    result = knowledge.aggregate([case])
    assert not result["validation"]["passed"]
    assert "source case has invalid semantic graph" in result["validation"]["errors"]


def test_state_goal_rules_map_without_fabricating_an_observed_opening():
    from video2op.single_video.pipeline import build_learning_graph
    b = scoped_case()
    original = {"id": "open_goal", "name": "打开", "atomic_refs": [], "inferred": True,
                "tuple": {"X": {"subject": "右手", "parts": ["右手"]}, "O": ["笔"],
                          "C_pre": [], "C_post": [], "C_const": [],
                          "E": {"process": ["检查开度"], "completion": []}, "R": []}}
    b["task_nodes_source"]["task_nodes"].append(original)
    build_learning_graph(b)
    opened = next(n for n in b["task_nodes"]["task_nodes"] if n["name"] == "打开")
    assert "open_goal" in opened["source_node_ids"]
    assert "检查开度" in opened["tuple"]["E"]["process"]
    assert opened["atomic_refs"] == []
    assert opened["time_range"] is None


def test_unobserved_release_proposal_is_preserved_without_inserting_a_release():
    from video2op.single_video.pipeline import build_learning_graph
    b = scoped_case()
    b["atomic"]["atomic_actions"] = [a for a in b["atomic"]["atomic_actions"] if a["id"] < 6]
    b["task_nodes_source"]["task_nodes"] = [n for n in b["task_nodes_source"]["task_nodes"] if n["id"] in {"n1", "n2"}]
    b["task_nodes_source"]["task_nodes"].append({"id": "release_guess", "name": "释放", "inferred": True,
        "atomic_refs": [], "tuple": {"X": {"subject": "右手", "parts": ["右手"]}, "O": ["笔"],
        "C_pre": ["目标已受支撑"], "C_post": [], "C_const": [], "E": {}, "R": []}})
    build_learning_graph(b)
    assert all(n["name"] != "释放" for n in b["task_nodes"]["task_nodes"])
    assert any(r["source_node_id"] == "release_guess" and r["scope"] == "uninstantiated_hypothesis"
               for r in b["learning_alignment"]["records"])

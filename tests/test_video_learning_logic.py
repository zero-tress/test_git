"""Adversarial evidence contracts, using synthetic records rather than video judgments."""
import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from test_case_graph import fixture as case_fixture, scope_stub
from test_semantic_aggregation import fixture as cross_fixture
from video2op.single_video import case_graph
from video2op.cross_video import semantic_aggregation as aggregation
from video2op.contracts.learning_contracts import CONTRACT_VERSION, policy_prompt, source_fingerprint
from video2op.cross_video.semantic_selection import validate_selection
from video2op.presentation.semantic_skill_render import _visual_flow, svg
from video2op.cross_video.skill_sample_pool import build, validate_groups, validate_reviews


def v2_case():
    bundle, graph = case_fixture()
    graph["contract_version"] = CONTRACT_VERSION
    for node in graph["nodes"]:
        node.update(attempt_id=node["id"], actual_postconditions=["observed synthetic result"])
        for r in node["R"]:
            r.update(completeness="complete", effect_evidence_refs=r["atomic_refs"])
    return bundle, graph


def two_occurrences():
    cases, conditions, rules, graph = cross_fixture()
    second = deepcopy(cases[0]["graph"]["nodes"][0]); second["id"] = "S2"
    cases[0]["graph"]["nodes"].append(second)
    cases[0]["graph"]["relations"] = [{"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order"}]
    graph["skills"][0]["source_members"].append("C1:S2")
    graph["realizations"][0]["source_realization_refs"].append("C1:S2:r1")
    graph["task_nodes"].append({"id": "T2", "skill_id": "K1", "source_members": ["C1:S2"]})
    graph["relations"] = [{"from": "T1", "to": "T2", "relation": "branch", "basis": "inferred_dependency",
        "reason": "synthetic candidate rewrite", "source_relation_refs": ["C1:e0"], "status": "candidate",
        "guard": "ready", "guard_truth": "U", "gate_outcome": "T", "rewrite": {"reason": "explicit policy"}}]
    return cases, conditions, rules, graph


def test_generic_request_has_no_implicit_pen_policy_and_keeps_model_semantics():
    bundle, graph = v2_case(); requests = []
    class Client:
        model = "qwen3.8-27b"
        base_url = "http://127.0.0.1:8032"
        def ask(self, **kwargs):
            if kwargs["stage"] == "s09_scope_roles":
                return scope_stub(kwargs)
            requests.append(kwargs); kwargs["validator"](graph)
            return deepcopy(graph)
    result = case_graph.learn(Client(), bundle)
    assert result["nodes"] == graph["nodes"]
    text = requests[0]["user_text"]
    assert '"operation_id": "step_1"' in text
    assert '"atomic_refs": [1]' in text
    assert '"observed_realization_allowed": false' in text
    assert "本任务入口遵守start_role" not in text
    assert "目标效果之后的释放/放置不属于本任务" not in text
    assert "本任务入口遵守start_role" in policy_prompt({"single_video": {"start_role": "approach", "chain": "linear"}})
    assert policy_prompt(None) == ""


@pytest.mark.parametrize("field,wrong_refs", [("operation_refs", [1]), ("atomic_refs", ["step_1"])])
def test_operation_and_action_namespaces_are_not_interchangeable(field, wrong_refs):
    bundle, graph = v2_case()
    graph["nodes"][0]["R"][0][field] = wrong_refs
    with pytest.raises(ValueError, match="operation_refs must use"):
        case_graph.validate(graph, bundle)


@pytest.mark.parametrize("change", ["reverse", "wrong_owner", "no_overlap", "partial_realization"])
def test_observed_claims_need_correct_local_time_and_complete_effect(change):
    bundle, graph = v2_case()
    if change == "reverse":
        graph["relations"][0].update({"from": "S2", "to": "S1"})
    elif change == "wrong_owner":
        bundle["atomic"]["atomic_actions"].append({"id": 4, "start": 2, "end": 3})
        graph["relations"][0]["source_refs"] = [1, 4]
    elif change == "no_overlap":
        graph["relations"][0].update(relation="parallel", basis="observed_overlap")
    else:
        graph["nodes"][1]["R"][0]["completeness"] = "partial"
    with pytest.raises(ValueError):
        case_graph.validate(graph, bundle)


def test_real_overlap_is_accepted():
    bundle, graph = case_fixture()
    bundle["atomic"]["atomic_actions"][0]["end"] = 1.5
    graph["relations"][0].update(relation="parallel", basis="observed_overlap")
    assert case_graph.validate(graph, bundle)["structure_valid"]


@pytest.mark.parametrize("change", ["none", "duplicate_video", "contradiction", "unknown", "precondition"])
def test_expected_effect_alignment_has_distinct_evidence_requirements(change):
    cases, conditions, _, _ = cross_fixture()
    second = deepcopy(cases[0]); second.update(case_id="C2", video_uid="video-two")
    cases.append(second)
    row = conditions["condition_decisions"][0]
    kind = "C_pre" if change == "precondition" else "C_post"
    row.update(kind=kind, decision="promote_to_skill", source_condition_refs=[f"{cid}:S1:{kind}:0" for cid in ["C1", "C2"]])
    row["evidence"] = [{"member_ref": f"{cid}:S1", "truth": "T", "phase": "pre" if kind == "C_pre" else "post",
                        "outcome": "success", "atomic_refs": [1]} for cid in ["C1", "C2"]]
    if change == "duplicate_video":
        second["video_uid"] = cases[0]["video_uid"]
    elif change in {"contradiction", "unknown"}:
        row["evidence"][1]["truth"] = "F" if change == "contradiction" else "U"
    if change == "none":
        assert aggregation.validate_conditions(conditions, cases)["D1"] == row
    else:
        with pytest.raises(ValueError):
            aggregation.validate_conditions(conditions, cases)


@pytest.mark.parametrize("change", ["reverse", "guard", "truth", "observed", "forbidden", "wrong_type"])
def test_rewrite_never_skips_the_common_boundary_checks(change):
    cases, conditions, rules, graph = two_occurrences()
    policy = {"branch_policy": {"mode": "synthetic", "allow_precedence_rewrite": True}}
    edge = graph["relations"][0]
    if change == "reverse":
        edge.update({"from": "T2", "to": "T1"})
    elif change == "guard":
        edge.pop("guard")
    elif change == "truth":
        edge["guard_truth"] = "T"
    elif change == "observed":
        edge["status"] = "observed"
    elif change == "wrong_type":
        edge["relation"] = "parallel"
    else:
        policy["branch_policy"]["allow_precedence_rewrite"] = False
    with pytest.raises(ValueError):
        aggregation.validate_graph(graph, cases, conditions, rules, policy)


def projected_success_fixture():
    cases, conditions, rules, graph = cross_fixture()
    for sid, outcome in [("S2", "failure"), ("S3", "success")]:
        n = deepcopy(cases[0]["graph"]["nodes"][0]); n.update(id=sid, outcome=outcome)
        cases[0]["graph"]["nodes"].append(n)
        graph["skills"][0]["source_members"].append("C1:" + sid)
        graph["realizations"][0]["source_realization_refs"].append(f"C1:{sid}:r1")
    cases[0]["graph"]["relations"] = [
        {"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order"},
        {"from": "S2", "to": "S3", "relation": "sequence", "basis": "observed_order"}]
    graph["task_nodes"].append({"id": "T3", "skill_id": "K1", "source_members": ["C1:S3"]})
    graph["sample_selection"] = {"sample_dispositions": [
        {"member_ref": "C1:" + sid, "disposition": disposition, "reason": "synthetic evidence"}
        for sid, disposition in [("S1", "success_flow"), ("S2", "contrast_only"), ("S3", "success_flow")]], "unresolved": []}
    graph["realizations"][0].update(successful_source_refs=["C1:S1:r1", "C1:S3:r1"], usage="success_method")
    graph["excluded_relations"] = [{"source_relation_ref": ref, "reason": "Touches excluded failed trial"}
                                    for ref in ["C1:e0", "C1:e1"]]
    graph["relations"] = [{"from": "T1", "to": "T3", "relation": "sequence", "basis": "inferred_dependency",
        "reason": "Projected source path, not a directly observed edge", "source_relation_refs": [], "status": "candidate",
        "projection": {"source_relation_refs": ["C1:e0", "C1:e1"], "reason": "Failed trial retained in contrast data"}}]
    return cases, conditions, rules, graph


def test_failed_trial_is_kept_as_evidence_without_a_success_task_node(tmp_path):
    cases, conditions, rules, graph = projected_success_fixture()
    assert aggregation.validate_graph(graph, cases, conditions, rules)["passed"]
    saved = aggregation.export(graph, cases, tmp_path)
    value = json.loads((tmp_path / "G_semantic.json").read_text())
    assert len(value["source_instances"]) == 3 and saved["task_nodes"] == 2
    assert value["source_instances"][1]["node"]["outcome"] == "failure"
    assert value["source_paths"][0]["source_node_ids"] == ["S1", "S2", "S3"]


@pytest.mark.parametrize("change", ["failure_in_flow", "missing_sample", "skip_success", "reverse_path"])
def test_selection_and_projection_do_not_erase_or_relabel_sources(change):
    cases, conditions, rules, graph = projected_success_fixture()
    if change == "failure_in_flow":
        graph["sample_selection"]["sample_dispositions"][1]["disposition"] = "success_flow"
    elif change == "missing_sample":
        graph["sample_selection"]["sample_dispositions"].pop()
    elif change == "skip_success":
        graph["sample_selection"]["sample_dispositions"][1]["disposition"] = "success_flow"
        cases[0]["graph"]["nodes"][1]["outcome"] = "success"
    else:
        graph["relations"][0]["projection"]["source_relation_refs"].reverse()
    with pytest.raises(ValueError):
        aggregation.validate_graph(graph, cases, conditions, rules)


def test_mixed_policy_and_observed_occurrences_keep_distinct_path_positions():
    cases, conditions, rules, graph = cross_fixture()
    other = deepcopy(cases[0]); other.update(case_id="C2", video_uid="video-two")
    rule = deepcopy(cases[0]["graph"]["nodes"][0])
    rule.update(id="S0", occurrence="rule_only", status="candidate", outcome="unknown", R=[], evidence_refs=[])
    cases[0]["graph"]["nodes"].insert(0, rule)
    cases.append(other)
    cases[0]["graph"]["relations"] = [{"from": "S0", "to": "S1", "relation": "sequence", "basis": "declared_rule"}]
    graph["skills"][0].update(role="approach", source_members=["C1:S0", "C1:S1", "C2:S1"])
    graph["task_nodes"].insert(0, {"id": "T0", "skill_id": "K1", "source_members": ["C1:S0", "C2:S1"], "occurrence": "observed"})
    graph["relations"] = [{"from": "T0", "to": "T1", "relation": "sequence", "basis": "inferred_dependency",
                           "source_relation_refs": ["C1:e0"], "status": "candidate", "reason": "Policy-only entry stays unobserved"}]
    graph["realizations"][0].update(source_realization_refs=["C1:S1:r1", "C2:S1:r1"],
                                    successful_source_refs=["C1:S1:r1", "C2:S1:r1"], usage="success_method")
    graph["sample_selection"] = {"sample_dispositions": [
        {"member_ref": ref, "disposition": disposition, "reason": "synthetic scoped position"}
        for ref, disposition in [("C1:S0", "policy_only"), ("C1:S1", "success_flow"), ("C2:S1", "success_flow")]], "unresolved": []}
    policy = {"cross_video": {"entry_role": "approach", "share_nodes_across_videos": True}}
    assert aggregation.validate_graph(graph, cases, conditions, rules, policy)["passed"]
    assert cases[0]["graph"]["nodes"][0]["outcome"] == "unknown"


def test_media_review_conflict_cannot_be_used_as_success():
    cases, _, _, _ = cross_fixture()
    selection = {"sample_dispositions": [{"member_ref": "C1:S1", "disposition": "success_flow", "reason": "test"}], "unresolved": []}
    with pytest.raises(ValueError, match="conflicting"):
        validate_selection(selection, cases, {"sample_reviews": [{"member_ref": "C1:S1", "status": "conflict"}]})


def test_unresolved_path_stays_out_of_main_graph_but_keeps_local_success():
    cases, conditions, rules, graph = projected_success_fixture()
    selection = graph["sample_selection"]
    selection["sample_dispositions"][1]["disposition"] = "unresolved"
    selection["unresolved"] = ["C1:S2"]
    request = aggregation.graph_request(cases, conditions, rules, None, selection, {
        "sample_groups": [], "sample_reviews": []})
    checks = request["contract_checks"]
    assert checks["main_flow_member_refs"] == ["C1:S1", "C1:S3"]
    assert checks["excluded_flow_relation_refs"] == ["C1:e0", "C1:e1"]
    assert checks["deferred_source_paths"] == {}
    with pytest.raises(ValueError, match="ineligible_or_unknown=.*C1:S1.*C1:S3"):
        aggregation.validate_graph(graph, cases, conditions, rules)
    graph["task_nodes"] = []
    graph["relations"] = []
    result = aggregation.validate_graph(graph, cases, conditions, rules)
    assert result["deferred_source_paths"] == {"C1": ["C1:S2"]}
    assert graph["realizations"][0]["successful_source_refs"] == ["C1:S1:r1", "C1:S3:r1"]


def test_s12_normalizes_unique_source_alias_without_creating_missing_realization():
    graph = {
        "realizations": [{"id": "R1", "skill_id": "unassigned", "source_realization_refs": ["C1:S1:r1"]}],
        "unassigned_realizations": [{"realization_ref": "C1:S1:r1"}, {"realization_ref": "C2:S1:r1"}],
        "relations": [{"relation": "sequence", "gate_outcome": "T"}, {"relation": "branch", "gate_outcome": "F"}],
    }
    result = aggregation.normalize_graph_references(graph)
    assert result["realizations"] == graph["realizations"]
    assert result["unassigned_realizations"] == [{"realization_ref": "R1"}, {"realization_ref": "C2:S1:r1"}]
    assert result["relations"] == [{"relation": "sequence"}, {"relation": "branch", "gate_outcome": "F"}]
    assert graph["unassigned_realizations"][0]["realization_ref"] == "C1:S1:r1"


def test_whole_task_failure_keeps_successful_local_method_outside_task_flow():
    cases, conditions, rules, graph = cross_fixture()
    cases[0]["graph"]["task_outcome"] = "failure"
    graph["sample_selection"] = {"sample_dispositions": [{"member_ref": "C1:S1", "disposition": "contrast_only",
                                                         "reason": "Local success within a failed task"}], "unresolved": []}
    graph["task_nodes"] = []
    graph["realizations"][0].update(successful_source_refs=["C1:S1:r1"], usage="success_method")
    assert aggregation.validate_graph(graph, cases, conditions, rules)["passed"]
    assert cases[0]["graph"]["nodes"][0]["outcome"] == "success"
    graph["sample_selection"]["sample_dispositions"][0]["disposition"] = "success_flow"
    with pytest.raises(ValueError, match="whole-task success"):
        aggregation.validate_graph(graph, cases, conditions, rules)


def test_sample_manifest_preserves_local_context(tmp_path):
    cases, _, _, _ = cross_fixture()
    cases[0]["atomic"][0].update(start=1, end=2, state_before="empty", state_after="holding")
    manifest = build(cases, tmp_path, export_media=False); sample = manifest["samples"][0]
    assert sample["core_intervals"] == [{"atomic_ref": 1, "start": 1, "end": 2}]
    assert sample["state_evidence"][0]["state_after"] == "holding"
    valid = {"sample_groups": [{"id": "G1", "member_refs": [sample["member_ref"]], "reason": "same purpose", "comparison_context": "test"}], "unresolved": []}
    validate_groups(valid, manifest["samples"])
    valid["sample_groups"][0]["member_refs"] *= 2
    with pytest.raises(ValueError, match="exactly one"):
        validate_groups(valid, manifest["samples"])


def test_visual_review_cannot_borrow_another_samples_frames():
    sample = {"member_ref": "C1:S1", "local_outcome": "success", "frames": [{"frame_ref": "C1:S1:f0"}]}
    review = {"sample_reviews": [{"member_ref": "C1:S1", "review_outcome": "success", "status": "supports_source",
        "evidence_frame_refs": ["C2:S1:f0"], "reason": "test", "condition_notes": []}], "unresolved": []}
    with pytest.raises(ValueError, match="local sample"):
        validate_reviews(review, [sample])


def test_visual_review_cannot_use_later_success_frame_to_prove_precondition():
    sample = {"member_ref": "C1:S1", "local_outcome": "success", "frames": [
        {"frame_ref": "pre", "context_phase": "pre"}, {"frame_ref": "post", "context_phase": "post"}]}
    value = {"sample_reviews": [{"member_ref": "C1:S1", "review_outcome": "success", "status": "supports_source",
        "evidence_frame_refs": ["post"], "reason": "Synthetic result", "condition_notes": [
            {"kind": "C_pre", "phase": "pre", "truth": "T", "evidence_frame_refs": ["post"]}]}], "unresolved": []}
    with pytest.raises(ValueError, match="matching pre/during/post"):
        validate_reviews(value, [sample])
    value["sample_reviews"][0]["condition_notes"][0]["evidence_frame_refs"] = ["pre"]
    validate_reviews(value, [sample])


def test_grasp_gate_and_fresh_recheck_do_not_require_promoted_conditions():
    _, _, _, graph = cross_fixture()
    graph["skills"][0]["id"] = "G"
    graph["skills"][0]["name"] = "抓取"
    graph["task_nodes"] = [{"id": key, "name": key, "skill_id": "G", "source_members": []} for key in ["a1", "c", "a2", "g"]]
    graph["relations"] = [
        {"from": "a1", "to": "c", "relation": "branch", "gate_outcome": "F", "guarded_skill_id": "G", "guard": "抓取条件满足", "guard_truth": "U"},
        {"from": "a1", "to": "g", "relation": "branch", "gate_outcome": "T", "guarded_skill_id": "G", "guard": "抓取条件满足", "guard_truth": "U"},
        {"from": "c", "to": "a2", "relation": "sequence"},
        {"from": "a2", "to": "g", "relation": "sequence", "condition_check": {
            "guarded_skill_id": "G", "guard": "抓取条件满足", "guard_truth": "U", "check_context": []}}]
    flow, notes = _visual_flow(graph)
    assert list(notes.values()) == ["G", "G"]
    assert all("进入「抓取」" in n["detail"] for n in flow["nodes"] if n["kind"] == "gate")
    assert not any(e["from"].startswith("__gate_") and e["to"] == "__end__" for e in flow["edges"])
    ET.fromstring(svg(graph))


def test_source_fingerprint_detects_actual_code_changes(tmp_path):
    folder = tmp_path / "video2op"; folder.mkdir()
    path = folder / "module.py"; path.write_text("value = 1")
    before = source_fingerprint(tmp_path); path.write_text("value = 2")
    assert source_fingerprint(tmp_path) != before


def test_later_success_evidence_does_not_establish_a_precondition():
    cases, conditions, _, _ = cross_fixture()
    index = {"C1:S1": {"core_intervals": [{"start": 1., "end": 2.}], "frames": [
        {"frame_ref": "pre", "timestamp": .9}, {"frame_ref": "post", "timestamp": 2.2}]}}
    fact = conditions["condition_decisions"][0]["evidence"][0]
    fact["evidence_frame_refs"] = ["post"]
    with pytest.raises(ValueError, match="Later success"):
        aggregation.validate_condition_sources(conditions, cases, index)
    fact["evidence_frame_refs"] = ["pre"]
    aggregation.validate_condition_sources(conditions, cases, index)
    fact["evidence_frame_refs"] = []
    fact["state_evidence_refs"] = [{"atomic_ref": 1, "field": "state_after"}]
    with pytest.raises(ValueError, match="pre/post"):
        aggregation.validate_condition_sources(conditions, cases, index)


def test_complete_realization_export_keeps_cross_fragment_edges(tmp_path):
    cases, conditions, rules, graph = cross_fixture()
    local = cases[0]["graph"]["nodes"][0]
    local["R"].append({"id": "r2", "name": "legacy serial fragment", "operation_refs": ["step_2"], "atomic_refs": [2], "status": "observed"})
    cases[0]["operations"]["nodes"].append({"id": "step_2", "name": "second operation"})
    cases[0]["operations"]["edges"] = [
        {"from": "step_1", "to": "step_2", "relation": "sequence"},
        {"from": "step_1", "to": "step_2", "relation": "maintain_until"}]
    graph["realizations"][0]["source_realization_refs"].append("C1:S1:r2")
    aggregation.export(graph, cases, tmp_path)
    source = json.loads((tmp_path / "realizations.json").read_text())["realizations"][0]["source_subgraphs"]
    assert len(source) == 1
    assert len(source[0]["source_realization_refs"]) == 2
    assert {r["relation"] for r in source[0]["relations"]} == {"sequence", "maintain_until"}


def test_client_sends_media_bytes_and_content_changes_invalidate_cache(tmp_path, monkeypatch):
    from video2op.llm import VLMClient
    video = tmp_path / "clip.mp4"; video.write_bytes(b"synthetic-video")
    frame = tmp_path / "frame.jpg"; frame.write_bytes(b"synthetic-frame-one")
    client = VLMClient(tmp_path / "cache"); sent = []
    class Response:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": '{"reviewed":true}'}, "finish_reason": "stop"}]}
    def post(*args, **kwargs):
        sent.append(kwargs["json"]); return Response()
    monkeypatch.setattr(client.session, "post", post)
    kwargs = dict(stage="synthetic_review", system="test", user_text="media proof", video=video,
                  images=[{"path": frame, "timestamp": 1., "frame_id": "f1", "sample_id": "C1:S1", "context_phase": "pre"}])
    client.ask(**kwargs); client.ask(**kwargs)
    assert len(sent) == 1
    content = sent[0]["messages"][1]["content"]
    assert any(p["type"] == "video_url" for p in content) and any(p["type"] == "image_url" for p in content)
    assert any(p["type"] == "text" and "C1:S1" in p["text"] for p in content)
    frame.write_bytes(b"synthetic-frame-two"); client.ask(**kwargs)
    assert len(sent) == 2
    records = [json.loads(p.read_text()) for p in (tmp_path / "cache").glob("*.json")]
    assert all(r["video_bytes"] > 0 and r["image_count"] == 1 for r in records)

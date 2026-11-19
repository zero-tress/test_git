from copy import deepcopy
import json
import pytest
from test_goal_effect_learning import scoped_case
from video2op import knowledge, semantic
from video2op.task_observations import (attach, execution_outcome, evaluate_goal,
    prediction_from_audit, validate_reference, condition_observations)
from video2op.skill_tuple import project, validate_projection
from video2op.review import validate_reviewed
from video2op.holdout import explain, cluster_observed_instances
from video2op.knowledge_base import ingest, query
from video2op.pattern_verification import summarize
from video2op.semantic_checks import causal_consistency, pre_post_consistency, temporal_consistency

def task(uid="v", attempted="T", goal="F"):
    return {"case_id":"x", "video_uid":uid, "observation_id":"ob_"+uid,
            "task_contract":{"goal_key":"relocate_and_release","destination":"白色桌面 B","statement":"到B区并结束接触","origin":"provided_dataset_task"},
            "attempted":attempted, "outcome":execution_outcome(attempted,goal),
            "goal_satisfied_final":goal,"method":"Push","drop":"F","obstacle":"小盒子",
            "reviewer":{"kind":"existing_reference_import","identity":None},
            "evidence":[{"evidence_id":"ev","video_uid":uid,"source":"annotations.json",
                         "quote":"盒子仍在A区","provenance":"existing_annotation","verification_status":"verified"}],
            "provenance":"existing_annotation","verification_status":"verified"}

@pytest.mark.parametrize("attempted,goal,result", [
    ("F","T","not_executed"),("F","F","not_executed"),("T","F","failure"),
    ("T","T","success"),("T","U","unknown"),("U","T","unknown")])
def test_attempt_is_independent_from_initial_or_final_goal(attempted,goal,result):
    assert execution_outcome(attempted,goal)==result

def test_missing_goal_component_remains_unknown():
    assert evaluate_goal({"at_destination":"T","stationary":"T"})=="U"
    assert evaluate_goal({"at_destination":"F","stationary":"T"})=="F"

def test_task_audit_goal_is_recomputed_without_reference_labels():
    pred=prediction_from_audit({"attempted":"F","goal_satisfied_final":"F","final_region":"B",
                               "final_stationary":"T","hand_separated_final":"T"}, "v", {}, "audit.json")
    assert pred["goal_satisfied_final"]=="T"
    assert pred["outcome"]=="not_executed"
    assert pred["original_model_goal"]=="F"

def test_reference_cannot_cross_video_boundary():
    with pytest.raises(ValueError,match="identity"):
        attach({}, task("a"),task("b"))

def test_reference_outcome_requires_evidence():
    r=task();r["evidence"]=[]
    with pytest.raises(ValueError):validate_reference(r)

def test_task_failure_does_not_mark_local_grasp_failure():
    b=scoped_case(uid="v")
    attach(b,task("v"),task("v"))
    case=knowledge.extract(b,"v/result.json")
    whole=next(i for i in case["instances"] if i["instance_scope"]=="provided_task")
    assert whole["outcome"]=="failure"
    assert whole["bindings"]["destination"]=="白色桌面 B"
    assert all(i["outcome"]!="failure" for i in case["instances"] if i["goal_key"]=="grasp_object")

def test_nonexecution_has_observation_without_fabricated_task_actions():
    b=scoped_case(uid="v")
    attach(b,task("v","F","T"),task("v","F","T"))
    case=knowledge.extract(b,"v/result.json")
    assert not any(i["instance_scope"]=="provided_task" for i in case["instances"])
    result=knowledge.aggregate([case])
    assert result["task_observations"][0]["outcome"]=="not_executed"
    assert result["task_condition_induction"]["conditions"][0]["counts"]["T_not_executed"]==1

def test_model_obstacle_assessment_cannot_become_reference():
    r=task();r["provenance"]="model_task_audit"
    assert condition_observations([r])==[]

def test_tuple_preserves_realizations_and_scopes_constraints():
    b=scoped_case(uid="v")
    k=knowledge.aggregate([knowledge.extract(b,"v/result.json")])
    artifacts=project(k)
    assert not validate_projection(k,artifacts)
    for s in artifacts["skill_tuples"]["skills"]:
        assert s["C_const"]==[]
        assert s["E"]!=s["C_post"]
        assert s["verification_status"]=="unverified"
    original={r["realization_id"] for s in k["skills"] for r in s["realizations"]}
    projected={r["id"] for s in artifacts["skill_tuples"]["skills"] for r in s["R"]}
    assert original==projected

def test_holdout_identity_leak_is_rejected():
    case=knowledge.extract(scoped_case(uid="v"),"v/result.json")
    with pytest.raises(ValueError,match="leaked"):
        explain(knowledge.aggregate([case]),[case])

def test_holdout_match_never_self_certifies_applicability():
    a=knowledge.extract(scoped_case(uid="a"),"a/result.json")
    b=knowledge.extract(scoped_case(uid="b"),"b/result.json")
    result=explain(knowledge.aggregate([a]),[b])
    assert result[0]["decision"]=="hit"
    assert result[0]["semantic_reuse_verified"] is False
    assert all(r["applicability_verified"] is False for r in result[0]["instances"])

def test_clustering_does_not_read_declared_effects():
    k=knowledge.aggregate([knowledge.extract(scoped_case(uid="v"),"v/result.json")])
    before=cluster_observed_instances(k)
    for item in k["instances"]:
        item["expected"]={"purpose":"changed","expected_effects":[{"invented":True}]}
    assert cluster_observed_instances(k)==before

def test_kb_versioned_query_and_idempotent_ingest(tmp_path):
    k=knowledge.aggregate([knowledge.extract(scoped_case(uid="v"),"v/result.json")])
    tuples=project(k)["skill_tuples"]
    a=ingest(tuples,tmp_path);b=ingest(tuples,tmp_path)
    assert a==b
    sid=tuples["skills"][0]["skill_id"]
    version=a["skills"][sid][0]["version"]
    assert query(tmp_path,sid,version)["skill"]["skill_id"]==sid
    with pytest.raises(KeyError):query(tmp_path,sid,"missing")

def test_invalid_effect_reference_fails_causal_check():
    b=scoped_case()
    b["operations"]["nodes"][0]["effect_evidence"]=[{"status":"observed","atomic_refs":[999]}]
    assert causal_consistency(b)["status"]=="fail"

def test_unresolved_pre_post_entailment_is_reviewed_not_assumed():
    b=scoped_case()
    nodes=[n for n in b["semantic_graph"]["nodes"] if n not in {"START","END"}]
    b["semantic_graph"]["nodes"][nodes[0]]["skill"]["C_post"]=[]
    b["semantic_graph"]["relations"]=[{"from":nodes[0],"to":nodes[-1],"relation":"sequence","basis":"required_dependency"}]
    assert pre_post_consistency(b)["status"]=="warn"

def test_cycle_fails_temporal_consistency():
    b=scoped_case()
    nodes=[n for n in b["semantic_graph"]["nodes"] if n not in {"START","END"}]
    b["semantic_graph"]["relations"]=[{"from":nodes[0],"to":nodes[-1],"relation":"sequence"},
                                      {"from":nodes[-1],"to":nodes[0],"relation":"sequence"}]
    assert temporal_consistency(b)["status"]=="fail"

def test_pattern_verification_cannot_be_fabricated():
    b=scoped_case()
    cases=[{"bundle":b,"video_uid":"a"},{"bundle":deepcopy(b),"video_uid":"b"}]
    result=summarize(cases)
    assert result["verified"]==0
    if result["patterns"]:
        key=result["patterns"][0]["pattern_key"]
        with pytest.raises(ValueError):
            summarize(cases,[{"pattern_key":key,"confirmed":True}])

def test_reference_does_not_upgrade_every_semantic_effect():
    b=scoped_case(uid="v")
    attach(b,task("v"),task("v"))
    k=knowledge.aggregate([knowledge.extract(b,"v/result.json")])
    assert k["validation"]["semantic_success_verified"] is False
    assert k["validation"]["verification_basis"]["reviewed_instances"]>=1
    assert k["validation"]["verification_basis"]["unverified_instances"]

def test_description_is_background_with_explicit_provenance(monkeypatch,tmp_path):
    from video2op.single_video.stages import s02a_intent
    monkeypatch.setattr(s02a_intent.media,"make_clip",lambda *a,**k:tmp_path/"video.mp4")
    captured=[]
    class Client:
        def ask(self,**kwargs):
            captured.append(kwargs["user_text"])
            return {"intents":[{"statement":"观察盒子","confidence":0.4}]}
    ctx={"video":tmp_path/"v.mp4","meta":{"duration":1},"video_id":"v","viewpoint":{}}
    a=s02a_intent.run(Client(),ctx)
    original=captured[-1]
    b=s02a_intent.run(Client(),{**ctx,"text_description":{"text":"请观察盒子","provenance":"text_description"}})
    assert a.get("additional_evidence") is None
    assert b["additional_evidence"]["provenance"]=="text_description"
    assert captured[-1].startswith(original)
    assert "非视频事实" in captured[-1]

def test_effect_review_requires_a_matching_scoped_state():
    from video2op.evidence import audit_effects
    b=scoped_case(uid="v")
    observed = next(a for a in b["atomic"]["atomic_actions"] if a["id"] == 3)
    observed.update(state_after="杯子离开桌面", state_after_from="observed", world_after=["杯子离开桌面"])
    case=knowledge.extract(b,"v/result.json")
    item=case["instances"][0]
    actions=item["observed_process"]
    last=max(actions,key=lambda a:a["end"])
    quote=(last.get("world_after") or [last["state_after"]])[0]
    field="world_after" if last.get("world_after") else "state_after"
    row={"instance_id":item["instance_id"],"video_uid":"v","goal_key":item["goal_key"],
         "reviewer":"test_explicit_reviewer","truth":"U","outcome":"success","outcome_review":True,
         "outcome_evidence":[{"atomic_ref":last["id"],"field":field,"quote":quote}]}
    b["operations"]["nodes"][0]["effect_evidence"]=[{"condition":quote,"status":"observed","atomic_refs":[last["id"]]}]
    report=audit_effects(b,[row])
    assert report["records"][0]["verification_status"]=="verified"
    assert report["records"][0]["verification_basis"]=="scoped_reviewed_state_quote"

def test_outcome_review_updates_instance_without_claiming_causality():
    b=scoped_case(uid="v")
    observed = next(a for a in b["atomic"]["atomic_actions"] if a["id"] == 3)
    observed.update(state_after="杯子未离开桌面", state_after_from="observed")
    case=knowledge.extract(b,"v/result.json");item=case["instances"][0]
    last=max(item["observed_process"],key=lambda a:a["end"])
    row={"instance_id":item["instance_id"],"video_uid":"v","goal_key":item["goal_key"],
         "reviewer":"test_reviewer","truth":"U","outcome":"failure","outcome_review":True,
         "outcome_evidence":[{"atomic_ref":last["id"],"field":"state_after","quote":last["state_after"]}]}
    original_case=deepcopy(case)
    result=knowledge.aggregate([case],[row])
    assert case==original_case
    corrected=next(i for i in result["instances"] if i["instance_id"]==item["instance_id"])
    assert corrected["outcome"]=="failure"
    assert corrected["outcome_status"]=="reviewed_reference"
    assert result["validation"]["semantic_success_verified"] is False

def test_interface_validation_detects_mismatched_graph(tmp_path):
    from video2op.semantic_interface import validate_files
    b=scoped_case();semantic.export(b,tmp_path)
    assert validate_files(tmp_path)["passed"]
    p=tmp_path/"program.json";data=json.loads(p.read_text());data["graph_id"]="wrong";p.write_text(json.dumps(data))
    assert not validate_files(tmp_path)["passed"]

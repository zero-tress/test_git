"""Canonical, provenance-preserving Skill Tuple projection and semantic rule artifacts."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
from pathlib import Path

FIELDS = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")

def predicate_id(text):
    return "P" + hashlib.sha1(text.encode()).hexdigest()[:12]

def normalized_text(text, instance):
    text = str(text)
    bindings = instance.get("bindings", {})
    for word, role in sorted([(str(bindings.get("target") or ""), "$target"),
                              (str(bindings.get("destination") or ""), "$destination")], key=lambda r: -len(r[0])):
        if word:
            text = text.replace(word, role)
    for name, role in [("左手", "$gripper"), ("右手", "$gripper"), ("左臂", "$arm"), ("右臂", "$arm")]:
        text = text.replace(name, role)
    return text

def project(knowledge):
    predicates, constraints, evaluators, tuples = {}, [], [], []
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    def register(text, origin, source=None, expression=None):
        pid = predicate_id(text)
        item = predicates.setdefault(pid, {"text": text, "origin": origin,
                                           "verification_status": "unverified", "sources": []})
        if source and source not in item["sources"]:
            item["sources"].append(source)
        if expression:
            item["expression"] = deepcopy(expression)
        return pid
    for skill in knowledge["skills"]:
        sid = skill["skill_id"]
        members = [instances[i] for i in skill["instance_ids"]]
        effects = [register(json.dumps(e, ensure_ascii=False, sort_keys=True), skill.get("origin", "declared"),
                            expression=e) for e in skill["expected_effects"]]
        r_items = []
        for r in skill["realizations"]:
            rid = r["realization_id"]
            conditions = {"C_pre": [], "C_const": []}
            seen = set()
            for iid in r["instance_ids"]:
                item = instances[iid]
                for c in item.get("candidate_conditions", []):
                    kind = c.get("kind")
                    if kind not in conditions or c.get("scope") not in {"node", "provided_task"}:
                        continue
                    text = normalized_text(c["text"], item)
                    pid = register(text, "video_derived", {"video_uid": item["video_uid"], "instance_id": iid,
                                                          "source_node_id": c.get("node_id"),
                                                          "case_predicate_ref": predicate_id(c["text"])})
                    key = (kind, pid, iid, c.get("node_id"))
                    if key in seen:
                        continue
                    seen.add(key)
                    scoped = {"predicate_ref": pid, "scope": "implementation_node",
                              "node_ref": c.get("node_id"), "source_instance": iid,
                              "verification_status": "unverified"}
                    conditions[kind].append(scoped)
                    if kind == "C_const":
                        cid = "constraint_" + hashlib.sha1((sid + rid + pid).encode()).hexdigest()[:16]
                        if not any(x["constraint_id"] == cid for x in constraints):
                            category = "hold" if any(w in text for w in ["保持", "维持", "握持"]) else "avoid" if any(w in text for w in ["不", "无", "避免", "防止"]) else "capability"
                            constraints.append({"constraint_id": cid, "skill_id": sid, "realization_id": rid,
                                                "predicate_ref": pid, "category": category,
                                                "scope": "implementation_node", "verification_status": "unverified",
                                                "policy": "Not promoted to a universal task constraint."})
            r_items.append({"id": rid, "realization_ref": rid, "name": r["label"],
                            "instance_ids": r["instance_ids"], **conditions,
                            "selection_guard": {"status": "unresolved", "reason": "requires_realization_specific_contrast"},
                            "verification_status": "unverified"})
        evaluator_id = "eval_" + sid
        criteria = {"process": [], "completion": [], "failure_signals": []}
        for item in members:
            for key, values in item.get("evaluation_criteria", {}).items():
                if key not in criteria:
                    continue
                for value in values:
                    text = normalized_text(value, item)
                    pid = register(text, "video_derived", {"video_uid": item["video_uid"], "instance_id": item["instance_id"]})
                    if pid not in criteria[key]:
                        criteria[key].append(pid)
        evaluators.append({"evaluator_id": evaluator_id, "skill_id": sid,
                           "completion": {"operator": "all", "predicate_refs": effects, "unknown_policy": "U_remains_unknown"},
                           "process": {"candidate_predicate_refs": criteria["process"]},
                           "failure_signals": {"candidate_predicate_refs": criteria["failure_signals"]},
                           "completion_candidates": criteria["completion"],
                           "detector": {"binding_status": "unbound", "implementation": None},
                           "verification_status": "unverified",
                           "origin": "declared_goal_contract_with_video_derived_criteria"})
        roles = sorted({n["actor_role"] for n in skill.get("general_operation_graph", {}).get("nodes", [])})
        provenance = [{"video_sha256": i["video_uid"], "instance_id": i["instance_id"],
                       "source": i.get("analysis_source", i["source"]), "original_source": i["source"],
                       "scope": i.get("instance_scope", "subtask")} for i in members]
        tuples.append({"skill_id": sid, "goal_key": skill["goal_key"], "name": skill["name"],
                       "purpose": skill["purpose"],
                       "X": {"subject": "actor", "roles": roles, "binding_status": "unbound"},
                       "O": {"roles": ["target", "destination"] if any("destination" in e["roles"] for e in skill["expected_effects"]) else ["target"],
                             "object_categories": skill["object_categories"],
                             "bindings": [{"instance_id": i["instance_id"], **i["bindings"]} for i in members]},
                       "C_pre": [], "C_const": [], "E": [evaluator_id], "C_post": effects, "R": r_items,
                       "provenance": provenance, "verification_status": "unverified",
                       "unresolved": ["Common preconditions require cross-realization boundary evidence.",
                                      "Implementation-node constraints are retained under each R.",
                                      "Runtime actor and predicate detectors are unbound."],
                       "causal_status": "not_established"})
    result = {"schema_version": "skill_tuple.v1", "skills": tuples, "predicates": predicates,
              "policy": "Tuples are the standard skill view; knowledge.json preserves complete membership and audits."}
    return {"skill_tuples": result,
            "constraints": {"schema_version": "semantic_constraints.v1", "constraints": constraints, "predicates": predicates},
            "evaluators": {"schema_version": "semantic_evaluators.v1", "evaluators": evaluators, "predicates": predicates}}

def validate_projection(knowledge, artifacts):
    import jsonschema
    import yaml
    schema = yaml.safe_load((Path(__file__).parent / "schemas/skill_tuple.schema.yaml").read_text())
    result = artifacts["skill_tuples"]
    errors = sorted(e.message for e in jsonschema.Draft7Validator(schema).iter_errors(result))
    original = {s["skill_id"]: s for s in knowledge["skills"]}
    evaluator_ids = {e["evaluator_id"] for e in artifacts["evaluators"]["evaluators"]}
    for item in result["skills"]:
        source = original[item["skill_id"]]
        if {r["id"] for r in item["R"]} != {r["realization_id"] for r in source["realizations"]}:
            errors.append("realization identity is not conserved")
        if {p["instance_id"] for p in item["provenance"]} != set(source["instance_ids"]):
            errors.append("instance membership is not conserved")
        if not set(item["E"]) <= evaluator_ids or not set(item["C_post"]) <= set(result["predicates"]):
            errors.append("unknown evaluator or predicate")
    return errors

def export(knowledge, out):
    out = Path(out)
    artifacts = project(knowledge)
    errors = validate_projection(knowledge, artifacts)
    if errors:
        raise ValueError("Invalid Skill Tuple projection: " + "; ".join(errors))
    out.mkdir(parents=True, exist_ok=True)
    for key, value in artifacts.items():
        (out / (key + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    case_bindings = []
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    graph_cache = {}
    for canonical_id, predicate in artifacts["skill_tuples"]["predicates"].items():
        for source in predicate.get("sources", []):
            if not source.get("case_predicate_ref"):
                continue
            instance = instances[source["instance_id"]]
            path = instance.get("analysis_source", instance["source"])
            if path not in graph_cache:
                file = Path(path)
                graph_cache[path] = json.loads(file.read_text()).get("semantic_graph", {}).get("predicates", {}) if file.is_file() else {}
            resolved = source["case_predicate_ref"] in graph_cache[path]
            case_bindings.append({**source, "canonical_predicate_ref": canonical_id,
                                  "case_result": path, "binding_status": "resolved" if resolved else "needs_review",
                                  "note": "Role-normalized predicate and original case wording are linked explicitly."})
    (out / "case_predicate_bindings.json").write_text(json.dumps(case_bindings, ensure_ascii=False, indent=2) + "\n")
    (out / "effective_conditions.json").write_text(json.dumps({
        "local_subtask_conditions": knowledge["condition_induction"],
        "provided_task_conditions": knowledge.get("task_condition_induction", {}),
        "policy": "Rejected observations are not refuted conditions; causal conclusions require further trials."
    }, ensure_ascii=False, indent=2) + "\n")
    return artifacts

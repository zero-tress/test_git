"""One project skill outline, with explicit ontology-to-seven-tuple provenance."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

FIELDS = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")
ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "skill_library"
REFERENCE = ROOT / "references/two_table_skill_knowledge.json"
GOAL_REFS = {"grasp_object": "GraspObjectSkill", "acquire_object": "AcquireObjectSkill",
             "place_object": "PlaceOnSurfaceSkill"}
ACTION_REFS = {"抓取": "GraspObjectSkill"}


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _condition(c):
    return {"condition_ref": c["condition_id"], "kind": c["kind"], "phase": c.get("phase"),
            "expression": deepcopy(c["expression"]), "origin": deepcopy(c.get("origin", {})),
            "applies_when_bound_slots": deepcopy(c.get("applies_when_bound_slots", [])),
            "truth": "U", "verification_status": "not_observed"}


def build(reference=None, actions=None):
    from .goal_semantics import GOALS, contract
    if reference is None:
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if actions is None:
        from .semantic import _default_catalog
        actions = _default_catalog()
    source_hash = hashlib.sha256(json.dumps(reference, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    templates = {}
    contracts = reference["ontology"]["skill_contracts"]
    implementations = reference["implementation_reference"]["templates"]
    for index in reference["skill_index"]:
        ref = index["skill_ref"]
        c = contracts[ref]
        conditions = c.get("conditions", [])
        methods = []
        evaluations = []
        for rid in index.get("implementation_ref_ids", []):
            implementation = implementations[rid]
            methods.append({"id": "reference/"+rid, "name": rid, "origin": "implementation_reference",
                            "reference_path": "implementation_reference.templates."+rid,
                            "expansion": deepcopy(implementation.get("expansion", [])),
                            "required_capabilities": implementation.get("required_capabilities", []),
                            "binding_status": "unbound", "observation_status": "not_observed"})
            evaluations.extend(deepcopy(implementation.get("completion_conditions", [])))
        rules = reference["ontology"].get("acquire_method_rules", {})
        preference = rules.get("preference", {})
        if preference.get("source_ref") == ref:
            methods.append({"id": "semantic_method/"+preference["method_ref"],
                            "skill_template_ref": "skill/"+preference["method_ref"],
                            "origin": "reference_method_preference", "binding_status": "unbound",
                            "observation_status": "not_observed", "selection_status": "provisional"})
            for rule in rules.get("switches", []):
                methods.append({"id": "semantic_method/"+rule["target_method_ref"],
                                "skill_template_ref": "skill/"+rule["target_method_ref"],
                                "origin": "reference_method_switch", "guard": deepcopy(rule),
                                "binding_status": "unbound", "observation_status": "not_observed",
                                "selection_status": "deferred_until_guard_and_roles_confirmed"})
        pre = [_condition(r) for r in conditions if r.get("kind") == "precondition"]
        invariants = [_condition(r) for r in conditions if r.get("phase") in {"during", "invariant"}
                      or r.get("kind") in {"invariant", "constraint"}]
        post = [_condition(r) for r in conditions if r.get("kind") == "expected_effect"]
        tuple_ = {"X": {"role": "acting_agent", "binding_status": "unbound",
                        "ontology_actor_refs": ["ActingRobot"],
                        "policy": "Human demonstrators bind locally; they are not current robot facts."},
                  "O": {"role_slots": deepcopy(c.get("role_slots", [])),
                        "role_constraints": [_condition(r) for r in conditions if r.get("kind") == "role_constraint"]},
                  "C_pre": pre, "C_const": invariants,
                  "E": {"completion_checks": evaluations, "detector_binding": "unbound"},
                  "C_post": post, "R": methods}
        templates["skill/"+ref] = {"template_id": "skill/"+ref, "skill_ref": ref, "label": index["label"],
            "level": "semantic_skill", "meaning": index["meaning"], "parent_refs": index.get("parent_refs", []),
            "method_selection_required": c.get("method_selection_required", False),
            "seven_tuple": tuple_, "result_ports": deepcopy(c.get("result_ports", [])),
            "source_contract": {"schema": c["schema_version"], "ontology_revision": c["ontology_revision"]},
            "origin": "declared_reference_not_video_induction",
            "unresolved": (["No explicit process invariant supplied; C_const remains empty."] if not invariants else [])}
    for goal in GOALS:
        c = contract(goal)
        ontology_ref = GOAL_REFS.get(goal)
        templates["goal/"+goal] = {
            "template_id": "goal/"+goal, "label": c["name"], "level": "project_goal",
            "goal_key": goal, "ontology_candidate_ref": ontology_ref,
            "mapping_status": "requires_effect_alignment" if goal == "acquire_object" else "declared_correspondence",
            "seven_tuple": {"X": {"role": "acting_agent", "binding_status": "unbound"},
                            "O": {"roles": sorted({role for e in c["expected_effects"] for role in e["roles"] if role != "actor"})},
                            "C_pre": [], "C_const": [],
                            "E": {"completion_rule": "all_declared_postconditions", "detector_binding": "unbound"},
                            "C_post": deepcopy(c["expected_effects"]), "R": []},
            "origin": "project_declared_goal_contract",
            "unresolved": ["Public conditions and realizations require video evidence."]
                + (["Project acquisition includes leaving source support; reference AcquireObjectSkill is not silently substituted."]
                   if goal == "acquire_object" else [])}
    for name, action in actions.items():
        ref = ACTION_REFS.get(name)
        source = templates.get("skill/"+str(ref))
        templates["action/"+name] = {
            "template_id": "action/"+name, "label": name, "level": "controlled_action",
            "ontology_candidate_ref": ref, "meaning": action["meaning"],
            "seven_tuple": deepcopy(source["seven_tuple"]) if source else {
                "X": {"role": "acting_agent", "demonstration_subjects": action["allowed_subjects"], "binding_status": "unbound"},
                "O": {"roles": ["target"]}, "C_pre": [], "C_const": [],
                "E": {"completion_checks": [], "detector_binding": "unbound"},
                "C_post": [], "R": []},
            "origin": "declared_controlled_vocabulary", "unresolved": ["Observed node tuple is a local instance, not a replacement template."]}
    outline = {"schema_version": "skill_template_library.v1", "tuple_fields": list(FIELDS),
               "reference": {"path": "references/two_table_skill_knowledge.json",
                             "canonical_sha256": source_hash, "schema": reference["schema_version"],
                             "ontology_revision": reference["source"]["ontology_revision"]},
               "templates": templates,
               "policy": "Reference conditions, video observations and learned summaries remain separate."}
    revision = hashlib.sha256(json.dumps(outline, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    outline["revision"] = revision
    catalog = {"schema_version": "project_action_catalog.v1", "library_revision": revision,
               "actions": {name: {**deepcopy(action), "template_ref": "action/"+name} for name, action in actions.items()},
               "skill_index": [{"template_ref": "skill/"+r["skill_ref"], **deepcopy(r)} for r in reference["skill_index"]],
               "tuple_fields": list(FIELDS)}
    return catalog, outline


def initialize():
    catalog, outline = build()
    save(LIBRARY/"action_catalog.json", catalog)
    save(LIBRARY/"skill_templates.json", outline)
    return {"actions": len(catalog["actions"]), "semantic_skills": len(catalog["skill_index"]),
            "templates": len(outline["templates"]), "revision": outline["revision"]}


def load():
    return json.loads((LIBRARY/"skill_templates.json").read_text(encoding="utf-8"))


def export_learned(knowledge, tuple_view, out):
    """One outline per learned knowledge version; never duplicate it per video."""
    out = Path(out)
    library = load()
    members = {s["skill_id"]: s for s in knowledge["skills"]}
    templates = []
    for s in tuple_view["skills"]:
        source = members[s["skill_id"]]
        abstract = {k: deepcopy(s[k]) for k in FIELDS}
        # Bindings are evidence rows, not parameters hard-coded into a global skill.
        bindings = abstract["O"].pop("bindings", [])
        templates.append({"skill_id": s["skill_id"], "label": s["name"],
            "template_ref": "goal/"+s["goal_key"], "goal_key": s["goal_key"],
            "learned_seven_tuple": abstract, "source_video_count": source["source_video_count"],
            "instance_count": len(source["instance_ids"]), "instance_ids": source["instance_ids"],
            "instance_bindings": bindings,
            "realization_count": len(s["R"]), "observed_effect_review": "requires_proposition_review",
            "candidate_condition_summary": [deepcopy(c) for c in knowledge["condition_induction"]["conditions"]
                                            if c["goal_key"] == s["goal_key"]],
            "origin": "cross_video_induction", "public_condition_policy": "Do not promote R-specific conditions by union."})
    result = {"schema_version": "learned_skill_catalog.v1", "template_library_revision": library["revision"],
              "tuple_fields": list(FIELDS), "skills": templates,
              "artifact_base": str(out.resolve()), "predicates": deepcopy(tuple_view["predicates"]),
              "evaluators": json.loads((out/"evaluators.json").read_text(encoding="utf-8")),
              "source_video_uids": [s["video_uid"] for s in knowledge["sources"]],
              "provenance": "Learned membership, conditions and R; declared definitions remain in the shared library."}
    save(out/"skill_catalog.json", result)
    return result

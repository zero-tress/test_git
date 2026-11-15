"""Separate same-purpose graph induction from local skill clip classification."""

from __future__ import annotations

from copy import deepcopy

from .cross_video_alignment import digest
from .goal_semantics import contract
from .knowledge import extract
from .skill_episodes import build as build_episodes
from .task_causality import audit


def _project(bundle, unit, refs):
    actions = {a["id"]: a for a in bundle["atomic"]["atomic_actions"]}
    selected = sorted(
        (deepcopy(actions[r]) for r in refs if r in actions and not actions[r].get("inferred")),
        key=lambda a: (a["start"], str(a["id"])),
    )
    actual = {a["id"] for a in selected}
    nodes = [n for n in bundle["task_nodes"]["task_nodes"] if set(n.get("atomic_refs", [])) & actual]
    ids = {n["id"] for n in nodes}
    unit.update(
        atomic_refs=[a["id"] for a in selected], observed_process=selected, source_node_refs=[n["id"] for n in nodes]
    )
    unit["operation_subgraph"] = {
        "nodes": [
            {
                "node_id": n["id"],
                "name": n["name"],
                "selected_atomic_refs": [r for r in n.get("atomic_refs", []) if r in actual],
                "partial_node": bool(set(n.get("atomic_refs", [])) - actual),
                "semantic_preconditions": deepcopy(n.get("tuple", {}).get("C_pre", [])),
                "semantic_postconditions": deepcopy(n.get("tuple", {}).get("C_post", [])),
            }
            for n in nodes
        ],
        "relations": [deepcopy(e) for e in bundle["operations"]["edges"] if e["from"] in ids and e["to"] in ids],
    }
    existing = {(e["from"], e["to"], e["relation"]) for e in unit["operation_subgraph"]["relations"]}
    node_for = {r: n["id"] for n in nodes for r in n.get("atomic_refs", []) if r in actual}
    for left, right in zip(selected, selected[1:], strict=False):
        a, b = node_for.get(left["id"]), node_for.get(right["id"])
        ls = str(left.get("executor", ""))
        rs = str(right.get("executor", ""))
        paired = (ls[:1] in {"左", "右"} and ls[:1] == rs[:1]) or ls == rs
        if a and b and a != b and paired and left["end"] <= right["start"] and (a, b, "sequence") not in existing:
            unit["operation_subgraph"]["relations"].append(
                {
                    "from": a,
                    "to": b,
                    "relation": "sequence",
                    "basis": "observed_order",
                    "causal_status": "not_established",
                    "time_evidence": {
                        "source_atomic": left["id"],
                        "target_atomic": right["id"],
                        "source_end_sec": left["end"],
                        "target_start_sec": right["start"],
                    },
                }
            )
            existing.add((a, b, "sequence"))
    return unit


def _filtered(case, units):
    result = deepcopy(case)
    result["instances"] = units
    allowed = {u["instance_id"] for u in units}
    result["observations"] = [deepcopy(o) for o in case["observations"] if o["instance_id"] in allowed]
    return result


def split(bundle, source, case=None, provided_goal=None):
    """Goal context keeps preceding events without claiming they are prerequisites."""
    provided_goal = provided_goal or bundle.get("learning_goal")
    original = deepcopy(case) if case is not None else extract(bundle, source)
    units = original["instances"]
    episodes = [i for i in units if i.get("instance_scope") == "skill_episode"]
    if not episodes:
        episodes = build_episodes(bundle, source)["episodes"]
    supplied = [i for i in units if i.get("instance_scope") == "provided_task"]
    if provided_goal:
        goal = provided_goal["goal_key"]
        category = provided_goal.get("target_category")
        candidates = [i for i in units if category is None or i["target"]["category"] == category]
        ready = [i for i in candidates if i.get("instance_scope") == "purpose_task" and i["goal_key"] == goal]
        tasks = ready or [
            i for i in candidates if i["goal_key"] == goal and i.get("instance_scope") != "skill_episode"
        ]
        if not tasks:
            # The user's goal defines expected effects; a mistaken model goal label cannot change that intention.
            widest = {}
            for i in candidates:
                if i.get("instance_scope") == "skill_episode":
                    continue
                target = i["target"]["local_entity"]
                if target not in widest or len(i["atomic_refs"]) > len(widest[target]["atomic_refs"]):
                    widest[target] = i
            tasks = []
            for old in widest.values():
                u = deepcopy(old)
                u["alternative_model_scope"] = {
                    "goal_key": old["goal_key"],
                    "instance_id": old["instance_id"],
                    "outcome": old["outcome"],
                }
                u.update(
                    goal_key=goal,
                    expected=contract(goal),
                    skill_ref="skill_" + goal,
                    outcome="unknown",
                    outcome_evidence=[],
                    outcome_status="unverified",
                    goal_effect_audit={
                        "status": "candidate_requires_entailment_review",
                        "issues": [],
                        "note": "User goal retained independently of model classification.",
                    },
                )
                tasks.append(u)
    elif supplied or original.get("task_observation"):
        tasks = supplied
    else:
        # Select maximal intent-scoped processes; atomic leaf projections are not whole tasks.
        candidates = [
            i
            for i in units
            if i.get("instance_scope") not in {"skill_episode"}
            and not i.get("subtask_id", "").startswith("leaf_")
            and i.get("intent_ids")
        ]
        tasks = [
            i
            for i in candidates
            if not any(
                set(i["atomic_refs"]) < set(j["atomic_refs"]) and set(i["intent_ids"]) & set(j["intent_ids"])
                for j in candidates
            )
        ]
    causal = audit(bundle)
    if original.get("causal_model_review"):
        causal["model_review"] = deepcopy(original["causal_model_review"])
    purpose = []
    source_ids = set()
    for source_unit in tasks:
        task = deepcopy(source_unit)
        source_ids.add(task["instance_id"])
        source_ids.add(task.get("source_scope_instance_id", task["instance_id"]))
        end = max(a["end"] for a in task["observed_process"])
        # The observed prefix belongs to a recorded task path, not a proof of causal necessity.
        refs = {
            a["id"] for a in bundle["atomic"]["atomic_actions"] if not a.get("inferred") and a["end"] <= end + 1e-6
        }
        task = _project(bundle, task, refs)
        task.setdefault("source_scope_instance_id", source_unit["instance_id"])
        task["instance_id"] = "task_" + digest(
            [task["video_uid"], task["goal_key"], task["bindings"], task["atomic_refs"]]
        )
        task["original_instance_scope"] = source_unit["instance_scope"]
        task["instance_scope"] = "purpose_task"
        task["learning_track"] = "same_goal_graphs"
        task["intent_contract"] = deepcopy(
            provided_goal
            or bundle.get("provided_task_contract")
            or {
                "goal_key": task["goal_key"],
                "intent_ids": task["intent_ids"],
                "origin": "video_scoped_intent_candidate",
            }
        )
        task["realization_label"] = " → ".join(n["name"] for n in task["operation_subgraph"]["nodes"])
        original_refs = set(source_unit["atomic_refs"])
        task["context_membership"] = [
            {
                "atomic_ref": r,
                "status": "goal_scoped_observation"
                if r in original_refs
                else "preceding_context_requires_relevance_review",
                "causal_necessity_verified": False,
            }
            for r in task["atomic_refs"]
        ]
        task["causal_audit_ref"] = "task_causal_audit.json"
        task["boundary"] = {
            "start_sec": min(a["start"] for a in task["observed_process"]),
            "end_sec": end,
            "context_end_sec": min(bundle["meta"]["duration"], end + 0.5),
        }
        for row in task.get("condition_observations", []):
            row["instance_id"] = task["instance_id"]
        purpose.append(task)
    local = [
        deepcopy(i)
        for i in units
        if i["instance_id"] not in source_ids
        and i.get("instance_scope") not in {"provided_task", "skill_episode"}
        and i["goal_key"] != "grasp_object"
    ]
    local.extend(deepcopy(episodes))
    local = list({u["instance_id"]: u for u in local}.values())
    for unit in local:
        unit["learning_track"] = "classified_skill_clips"
        unit["parent_task_refs"] = [
            p["instance_id"] for p in purpose if set(unit["atomic_refs"]) <= set(p["atomic_refs"])
        ]
        core = set(unit.get("core_atomic_refs", unit["atomic_refs"]))
        acts = [a for a in unit["observed_process"] if a["id"] in core and not a.get("inferred")]
        unit["classification"] = {
            "goal_key": unit["goal_key"],
            "basis": "local_intent_and_expected_effect_not_parent_task_outcome",
            "template_ref": "goal/" + unit["goal_key"],
            "atomic_refs": sorted(core),
            "clip_start_sec": min((a["start"] for a in acts), default=None),
            "clip_end_sec": max((a["end"] for a in acts), default=None),
            "process_context_refs": unit["atomic_refs"],
            "status": "candidate_requires_local_effect_review",
        }
    causal["observed_order_only_edges"] = [
        {"instance_id": t["instance_id"], **deepcopy(e)}
        for t in purpose
        for e in t["operation_subgraph"]["relations"]
        if e.get("basis") == "observed_order"
    ]
    task_case = _filtered(original, purpose)
    task_case["observations"] = [deepcopy(o) for t in purpose for o in t.get("condition_observations", [])]
    clip_case = _filtered(original, local)
    clip_case["observations"] = [
        deepcopy(o) for t in local for o in t.get("condition_observations", [])
    ] or clip_case["observations"]
    classification_index = [
        {
            "instance_id": u["instance_id"],
            "video_uid": u["video_uid"],
            "outcome": u["outcome"],
            "outcome_status": u["outcome_status"],
            "parent_task_refs": u["parent_task_refs"],
            **u["classification"],
        }
        for u in local
    ]
    return {
        "schema_version": "learning_tracks.v1",
        "purpose_case": task_case,
        "clip_case": clip_case,
        "classification": classification_index,
        "task_causal_audit": causal,
        "unresolved_goal": bool(provided_goal and not purpose),
        "policy": "Whole same-purpose paths and local classified skill trials remain separate; preparation context is not necessity proof.",
    }


def apply_reviewed(tracks, reviewed):
    """Carry explicit human reviews into derived scopes without changing the reviewed goal."""
    for track in tracks:
        for key in ["purpose_case", "clip_case"]:
            case = track[key]
            extra = []
            for unit in case["instances"]:
                changed_goal = unit.get("alternative_model_scope", {}).get("goal_key") not in {None, unit["goal_key"]}
                ids = {unit["instance_id"], unit.get("atomic_instance_ref")}
                if not changed_goal:
                    ids.add(unit.get("source_scope_instance_id"))
                for row in reviewed:
                    if row["instance_id"] not in ids:
                        continue
                    if row.get("outcome_review"):
                        unit.setdefault("original_model_outcome", unit["outcome"])
                        unit.update(
                            outcome=row["outcome"],
                            outcome_status="reviewed_reference",
                            outcome_evidence=deepcopy(row["outcome_evidence"]),
                        )
                        unit["human_outcome_review"] = deepcopy(row)
                    if row.get("condition_key"):
                        observation = deepcopy(row)
                        phase = row.get("phase", "post" if row.get("at") == "post" else "entry")
                        if phase == "entry" and row["instance_id"] != unit["instance_id"]:
                            phase = "core_entry"
                        observation.update(
                            instance_id=unit["instance_id"],
                            video_uid=unit["video_uid"],
                            goal_key=unit["goal_key"],
                            phase=phase,
                            comparison_context=phase + "|" + unit["instance_scope"],
                            outcome=unit["outcome"],
                            outcome_evidence=deepcopy(unit["outcome_evidence"]),
                        )
                        extra.append(observation)
            case["observations"].extend(extra)
            for row in case["observations"]:
                unit = next((u for u in case["instances"] if u["instance_id"] == row["instance_id"]), None)
                if unit:
                    row.update(outcome=unit["outcome"], outcome_evidence=deepcopy(unit["outcome_evidence"]))
            # Both the graph inducer and the clip-pool view read the same reviewed observations.
            for unit in case["instances"]:
                unit["condition_observations"] = [
                    deepcopy(o) for o in case["observations"] if o["instance_id"] == unit["instance_id"]
                ]
        by_id = {u["instance_id"]: u for u in track["clip_case"]["instances"]}
        for row in track["classification"]:
            unit = by_id[row["instance_id"]]
            row.update(outcome=unit["outcome"], outcome_status=unit["outcome_status"])
    return tracks

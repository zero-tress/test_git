"""Goal/effect-based cross-video induction with object-specific task families and realizations."""
from __future__ import annotations

import hashlib
import html
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from .condition_induction import induce
from .goal_semantics import GOALS, LEAF_GOALS, contract


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()[:20]


def video_identity(bundle: dict) -> tuple[str, str]:
    if bundle.get("source_video_sha256"):
        return bundle["source_video_sha256"], "video_bytes_sha256"
    p = Path((bundle.get("meta") or {}).get("path") or "")
    if p.is_file():
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest(), "video_bytes_sha256"
    # No filename-based UID. This fallback deduplicates identical observations only.
    return digest((bundle.get("atomic") or {}).get("atomic_actions") or []), "observation_fingerprint_only"


def extract(bundle: dict, source: str) -> dict:
    uid, identity_kind = video_identity(bundle)
    actions = {a["id"]: a for a in (bundle.get("atomic") or {}).get("atomic_actions") or []}
    nodes = (bundle.get("task_nodes") or {}).get("task_nodes") or []
    scopes = deepcopy((bundle.get("semantic_scope") or {}).get("subtasks") or [])
    labels = {o["label"]: o for o in (bundle.get("semantic_scope") or {}).get("objects") or []}
    for n in nodes:
        if n["name"] in LEAF_GOALS and n.get("atomic_refs") and n["tuple"].get("O"):
            for target in n["tuple"]["O"]:
                scopes.append({"id": "leaf_" + n["id"], "goal_key": LEAF_GOALS[n["name"]],
                               "target": target, "atomic_refs": n["atomic_refs"],
                               "intent_ids": [], "confidence": None, "outcome": "unknown",
                               "realization": "单节点抓取", "origin": "semantic_leaf_projection"})
    instances, unresolved, observations = [], [], []
    for s in scopes:
        goal, target = s.get("goal_key"), s.get("target")
        refs = sorted(set(s.get("atomic_refs") or []),
                      key=lambda r: (actions.get(r, {}).get("start", 0), str(r)))
        selected = [actions[r] for r in refs if r in actions]
        if goal not in GOALS or not target or not selected:
            unresolved.append({"scope": s, "reason": "unresolved_goal_target_or_actions"})
            continue
        identity = digest([uid, goal, target, refs])
        local_nodes = [n for n in nodes if set(n.get("atomic_refs") or []) & set(refs)]
        local_ids = {n["id"] for n in local_nodes}
        projected = [{"node_id": n["id"], "name": n["name"],
                      "selected_atomic_refs": [r for r in n.get("atomic_refs", []) if r in refs],
                      "partial_node": bool(set(n.get("atomic_refs") or []) - set(refs))}
                     for n in local_nodes]
        category = labels.get(target, {}).get("category", "unknown")
        # Target entities are local to a video. Sharing category never shares identity.
        instance = {"instance_id": identity, "video_uid": uid, "identity_kind": identity_kind,
                    "source": source, "subtask_id": s["id"], "goal_key": goal,
                    "target": {"local_entity": target, "category": category},
                    "bindings": {"target": target, "destination": s.get("destination")},
                    "expected": contract(goal), "intent_ids": s.get("intent_ids") or [],
                    "confidence": s.get("confidence"), "outcome": s.get("outcome", "unknown"),
                    "outcome_evidence": s.get("outcome_evidence") or [],
                    "outcome_status": "model_grounded_candidate" if s.get("outcome_evidence") else "unverified",
                    "atomic_refs": refs, "observed_process": deepcopy(selected),
                    "observation_quality": "contains_inferred_steps" if any(a.get("inferred") for a in selected) else "model_extracted_observations",
                    "operation_subgraph": {"nodes": projected, "relations": [
                        deepcopy(e) for e in (bundle.get("operations") or {}).get("edges") or []
                        if e["from"] in local_ids and e["to"] in local_ids]},
                    "realization_label": s.get("realization", ""),
                    "preparation_for": s.get("preparation_for") or [],
                    "causal_status": s.get("causal_status", "hypothesis"),
                    "candidate_conditions": [deepcopy(r) for r in bundle.get("learning_alignment", {}).get("records", [])
                                             if r.get("node_id") in local_ids and r["kind"] in {"C_pre", "C_post", "C_const"}]}
        effect_issues = []
        if goal == "acquire_object" and not any(n["name"] == "移动" for n in local_nodes):
            effect_issues.append("acquisition_scope_has_no_transport_or_lift_transition")
        if goal in {"relocate_object", "place_object"} and (
                not s.get("destination") or "画面" in str(s.get("destination"))):
            effect_issues.append("physical_destination_not_grounded")
        instance["goal_effect_audit"] = {
            "status": "needs_review" if effect_issues else "candidate_requires_entailment_review",
            "issues": effect_issues, "policy": "A matching state quote does not alone prove every goal effect."}
        if effect_issues:
            instance["original_model_outcome"] = instance["outcome"]
            instance.update(outcome="unknown", outcome_evidence=[], outcome_status="unverified")
        if any(a.get("media_coverage_status") == "outside_decoded_coverage" for a in selected):
            instance["original_model_outcome"] = instance["outcome"]
            instance.update(outcome="unknown", outcome_evidence=[], outcome_status="unverified")
        instances.append(instance)
        for c in (bundle.get("semantic_scope") or {}).get("condition_observations") or []:
            if c.get("subtask_id") == s["id"]:
                observations.append({**deepcopy(c), "instance_id": identity, "video_uid": uid,
                                     "goal_key": goal, "outcome": instance["outcome"],
                                     "outcome_evidence": instance["outcome_evidence"],
                                     "provenance": "model_grounded_candidate"})
    from .semantic import validate as validate_case
    case_validation = bundle.get("validation") or validate_case(bundle)
    return {"video_uid": uid, "identity_kind": identity_kind, "case_validation": case_validation, "media_quality": bundle.get("meta", {}).get("media_quality", {}), "instances": instances,
            "unresolved": unresolved, "observations": observations,
            "video_intents": deepcopy(bundle.get("intents") or {}),
            "temporal_knowledge": deepcopy(bundle.get("temporal_knowledge") or {})}


def realization_signature(instance: dict) -> str:
    """Retain process differences while parameterizing side, target identity, and object category."""
    target = instance["target"]["local_entity"]
    process = []
    for a in instance["observed_process"]:
        text = str(a.get("action") or "")
        for word in sorted({target, str(a.get("object") or "")}, key=len, reverse=True):
            if word:
                text = text.replace(word, "$target")
        for part in ("左手", "右手"):
            text = text.replace(part, "$gripper")
        for part in ("左臂", "右臂"):
            text = text.replace(part, "$arm")
        process.append([a.get("functional_role", {}).get("function"), text, a.get("mode")])
    return digest(process)


def aggregate(cases: list[dict], reviewed: list[dict] | None = None) -> dict:
    instances, sources, unresolved, observations = {}, {}, [], []
    for case in cases:
        uid = case["video_uid"]
        if uid in sources:
            sources[uid].setdefault("alternate_analyses", []).append({
                "source_files": sorted({i["source"] for i in case["instances"]}),
                "case_validation": case.get("case_validation", {}),
                "policy": "First analysis selected; another analysis of identical video is not another demonstration."})
            continue
        sources.setdefault(uid, {"video_uid": uid, "identity_kind": case["identity_kind"],
                                "source_files": [], "case_validation": case.get("case_validation", {}),
                                "media_quality": case.get("media_quality", {}),
                                "intent_hypotheses": case["video_intents"],
                                "temporal_knowledge": case["temporal_knowledge"]})
        for instance in case["instances"]:
            if instance["source"] not in sources[uid]["source_files"]:
                sources[uid]["source_files"].append(instance["source"])
            instances.setdefault(instance["instance_id"], instance)
        unresolved.extend(case["unresolved"])
        observations.extend(case["observations"])
    # Reviewed rows must name actual loaded instances and evidence; validate in CLI.
    observations += deepcopy(reviewed or [])
    grouped, families = defaultdict(list), defaultdict(list)
    for item in instances.values():
        grouped[item["goal_key"]].append(item)
        families[(item["goal_key"], item["target"]["category"])].append(item)
    skills = []
    for goal, items in sorted(grouped.items()):
        methods = defaultdict(list)
        for item in items:
            methods[realization_signature(item)].append(item)
        realizations = []
        for key, members in sorted(methods.items()):
            realizations.append({"realization_id": "R_" + key, "label": members[0]["realization_label"],
                                 "instance_ids": [m["instance_id"] for m in members],
                                 "source_video_count": len({m["video_uid"] for m in members}),
                                 "object_categories": sorted({m["target"]["category"] for m in members}),
                                 "process_example": members[0]["observed_process"],
                                 "applicability": {"status": "candidate_conditions_require_contrast",
                                                  "by_instance": {m["instance_id"]: m["candidate_conditions"] for m in members}}})
        skills.append({**contract(goal), "skill_id": "skill_" + goal,
                       "source_video_count": len({m["video_uid"] for m in items}),
                       "object_categories": sorted({m["target"]["category"] for m in items}),
                       "instance_ids": [m["instance_id"] for m in items], "realizations": realizations,
                       "generalization_status": "cross_video_candidate" if len({m["video_uid"] for m in items}) > 1 else "single_video_candidate",
                       "schema_status": "seed_contract_with_learned_case_membership_and_realizations",
                       "causally_verified": False})
    from .general_graph import build as general_graph
    for skill in skills:
        skill["general_operation_graph"] = general_graph(skill, instances)
    result = {"schema_version": "goal_effect_knowledge.v1", "sources": list(sources.values()),
              "skills": skills, "instances": list(instances.values()),
              "task_families": [{"goal_key": goal, "object_category": cat,
                                "instance_ids": [m["instance_id"] for m in members],
                                "parent_skill_id": "skill_" + goal,
                                "status": "candidate"}
                               for (goal, cat), members in sorted(families.items())],
              "condition_induction": induce(observations), "unresolved": unresolved,
              "policy": {
                  "grouping": "local purpose and role-based expected effect; not video filename or whole-video similarity",
                  "identity": "object identities are video-local; category is a parameter",
                  "provenance": "seed goal contracts are declared; observed processes and memberships are induced",
                  "causality": "preceding another object's movement does not establish a prerequisite",
                  "selection": "no controller or execution-policy selection in the learning layer"}}
    result["validation"] = validate(result)
    return result


def validate(knowledge: dict) -> dict:
    errors = []
    instances = {i["instance_id"]: i for i in knowledge.get("instances", [])}
    source_ids = {s["video_uid"] for s in knowledge.get("sources", [])}
    for source in knowledge.get("sources", []):
        if source.get("case_validation", {}).get("passed") is False:
            errors.append("source case has invalid semantic graph")
    for item in instances.values():
        if item["video_uid"] not in source_ids:
            errors.append("instance references unknown source")
        if item["goal_key"] not in GOALS or item["expected"] != contract(item["goal_key"]):
            errors.append("instance goal/effect contract mismatch")
    for skill in knowledge.get("skills", []):
        for key in skill["instance_ids"]:
            if key not in instances or instances[key]["goal_key"] != skill["goal_key"]:
                errors.append("skill membership goal/effect mismatch")
        for realization in skill["realizations"]:
            for key in realization["instance_ids"]:
                if key not in skill["instance_ids"]:
                    errors.append("realization has unknown instance")
    for family in knowledge.get("task_families", []):
        for key in family["instance_ids"]:
            if key not in instances or instances[key]["target"]["category"] != family["object_category"]:
                errors.append("task family object mismatch")
    from .temporal_learning import has_path
    for skill in knowledge.get("skills", []):
        graph = skill.get("general_operation_graph") or {}
        node_ids = {n["id"] for n in graph.get("nodes", [])}
        paths = {p["realization_id"]: p for p in graph.get("alternatives", [])}
        for path in paths.values():
            hard = []
            for edge in path["relations"]:
                if edge["from"] not in node_ids or edge["to"] not in node_ids:
                    errors.append("general graph edge references unknown node")
                if edge["relation"] == "sequence":
                    if has_path(hard, edge["to"], edge["from"]):
                        errors.append("realization graph contains cycle")
                    hard.append(edge)
        for edge in graph.get("relations", []):
            if not edge.get("realization_guards") or any(g not in paths for g in edge["realization_guards"]):
                errors.append("general graph edge has unknown realization guard")
    try:
        import jsonschema
        schema = json.loads((Path(__file__).parent / "schemas/goal_effect_knowledge.schema.json").read_text())
        errors.extend(e.message for e in jsonschema.Draft7Validator(schema).iter_errors(knowledge))
    except (OSError, ImportError) as exc:
        errors.append("knowledge schema unavailable: " + str(exc))
    return {"passed": not errors, "errors": sorted(set(errors)),
            "semantic_success_verified": False}


def render(knowledge: dict) -> str:
    """Self-contained, escaped report for reviewing actual memberships and variant processes."""
    def esc(value):
        return html.escape(str(value))
    sections = []
    by_id = {i["instance_id"]: i for i in knowledge["instances"]}
    for skill in knowledge["skills"]:
        rows = []
        for iid in skill["instance_ids"]:
            item = by_id[iid]
            rows.append("<tr>" + "".join("<td>" + esc(v) + "</td>" for v in (
                Path(item["source"]).parent.name, item["target"]["local_entity"],
                item["target"]["category"], " → ".join(a["action"] for a in item["observed_process"]),
                item["outcome"], item["outcome_status"])) + "</tr>")
        sections.append(f"<section><h2>{esc(skill['name'])}</h2><p>{esc(skill['purpose'])} · "
                        f"{skill['source_video_count']}个视频 · {len(skill['realizations'])}种过程候选</p>"
                        "<table><tr><th>案例</th><th>对象</th><th>对象类</th><th>观察过程</th>"
                        "<th>结果标签</th><th>证据状态</th></tr>" + "".join(rows) + "</table></section>")
    summary = {"task_families": knowledge["task_families"],
               "conditions": [{k: v for k, v in c.items() if k != "examples"} for c in knowledge["condition_induction"]["conditions"]],
               "unresolved": knowledge["unresolved"], "validation": knowledge["validation"], "policy": knowledge["policy"],
               "full_provenance": "knowledge.json"}
    summary["media_quality"] = [{"source_files": r["source_files"], "quality": r.get("media_quality", {})}
                                for r in knowledge["sources"]]
    summary["goal_effect_issues"] = [{"instance_id": i["instance_id"], "target": i["target"],
                                    "audit": i["goal_effect_audit"]} for i in knowledge["instances"]
                                   if i["goal_effect_audit"]["issues"]]
    family_rows = []
    categories = {"pen": "笔", "cup": "杯", "bottle": "瓶", "box": "盒", "unknown": "未确认"}
    for family in knowledge["task_families"]:
        members = [by_id[i] for i in family["instance_ids"]]
        cells = (GOALS[family["goal_key"]]["name"], categories.get(family["object_category"], family["object_category"]),
                 len({i["video_uid"] for i in members}), len(members), "候选，需核验效果与适用条件")
        family_rows.append("<tr>" + "".join("<td>"+esc(c)+"</td>" for c in cells) + "</tr>")
    families = ("<section><h2>对象任务族</h2><p>按目标效果和对象类别比较；整段视频可包含多个子任务。</p>"
                "<table><tr><th>目标</th><th>对象类</th><th>视频数</th><th>实例数</th><th>状态</th></tr>"
                + "".join(family_rows) + "</table></section>")
    warnings = []
    for source in knowledge["sources"]:
        quality = source.get("media_quality", {})
        if quality and not quality.get("coverage_verified"):
            warnings.append("；".join(Path(f).parent.name for f in source["source_files"])
                            + "：源视频存在解码警告，尾部覆盖需复核。")
    for item in knowledge["instances"]:
        if item["goal_effect_audit"]["issues"]:
            warnings.append(item["target"]["local_entity"] + " / " + GOALS[item["goal_key"]]["name"]
                            + "：效果或物理终点证据不完整，已保留未知。")
    review_flags = "<section><h2>需复核项</h2><ul>" + "".join("<li>"+esc(w)+"</li>" for w in warnings) + "</ul></section>"
    data = json.dumps(summary, ensure_ascii=False, indent=2)
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>目的与效果语义归纳</title>'
            '<style>body{font:16px/1.7 system-ui;max-width:1400px;margin:36px auto;padding:0 24px;color:#172b4d;background:#f6f8fb}'
            'section{background:white;padding:24px;margin:20px 0;border-radius:12px}table{border-collapse:collapse;width:100%}'
            'td,th{border:1px solid #dbe2ed;padding:9px;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>按子任务目的与目标效果归纳</h1><p>任务、语义技能、实现过程分别保留。'
            '共同目标契约是显式词表；跨视频成员与过程来自案例。所有归纳保持候选状态，未知不当成功。</p>'
            + families + review_flags + "".join(sections) + "<details><summary>条件统计、来源摘要与待复核项（完整数据见knowledge.json）</summary><pre>"
            + esc(data) + "</pre></details></html>")

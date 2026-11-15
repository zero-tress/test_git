"""Auditable offline branch/function consolidation and evidence delivery."""
from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from .condition_induction import induce
from .cross_video_alignment import compatible
from .general_graph import build
from .goal_semantics import GOALS, contract
from .knowledge import realization_signature, validate
from .skill_tuple import export as export_tuples


def save(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def refine(saved):
    """Regroup every member by the strengthened signature, retaining old lineage."""
    result = deepcopy(saved)
    instances = {i["instance_id"]: i for i in result["instances"]}
    for skill in result["skills"]:
        grouped = defaultdict(list)
        old = {iid: r["realization_id"] for r in skill["realizations"] for iid in r["instance_ids"]}
        for iid in skill["instance_ids"]:
            if not compatible(instances[iid], skill):
                raise ValueError("Goal/effect conflict requires explicit review: " + iid)
            grouped[realization_signature(instances[iid])].append(instances[iid])
        rs = []
        for signature, members in sorted(grouped.items()):
            rs.append({"realization_id": "R_"+signature, "label": members[0]["realization_label"],
                       "instance_ids": [i["instance_id"] for i in members],
                       "source_video_count": len({i["video_uid"] for i in members}),
                       "object_categories": sorted({i["target"]["category"] for i in members}),
                       "process_example": deepcopy(members[0]["observed_process"]),
                       "previous_realization_ids": sorted({old[i["instance_id"]] for i in members}),
                       "applicability": {"status": "candidate_conditions_require_contrast",
                                         "by_instance": {i["instance_id"]: deepcopy(i["candidate_conditions"]) for i in members}}})
        skill["realizations"] = rs
        skill["general_operation_graph"] = build(skill, instances)
    result["validation"] = validate(result)
    if not result["validation"]["passed"]:
        raise ValueError(result["validation"]["errors"])
    return result


def consolidate(knowledge):
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    decisions, realizations, evidence, definitions = [], [], [], []
    graphs = {}
    local_observations = [deepcopy(e) for c in knowledge["condition_induction"]["conditions"] for e in c["examples"]]
    for skill in knowledge["skills"]:
        sid = skill["skill_id"]
        graph = skill["general_operation_graph"]
        graphs[sid] = graph
        definitions.append({**contract(skill["goal_key"]), "skill_id": sid,
                            "scope": "provided_task_and_local_skill_are_distinct",
                            "criterion": "all declared postconditions; evidence may remain unknown"})
        for iid in skill["instance_ids"]:
            i = instances[iid]
            decisions.append({"skill_id": sid, "instance_id": iid, "video_uid": i["video_uid"],
                              "decision": "candidate_member" if compatible(i, skill) else "conflict",
                              "basis": "declared_goal_and_postcondition_contract_with_video_local_roles",
                              "observed_effect_review": deepcopy(i.get("goal_effect_audit", {})),
                              "outcome": i["outcome"], "outcome_status": i["outcome_status"],
                              "semantic_entailment_verified": i.get("goal_effect_audit", {}).get("status") == "verified"})
        for r in skill["realizations"]:
            members = [instances[iid] for iid in r["instance_ids"]]
            paths = [p for p in graph["alternatives"] if p["realization_id"] == r["realization_id"]]
            capabilities = sorted({a.get("functional_role", {}).get("atomic_capability")
                                   for i in members for a in i["observed_process"]
                                   if a.get("functional_role", {}).get("atomic_capability")})
            functional_operations = sorted({n["name"] for i in members for n in i["operation_subgraph"]["nodes"]})
            conditions = induce([o for o in local_observations if o["instance_id"] in r["instance_ids"]])
            record = {"realization_id": r["realization_id"], "skill_id": sid,
                      "instance_ids": r["instance_ids"], "path_ids": [p["path_id"] for p in paths],
                      "implementation_subgraphs": [{"instance_id": i["instance_id"], **deepcopy(i["operation_subgraph"])} for i in members],
                      "required_capabilities": capabilities, "operations": functional_operations,
                      "capability_binding_status": "unbound", "goal_contract_compatible": all(compatible(i, skill) for i in members),
                      "effect_review_status": "needs_review",
                      "postconditions": deepcopy(skill["expected_effects"]),
                      "evaluator_ref": "eval_"+sid,
                      "candidate_conditions": deepcopy(r["applicability"]),
                      "observed_condition_contrasts": conditions,
                      "selection_guard": {"status": "unresolved", "truth": "U"},
                      "source_video_count": len({i["video_uid"] for i in members})}
            realizations.append(record)
            evidence.append({"skill_id": sid, "realization_id": r["realization_id"],
                             "condition_contrasts": conditions,
                             "unverified_node_conditions": deepcopy(r["applicability"]),
                             "policy": "A model counterfactual is not an observed negative trial."})
    unresolved = [d for d in decisions if not d["semantic_entailment_verified"]]
    for key in GOALS:
        if not any(d["goal_key"] == key for d in definitions):
            definitions.append({**contract(key), "observed_instance_count": 0, "status": "definition_only_not_learned"})
    return {"definitions": definitions, "graphs": graphs, "realizations": realizations,
            "merge_decisions": decisions, "condition_evidence": evidence,
            "unresolved_members": unresolved}


def graph_svg(graph):
    """Display the union, while all routing is restricted to stored complete paths."""
    nodes = graph["nodes"]
    edges = graph["relations"]
    level = {n["id"]: 0 for n in nodes}
    for _ in nodes:
        changed = False
        for e in edges:
            if e["relation"] == "sequence" and level[e["to"]] <= level[e["from"]]:
                level[e["to"]] = level[e["from"]]+1
                changed = True
        if not changed:
            break
    columns = defaultdict(list)
    for n in nodes:
        columns[level[n["id"]]].append(n)
    width = max(550, (max(level.values(), default=0)+1)*155)
    height = max(120, max((len(ns) for ns in columns.values()), default=1)*72+40)
    pos = {n["id"]: (20+column*155, 20+j*72) for column, ns in columns.items() for j, n in enumerate(ns)}
    rows = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" style="min-width:{width}px;max-height:900px" role="img" aria-label="带来源支路的通用操作图">',
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0L7 3L0 6" fill="#64748b"/></marker></defs>']
    for e in edges:
        x1, y1 = pos[e["from"]]
        x2, y2 = pos[e["to"]]
        guard = html.escape(" ".join(e["path_guards"]), quote=True)
        rows.append(f'<g data-paths="{guard}"><path d="M{x1+112} {y1+22} L{x2} {y2+22}" stroke="#64748b" fill="none" marker-end="url(#arrow)"/><text x="{(x1+x2+112)/2}" y="{(y1+y2)/2+16}" font-size="10">{html.escape("时序" if e.get("basis")=="observed_order" else e["relation"])}</text></g>')
    for n in nodes:
        x, y = pos[n["id"]]
        guard = html.escape(" ".join(n["path_guards"]), quote=True)
        rows.append(f'<g data-paths="{guard}"><rect x="{x}" y="{y}" width="112" height="46" rx="6" fill="#eff6ff" stroke="#2563eb"/><text x="{x+8}" y="{y+18}" font-size="13">{html.escape(n["operation"][:9])}</text><text x="{x+8}" y="{y+35}" font-size="9">{html.escape(n["actor_role"][:18])}</text></g>')
    return "\n".join(rows)+"</svg>"


def export(knowledge, out, clip_manifest=None):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = consolidate(knowledge)
    by_r = {r["realization_id"]: r for r in data["realizations"]}
    artifacts = export_tuples(knowledge, out)
    for s in artifacts["skill_tuples"]["skills"]:
        for r in s["R"]:
            detail = by_r[r["id"]]
            r.update(implementation_graph_ref=f'general_graphs/{s["skill_id"]}.json',
                     path_ids=detail["path_ids"], required_capabilities=detail["required_capabilities"],
                     capability_binding_status="unbound", effect_review_status=detail["effect_review_status"])
    save(out/"skill_tuples.json", artifacts["skill_tuples"])
    from .skill_library import export_learned
    export_learned(knowledge, artifacts["skill_tuples"], out)
    save(out/"skill_definitions.json", data["definitions"])
    save(out/"functional_realizations.json", data["realizations"])
    save(out/"merge_decisions.json", data["merge_decisions"])
    save(out/"condition_evidence.json", data["condition_evidence"])
    for sid, graph in data["graphs"].items():
        save(out/"general_graphs"/(sid+".json"), graph)
        (out/"general_graphs"/(sid+".svg")).write_text(graph_svg(graph))
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    clips = {}
    clip_root = None
    if clip_manifest:
        clip_manifest = Path(clip_manifest).resolve()
        clip_root = clip_manifest.parent
        cm = json.loads(clip_manifest.read_text())
        allowed = {s["video_uid"] for s in knowledge["sources"]}
        for row in cm["instances"]:
            if row["kind"] == "skills" and row["video_uid"] in allowed:
                clips[row["instance_id"]] = {**row, "clip_root": str(clip_root)}
    # New layout: each analysis owns clip/sequence.json. Read it directly when
    # no historical cross-video clip manifest has been supplied.
    for iid, item in instances.items():
        if iid in clips:
            continue
        case = Path(item.get("analysis_source", item["source"])).parent
        sequence = case/"clip/sequence.json"
        if not sequence.is_file():
            continue
        local = json.loads(sequence.read_text(encoding="utf-8"))
        if local["source_video"]["sha256"] != item["video_uid"]:
            raise ValueError("Case clip source identity mismatch: " + iid)
        matching = [r for r in local["clips"] if r["status"] == "exported"
                    and set(r["atomic_refs"]) & set(item["atomic_refs"])]
        clips[iid] = {"instance_id": iid, "case_id": local["source_video"]["name"],
                      "clip_root": str(case/"clip"), "boundary_status": "model_candidate_with_context",
                      "segments": [{"path": r["filename"], "start": r["source_start_sec"],
                                    "end": r["source_end_sec"], "atomic_refs": r["atomic_refs"]}
                                   for r in matching],
                      "case_workbench": str(case/"workbench.html")}
    evidence_index = []
    for iid, i in instances.items():
        clip = clips.get(iid)
        evidence_index.append({"instance_id": iid, "video_uid": i["video_uid"],
                               "analysis_source": i.get("analysis_source", i["source"]),
                               "operation_subgraph": i["operation_subgraph"], "atomic_refs": i["atomic_refs"],
                               "clip_segments": deepcopy(clip["segments"]) if clip else [],
                               "clip_root": str(clip.get("clip_root", clip_root)) if clip else None,
                               "outcome": i["outcome"], "outcome_status": i["outcome_status"],
                               "goal_effect_audit": i.get("goal_effect_audit", {})})
    save(out/"evidence_index.json", evidence_index)
    checked = sum(g["reconstruction_validation"]["instances_checked"] for g in data["graphs"].values())
    errors = [e for g in data["graphs"].values() for e in g["reconstruction_validation"]["errors"]]
    summary = {"source_videos": len(knowledge["sources"]), "skill_instances": len(instances),
               "skills": len(knowledge["skills"]), "realizations": len(data["realizations"]),
               "paths_checked": checked, "path_preservation_passed": not errors and checked == len(instances),
               "path_errors": errors, "clip_linked_instances": len(clips),
               "shared_nodes": sum(sum(len(n["source_instances"]) > 1 for n in g["nodes"]) for g in data["graphs"].values()),
               "shared_edges": sum(sum(len(e["path_guards"]) > 1 for e in g["relations"]) for g in data["graphs"].values()),
               "semantic_members_needing_review": len(data["unresolved_members"]),
               "confirmed_routing_guards": 0, "causally_verified": False,
               "validation_scope": "mechanisms_and_source_preservation_not_new_human_semantic_review"}
    save(out/"generalization_validation.json", summary)
    rows = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>支路与功能合并审阅</title>",
            "<style>body{font:16px system-ui;max-width:1200px;margin:32px auto;color:#1e293b}section{border-top:1px solid #ccc;padding:16px 0}.graph{overflow:auto}pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:12px}video{max-width:100%;width:480px}select{max-width:100%;padding:8px}a{color:#2563eb}</style>",
            "<h1>支路与功能合并审阅</h1><p>结构保留检查与语义审阅分别记录。条件未知、局部效果未确认时继续保留候选状态。</p>",
            "<pre>"+html.escape(json.dumps(summary, ensure_ascii=False, indent=2))+"</pre>"]
    for skill in knowledge["skills"]:
        sid, graph = skill["skill_id"], data["graphs"][skill["skill_id"]]
        rows.append("<section><h2>"+html.escape(skill["name"])+"</h2><p>目标效果："+html.escape(json.dumps(skill["expected_effects"], ensure_ascii=False))+"</p>")
        rows.append('<label>查看来源路径 <select onchange="selectPath(this)"><option value="">所有候选支路</option>')
        for p in graph["alternatives"]:
            iid = p["instance_ids"][0]
            label = f'{iid} · {instances[iid]["realization_label"]}'
            rows.append(f'<option value="{p["path_id"]}">{html.escape(label)}</option>')
        rows.append("</select></label><div class='graph'>"+graph_svg(graph)+"</div>")
        for r in skill["realizations"]:
            detail = by_r[r["realization_id"]]
            rows.append("<details><summary>"+html.escape(r["realization_id"]+" · "+r["label"])+"</summary>")
            rows.append("<p>能力待绑定；分支适用条件待确认。</p><pre>"+html.escape(json.dumps(detail, ensure_ascii=False, indent=2))+"</pre>")
            for iid in r["instance_ids"]:
                rows.append("<h3>来源实例 "+html.escape(iid)+"</h3>")
                c = clips.get(iid)
                if c:
                    for seg in c["segments"]:
                        url = quote(os.path.relpath(Path(c.get("clip_root", clip_root))/seg["path"], out).replace(os.sep, "/"), safe="/")
                        rows.append(f'<p>源视频 {c["case_id"]}，{seg["start"]:.3f}—{seg["end"]:.3f}秒；{html.escape(c["boundary_status"])}</p><video controls preload="none" src="{url}"></video>')
                rows.append("<p>结果："+html.escape(instances[iid]["outcome"])+"；审阅状态："+html.escape(instances[iid]["outcome_status"])+"</p>")
            rows.append("</details>")
        rows.append("</section>")
    rows.append("""<script>function selectPath(el){const p=el.value;el.closest('section').querySelectorAll('[data-paths]').forEach(n=>{n.style.opacity=!p||n.dataset.paths.split(' ').includes(p)?'1':'.12';});}</script></html>""")
    (out/"cross_video_review.html").write_text("\n".join(rows))
    return summary

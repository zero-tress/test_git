"""Task hypotheses contain coexisting subtasks; scores are independent assessments."""
from __future__ import annotations

import math
from copy import deepcopy

CHECK_KEYS = ("explains_graph", "achieves_intent", "state_consistency")
STATUSES = {"observed", "partially_observed", "not_observed", "not_applicable", "unknown"}


def items(payload):
    """Yield parent first and children in decomposition order, never ranked by score."""
    for task in payload.get("intents") or []:
        yield task
        yield from task.get("subtasks") or []


def score(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= 1)


def validate_intents(payload, *, require_hierarchy=False):
    tasks = payload.get("intents")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("intents 必须是非空数组")
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("任务意图必须是对象")
        children = task.get("subtasks")
        hierarchical = require_hierarchy or children is not None
        if hierarchical and (not isinstance(children, list) or not children):
            raise ValueError("每个总任务必须提供非空 subtasks 分解")
        for item in [task] + (children or []):
            if not isinstance(item, dict) or not str(item.get("statement") or "").strip():
                raise ValueError("每个总任务及子任务必须有 statement")
            if not score(item.get("confidence")):
                raise ValueError("每个总任务及子任务的 confidence 必须是有限的 0~1 数值")
            key = item.get("id")
            if hierarchical and (not isinstance(key, str) or not key.strip()):
                raise ValueError("层级意图必须有非空字符串 id")
            if key is not None:
                if not isinstance(key, str) or key in seen:
                    raise ValueError("总任务和子任务 id 必须全局唯一")
                seen.add(key)
            if item is not task:
                if item.get("parent_intent_id") != task.get("id"):
                    raise ValueError("子任务 parent_intent_id 必须引用所属总任务")
                if not isinstance(item.get("optional"), bool):
                    raise ValueError("子任务必须声明 optional")
                if item.get("subtasks"):
                    raise ValueError("当前契约仅支持总任务—子任务—操作三层")


def validate_updates(payload, intents, nodes, actions):
    """Require complete two-level audits and check evidence against each local scope."""
    tasks = intents.get("intents") or []
    children = {s["id"]: (t, s) for t in tasks for s in t.get("subtasks") or []}
    node_map = {n["id"]: n for n in nodes}
    action_map = {a["id"]: a for a in actions}
    hierarchical = bool(children)

    def rows(field, expected, child=False):
        updates = payload.get(field)
        if not isinstance(updates, list):
            raise ValueError(field + " 必须分别覆盖全部输入意图")
        seen = set()
        for row in updates:
            if not isinstance(row, dict):
                raise ValueError("置信度更新必须是对象")
            key = row.get("intent_id")
            if not isinstance(key, str) or key not in expected or key in seen:
                raise ValueError("意图更新引用未知或重复候选")
            seen.add(key)
            if not score(row.get("confidence")):
                raise ValueError("非法置信度")
            scope = set(action_map)
            if child:
                parent, subtask = children[key]
                if row.get("parent_intent_id") != parent["id"]:
                    raise ValueError("子任务更新引用错误的父任务")
                if row.get("status") not in STATUSES:
                    raise ValueError("子任务更新缺少合法观察状态")
                if row["status"] == "not_applicable" and not subtask["optional"]:
                    raise ValueError("必需子任务不能标记为 not_applicable")
                for field_name, valid, typ in (("node_refs", node_map, str),
                                                ("atomic_refs", action_map, int)):
                    refs = row.get(field_name)
                    if (not isinstance(refs, list)
                        or any(type(r) is not typ or r not in valid for r in refs)
                        or len(set(refs)) != len(refs)):
                        raise ValueError("子任务映射包含非法、重复或不存在的 " + field_name)
                nrefs, arefs = row["node_refs"], set(row["atomic_refs"])
                node_actions = {r for n in nrefs for r in node_map[n].get("atomic_refs") or []}
                if nrefs and arefs != node_actions:
                    raise ValueError("子任务 node_refs 与 atomic_refs 必须指向同一组操作证据")
                scope = arefs
                observed = {r for r in scope if not action_map[r].get("inferred")}
                if row["status"] in {"observed", "partially_observed"} and not observed:
                    raise ValueError("观察到的子任务必须引用实际观察操作")
                if row["status"] in {"not_observed", "not_applicable"} and (nrefs or arefs):
                    raise ValueError("未观察或不适用子任务不能绑定已发生操作")
            checks = row.get("checks")
            if not isinstance(checks, list) or len(checks) != 3:
                raise ValueError("每个总任务和子任务需要三项校验")
            if hierarchical and {c.get("check") for c in checks if isinstance(c, dict)} != set(CHECK_KEYS):
                raise ValueError("必须分别回答解释性、意图可实现性、状态一致性，不能重复同一问题")
            for check in checks:
                if not isinstance(check, dict) or check.get("verdict") not in {"yes", "partial", "no", "unknown"}:
                    raise ValueError("非法校验判定")
                refs = check.get("evidence_refs", [])
                if not isinstance(refs, list) or any(type(r) is not int or r not in scope for r in refs):
                    raise ValueError("校验引用不存在或超出子任务范围的动作")
                if hierarchical and check["verdict"] == "yes":
                    if not refs or not any(not action_map[r].get("inferred") for r in refs):
                        raise ValueError("肯定判定必须提供本范围内的观察证据")
        if seen != set(expected):
            raise ValueError("每个意图必须分别校验，不能丢弃低置信度候选或未观察子任务")

    if "intent_updates" in payload:
        rows("intent_updates", {t["id"] for t in tasks})
    elif hierarchical or len(tasks) > 1:
        raise ValueError("多个意图及层级意图不能使用单个更新值")
    if hierarchical:
        rows("subtask_updates", children, child=True)
    elif payload.get("subtask_updates"):
        raise ValueError("不能为不存在的子任务添加更新")


def export_hierarchy(bundle, idmap):
    """Resolve source mappings through graph splits/merges without changing source audits."""
    tasks = deepcopy((bundle.get("intents") or {}).get("intents") or [])
    final = (bundle.get("task_nodes") or {}).get("task_nodes") or []
    updates = {r["intent_id"]: r for r in (bundle.get("sync") or {}).get("subtask_updates") or []}
    source_to_final = (bundle.get("learning_alignment") or {}).get("source_to_final") or {}
    for task in tasks:
        for subtask in task.get("subtasks") or []:
            update = updates.get(subtask["id"], {})
            # Invalid/quarantined rows must never reappear as graph mappings.
            if subtask["id"] not in (bundle.get("intent_alignment") or {}).get("updated_ids", []):
                update = {}
            source_refs = update.get("node_refs") or []
            atomic_refs = update.get("atomic_refs") or []
            mapped = {f for s in source_refs for f in source_to_final.get(s, [])}
            if not source_refs and atomic_refs:
                mapped = {n["id"] for n in final if n.get("atomic_refs")
                          and set(n["atomic_refs"]) <= set(atomic_refs)}
            subtask["operation_mapping"] = {
                "source_node_refs": list(source_refs),
                "node_refs": [idmap[n["id"]] for n in final if n["id"] in mapped and n["id"] in idmap],
                "atomic_refs": list(atomic_refs),
                "status": update.get("status", "unknown"),
                "unmapped_source_refs": [s for s in source_refs if not source_to_final.get(s)],
            }
    return {"schema_version": "task_intent_hierarchy.v1", "tasks": tasks,
            "confidence_kind": "model_assessment_not_calibrated_probability",
            "policy": "Sibling subtasks coexist; missing operations are never fabricated."}

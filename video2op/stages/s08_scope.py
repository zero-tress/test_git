"""Identify goal-scoped subtasks; never classify a whole video by its filename."""
from __future__ import annotations

import json

from ..goal_semantics import GOALS
from .common import ValidationFailure, atomic_table

SYSTEM = """
你是视频操作知识的子任务语义对齐专家。严格JSON，只依据给出的观察，不依据文件名。
把整段任务、局部技能、实现方式分开。目标是以相同目的和目标效果聚合不同过程。
笔和杯子可以共享抓取对象；获取对象与搬移后放下具有不同完成效果。
一段视频可以包含多个对象和多个子任务，不能全部贴成拿笔。
先移杯再拿笔不证明移杯为拿笔必需；只有有因果证据才标preparation_for，否则独立保留。
不同对象不能共用一个target；抓取与移动必须引用同一个局部实体。
goal_key取：
grasp_object=建立稳定握持；
acquire_object=取得并持有目标且脱离原支撑；
relocate_object=到达目的位置，允许推/拉/抓持搬移，不要求最终持有或释放；
place_object=在目的位置得到支撑并释放；
clear_access=移障后目标可接近（必须有依据）；
open_object/close_object=目标打开/关闭；
unresolved=目的或对象无法确认。
目标效果是预期，不能据此标记成功；效果证据不清就写unknown。
为拿笔/拿杯等取得片段建立acquire_object子任务；单次搬移后放下也可另建relocate_object或place_object，
每个子任务只引用对应过程的动作，不把之前拿别的物体加入同一获取片段。
objects的label及aliases只能来自输入动作中的object；category如pen/cup/box/bottle/unknown。
object映射只是模型候选，不把同类对象合并为同一个实体。
输出：
{"objects":[{"label":"红笔","category":"pen","aliases":[]}],
 "subtasks":[{"id":"sub1","goal_key":"acquire_object","target":"红笔",
 "destination":null,"atomic_refs":[1,2,3],"intent_ids":["intent_1"],
 "confidence":0.8,"realization":"直接接近并抓取拿起",
 "outcome":"unknown","outcome_evidence":[],
 "preparation_for":[],"causal_status":"hypothesis","reason":"目标效果与片段对应理由"}],
 "condition_observations":[],"unresolved":[]}
outcome只能success/failure/not_executed/unknown。
outcome=success/failure必须提供直接状态证据，动作名与推断状态不算：
{"atomic_ref":2,"field":"state_after","quote":"输入中实际观察到的完整状态原文"}。
condition_observations可记录可观察条件，不允许编造未发生的失败：
{"subtask_id":"sub1","condition_key":"target_reachable","text":"目标在可抓取范围",
 "truth":"T","at":"pre",
 "evidence":[{"atomic_ref":1,"field":"state_before","quote":"完整状态原文"}]}
pre条件仅引用片段开始前的状态，post仅引用结束后的状态。无法确认填U或不填写。
未执行不是执行失败，不能从未执行推断条件为F；推理反例只留在条件假设分析中。
"""


def validate(payload: object, ctx: dict) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("subtasks"), list):
        raise ValidationFailure("scope requires subtasks array")
    actions = {a["id"]: a for a in ctx["atomic"]["atomic_actions"]}
    labels = {a.get("object") for a in actions.values() if a.get("object")}
    ids = set()
    for obj in payload.get("objects") or []:
        if obj.get("label") not in labels or any(a not in labels for a in obj.get("aliases", [])):
            raise ValidationFailure(f"object labels/aliases must reference observed local objects; allowed={sorted(labels)}; invalid={obj}")
    for s in payload["subtasks"]:
        if not s.get("id") or s["id"] in ids:
            raise ValidationFailure("subtask ids must be unique")
        ids.add(s["id"])
        if s.get("goal_key") not in {*GOALS, "unresolved"}:
            raise ValidationFailure("unknown goal_key")
        refs = s.get("atomic_refs")
        if not isinstance(refs, list) or not refs or any(r not in actions for r in refs):
            raise ValidationFailure("subtask must reference existing atomic actions")
        context_refs = s.get("context_atomic_refs", [])
        if (not isinstance(context_refs, list) or any(r not in actions for r in context_refs)
                or set(context_refs) & set(refs)):
            raise ValidationFailure(f"{s['id']}: context_atomic_refs must be existing actions disjoint from atomic_refs")
        if s.get("goal_key") in {"grasp_object", "acquire_object", "relocate_object", "place_object"}:
            mismatches = [{"atomic_ref": r, "object": actions[r]["object"]} for r in refs
                          if actions[r].get("object") and actions[r]["object"] != s.get("target")]
            if mismatches:
                raise ValidationFailure(
                    f"{s['id']}: target={s.get('target')}; single-target subtask includes another object in atomic_refs: "
                    f"{json.dumps(mismatches, ensure_ascii=False)}. "
                    "请由模型重新划分：本目标动作留atomic_refs；其他对象/位置的上下文动作保留context_atomic_refs或独立子任务；不可用上下文动作证明目标成功。")
        if s.get("target") not in labels:
            raise ValidationFailure("subtask target must be an observed local object")
        if s.get("outcome", "unknown") not in {"success", "failure", "not_executed", "unknown"}:
            raise ValidationFailure("invalid outcome")
        if s.get("outcome") in {"success", "failure"} and not s.get("outcome_evidence"):
            raise ValidationFailure("success/failure requires actual state evidence")
        end = max(actions[r]["end"] for r in refs)
        for ev in s.get("outcome_evidence") or []:
            _evidence(ev, actions)
            a = actions[ev["atomic_ref"]]
            if ev["atomic_ref"] not in refs or "after" not in ev["field"] or a["end"] < end:
                raise ValidationFailure("outcome evidence must describe the scoped final boundary")
        valid_intents = {i["id"] for i in (ctx.get("intents") or {}).get("intents") or []}
        if any(i not in valid_intents for i in s.get("intent_ids", [])):
            raise ValidationFailure("unknown intent reference")
    for s in payload["subtasks"]:
        if any(k not in ids or k == s["id"] for k in s.get("preparation_for", [])):
            raise ValidationFailure("invalid preparation subtask reference")
    for c in payload.get("condition_observations") or []:
        if c.get("subtask_id") not in ids or c.get("truth") not in {"T", "F", "U"}:
            raise ValidationFailure("invalid condition reference/truth")
        if c.get("at") not in {"pre", "post"} or not c.get("condition_key"):
            raise ValidationFailure("invalid condition phase/key")
        if c["truth"] != "U" and not c.get("evidence"):
            raise ValidationFailure("condition truth requires evidence")
        scope = next(s for s in payload["subtasks"] if s["id"] == c["subtask_id"])
        start = min(actions[r]["start"] for r in scope["atomic_refs"])
        end = max(actions[r]["end"] for r in scope["atomic_refs"])
        for ev in c.get("evidence") or []:
            _evidence(ev, actions)
            a = actions[ev["atomic_ref"]]
            time = a["start"] if "before" in ev["field"] else a["end"]
            if (c["at"] == "pre" and time > start) or (c["at"] == "post" and time < end):
                raise ValidationFailure("condition evidence outside its state boundary")


def _evidence(ev: dict, actions: dict) -> None:
    from ..evidence import observed_states
    if ev.get("atomic_ref") not in actions or ev.get("field") not in {
            "state_before", "state_after", "world_before", "world_after"}:
        raise ValidationFailure("invalid state evidence reference")
    a = actions[ev["atomic_ref"]]
    key = "state_before" if "before" in ev["field"] else "state_after"
    # Exact quotes and observed provenance required. No inherited or generated states.
    value = a.get(ev["field"])
    values = value if isinstance(value, list) else [value]
    if ev.get("quote") not in values or ev.get("quote") not in observed_states(a, key):
        raise ValidationFailure("quote is not an observed state")


def evidence_catalog(ctx):
    rows = {}
    for a in ctx["atomic"]["atomic_actions"]:
        if a.get("media_coverage_status") == "outside_decoded_coverage":
            continue
        for field in ("state_before", "state_after", "world_before", "world_after"):
            if a.get("inferred") or a.get(field + "_from", "observed") != "observed":
                continue
            values = a.get(field) or []
            if isinstance(values, str):
                values = [values]
            for index, quote in enumerate(values):
                if isinstance(quote, str) and quote:
                    key = f"a{a['id']}_{field}_{index}"
                    rows[key] = {"evidence_id": key, "atomic_ref": a["id"], "field": field, "quote": quote}
    return rows


def expand_evidence(payload, ctx):
    """Resolve finite evidence IDs; quarantine unsupported claims instead of fabricating text."""
    from copy import deepcopy
    catalog = evidence_catalog(ctx)
    diagnostics = payload.setdefault("evidence_diagnostics", [])
    def expand(rows):
        result = []
        for row in rows or []:
            key = row if isinstance(row, str) else row.get("evidence_id") if isinstance(row, dict) else None
            if key is not None:
                if key not in catalog:
                    raise ValidationFailure("unknown evidence_id")
                result.append(deepcopy(catalog[key]))
            elif isinstance(row, dict):
                _evidence(row, {a["id"]: a for a in ctx["atomic"]["atomic_actions"]})
                result.append(row)
            else:
                raise ValidationFailure("evidence must be a catalog ID")
        return result
    for scope in payload.get("subtasks", []):
        try:
            scope["outcome_evidence"] = expand(scope.get("outcome_evidence"))
            # Outcome evidence must describe this subtask's completion.
            actions = {a["id"]: a for a in ctx["atomic"]["atomic_actions"]}
            refs = scope.get("atomic_refs") or []
            end = max(actions[r]["end"] for r in refs if r in actions)
            for ev in scope["outcome_evidence"]:
                if ev["atomic_ref"] not in refs or "after" not in ev["field"] or actions[ev["atomic_ref"]]["end"] < end:
                    raise ValidationFailure("outcome is not supported at the final boundary")
        except (ValidationFailure, ValueError) as exc:
            diagnostics.append({"scope_id": scope.get("id"), "claim": deepcopy(scope.get("outcome_evidence")),
                                "reason": str(exc), "action": "outcome_kept_unknown"})
            scope["outcome"] = "unknown"
            scope["outcome_evidence"] = []
    candidates = payload.pop("condition_observations", [])
    payload["condition_observations"] = []
    validate(payload, ctx)
    for row in candidates:
        try:
            row["evidence"] = expand(row.get("evidence"))
            trial = {**payload, "condition_observations": [row]}
            validate(trial, ctx)
            payload["condition_observations"].append(row)
        except ValidationFailure as exc:
            diagnostics.append({"condition": deepcopy(row), "reason": str(exc),
                                "action": "excluded_from_observation_counts"})
    return payload


def run(client, ctx: dict) -> dict:
    user = json.dumps({"allowed_object_labels": sorted({a["object"] for a in ctx["atomic"]["atomic_actions"] if a.get("object")}),
                       "intents": ctx.get("intents", {}),
                       "nodes": ctx.get("task_nodes", {}),
                       "media_quality": ctx.get("meta", {}).get("media_quality", {}),
                       "evidence_catalog": evidence_catalog(ctx)}, ensure_ascii=False)
    user += "\\n独立动作证据：\\n" + atomic_table(ctx["atomic"]["atomic_actions"])
    system = SYSTEM + """
【证据引用协议更新，优先于上方旧例】
outcome_evidence和condition_observations.evidence只填写evidence_catalog中实际存在的evidence_id字符串数组。
例如["a3_world_after_0"]。不要手写quote或field，程序会从原观察恢复真实字段和原文。
objects.label、aliases和subtasks.target只能逐字选取allowed_object_labels，未参与动作的桌面区域仅可写destination，不注册为操作对象。
条件状态必须被对应状态直接支持，“放在桌面”不证明“可达”，“后来抓到了”不证明片段开始时已经可达。
单目标grasp_object/acquire_object/relocate_object/place_object的atomic_refs只含object与target逐字相同的目标动作（无object者可按证据保留）。
靠近容器、移动其他物体等上下文动作可以在context_atomic_refs数组引用，或者另建子任务；不把它们混进目标atomic_refs。
context_atomic_refs只保留来源上下文，不是目标动作、目标成功证据或必要因果条件，且不得与atomic_refs重叠。所有上下文动作必须引用已存在id。
"""
    result = client.ask(stage="s08_scope", system=system, user_text=user,
                        max_tokens=6000, validator=lambda p: expand_evidence(p, ctx))
    result["provenance"] = "vlm_scoped_candidate"
    for c in result.get("condition_observations") or []:
        c["provenance"] = "model_grounded_candidate"
        c["semantic_entailment_status"] = "model_assessment_requires_review"
        c.pop("reviewer", None)
    return result

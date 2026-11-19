#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""④ 正反例条件学习：C_pre / C_post 各配 正例、反例A（失败执行/执行后失败）、反例B（未执行/未达预期）。"""

from __future__ import annotations

import json

from ...abstraction import validate_semantics
from ...llm import VLMClient
from .common import ValidationFailure, atomic_table, load_prompt, require_keys

VALID_VERDICTS = {"有效", "部分有效", "无效或过度约束", "证据不足"}


def _validate(payload: object) -> None:
    require_keys(payload, ["condition_learning"], "conditions")
    cl = payload["condition_learning"]  # type: ignore[index]
    if not isinstance(cl, list) or not cl:
        raise ValidationFailure("condition_learning 必须是非空数组")


def _normalize(payload: dict) -> dict:
    out = []
    for item in payload.get("condition_learning", []) or []:
        if not isinstance(item, dict):
            continue
        node = {"node_id": str(item.get("node_id") or ""),
                "C_pre_learning": [], "C_post_learning": []}
        for key in ("C_pre_learning", "C_post_learning"):
            for entry in item.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                e = dict(entry)
                if e.get("verdict") not in VALID_VERDICTS:
                    e["verdict"] = "证据不足"
                for side in ("positive", "negative_a", "negative_b"):
                    v = e.get(side)
                    if isinstance(v, str):
                        e[side] = {"text": v, "reason": ""}
                    elif not isinstance(v, dict):
                        e[side] = {"text": "", "reason": ""}
                try:
                    e["confidence"] = round(max(0.0, min(1.0, float(e.get("confidence", 0.6)))), 2)
                except (TypeError, ValueError):
                    e["confidence"] = 0.6
                node[key].append(e)
        out.append(node)
    payload["condition_learning"] = out
    payload["effective_conditions_summary"] = [
        str(x) for x in (payload.get("effective_conditions_summary") or [])]
    payload["rejected_conditions"] = [
        x if isinstance(x, dict) else {"condition": str(x), "why": ""}
        for x in (payload.get("rejected_conditions") or [])]
    return payload



def condition_catalog(nodes: list[dict]) -> list[dict]:
    """Exact deduplication only within one node and one condition kind."""
    catalog = []
    for node in nodes:
        for kind in ("C_pre", "C_post"):
            seen = set()
            for condition in node.get("tuple", {}).get(kind) or []:
                condition = str(condition).strip()
                if not condition or condition in seen:
                    continue
                seen.add(condition)
                catalog.append({"id": f"c{len(catalog) + 1}", "node_id": node["id"],
                                "kind": kind, "condition": condition})
    return catalog


def expand_compact(payload: dict, catalog: list[dict], nodes: list[dict]) -> dict:
    """Validate complete coverage before expanding the compact wire format."""
    require_keys(payload, ["items"], "compact conditions")
    items = payload["items"]
    if not isinstance(items, list):
        raise ValidationFailure("items 必须为数组")
    expected = {c["id"]: c for c in catalog}
    by_id = {}
    for row in items:
        require_keys(row, ["id", "verdict", "positive", "negative_a", "negative_b",
                           "confidence"], "condition")
        cid = row["id"]
        if not isinstance(cid, str) or cid not in expected or cid in by_id:
            raise ValidationFailure("条件编号未知或重复")
        if row["verdict"] not in VALID_VERDICTS:
            raise ValidationFailure("条件判定非法")
        for side in ("positive", "negative_a", "negative_b"):
            pair = row[side]
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(isinstance(x, str) and x.strip() for x in pair)):
                raise ValidationFailure(f"{cid}.{side} 必须为[简短情形, 证据或推理依据]")
        if isinstance(row["confidence"], bool) or not isinstance(row["confidence"], (int, float)):
            raise ValidationFailure("confidence 必须是数值")
        if not 0 <= row["confidence"] <= 1:
            raise ValidationFailure("confidence 超出范围")
        by_id[cid] = row
    if set(by_id) != set(expected):
        raise ValidationFailure("缺少条件编号：" + ",".join(sorted(set(expected) - set(by_id))))
    validate_semantics(payload)
    learned = {n["id"]: {"node_id": n["id"], "C_pre_learning": [], "C_post_learning": []}
               for n in nodes}
    summary, rejected = [], []
    for cid, source in expected.items():
        row = by_id[cid]
        entry = {"condition": source["condition"], "verdict": row["verdict"],
                 "confidence": row["confidence"],
                 "evidence_kind": "model_counterfactual_review", "empirically_verified": False,
                 "positive": {"text": row["positive"][0], "evidence": row["positive"][1]},
                 "negative_a": {"text": row["negative_a"][0], "reason": row["negative_a"][1]},
                 "negative_b": {"text": row["negative_b"][0], "reason": row["negative_b"][1]}}
        learned[source["node_id"]][source["kind"] + "_learning"].append(entry)
        if row["verdict"] in ("有效", "部分有效"):
            summary.append(source["condition"])
        elif row["verdict"] == "无效或过度约束":
            rejected.append({"node_id": source["node_id"], "condition": source["condition"],
                             "why": row["negative_a"][1] + "；" + row["negative_b"][1]})
    return {"condition_learning": list(learned.values()),
            "effective_conditions_summary": list(dict.fromkeys(summary)),
            "rejected_conditions": rejected,
            "learning_status": "counterfactual_review_not_empirical_induction"}


def run(client: VLMClient, ctx: dict) -> dict:
    nodes = ctx.get("task_nodes", {}).get("task_nodes", [])
    catalog = condition_catalog(nodes)
    if not catalog:
        return {"condition_learning": [], "effective_conditions_summary": [],
                "rejected_conditions": []}
    # Keep semantics from the original prompt, replace only its verbose wire schema.
    system = load_prompt("s04_conditions").split("【输出 JSON】", 1)[0]
    from ...abstraction import PROMPT_POLICY
    system += PROMPT_POLICY + """
【完整但紧凑的输出】
只分析给定目录中的条件，每个 id 必须恰好出现一次。不同节点即使条件同名也分别判定。
每个正反例只写一条必要短句；不能确认的正例明确写未观察到，推理反例不能冒充视频事实。
不满足条件不等于操作者绝不会尝试，区分不能成功与未发起。
返回 {"items":[{"id":"c1","verdict":"有效 | 部分有效 | 无效或过度约束 | 证据不足",
"positive":["情形短句","视频证据或未观察到"],
"negative_a":["情形短句","推理依据"],"negative_b":["情形短句","推理依据"],"confidence":0.5}]}。
不重复条件原文，不输出总结列表；程序按 id 还原原文和完整报告，不能遗漏条件。
"""
    user = json.dumps({
        "intents": ctx.get("intents", {}).get("intents", []),
        "nodes": [{"id": n["id"], "name": n.get("name"),
                   "constraints": n.get("tuple", {}).get("C_const", []),
                   "atomic_refs": n.get("atomic_refs", [])} for n in nodes],
        "conditions": catalog,
        "sync": ctx.get("sync", {}),
    }, ensure_ascii=False, separators=(",", ":"))
    user += "\n动作证据：\n" + atomic_table(ctx["atomic"]["atomic_actions"])
    payload = client.ask(
        stage="s04_conditions", system=system, user_text=user,
        validator=lambda value: expand_compact(value, catalog, nodes))
    return expand_compact(payload, catalog, nodes)

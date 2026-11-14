#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2b-3 任务级节点聚合（七元组）。

输入：已合并的原子动作表 + 视角/场景信息（文本调用，不再看视频）。
输出：3~8 个任务级节点，每个节点带完整七元组与 atomic_refs。
"""

from __future__ import annotations

from ..abstraction import validate_semantics
from ..llm import VLMClient
from ..vocab import IGNORED_PARTS
from .common import (
    ValidationFailure,
    atomic_table,
    expand_parts,
    fill,
    intents_table,
    load_prompt,
    normalize_part,
    parts_functions,
    require_keys,
)


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["task_nodes"], "task")
    nodes = payload["task_nodes"]  # type: ignore[index]
    if not isinstance(nodes, list) or not nodes:
        raise ValidationFailure("task_nodes 必须是非空数组")
    for i, n in enumerate(nodes):
        require_keys(n, ["id", "name", "tuple", "intent_role", "required_capabilities"], f"task_nodes[{i}]")
        if not isinstance(n["intent_role"], str) or not n["intent_role"].strip():
            raise ValidationFailure(f"task_nodes[{i}] 缺少操作目的")
        caps = n["required_capabilities"]
        if not isinstance(caps, list) or not caps or not all(isinstance(c, str) and c.strip() for c in caps):
            raise ValidationFailure(f"task_nodes[{i}] required_capabilities 必须是非空字符串数组")
        from ..semantic import canonical
        canonical(n["name"])
        actor = n.get("tuple", {}).get("X") or {}
        parts = actor.get("parts") or []
        if len(parts) != 1 or actor.get("subject") != parts[0]:
            raise ValidationFailure("一个节点只允许一个执行主体，X.subject 与唯一的 X.parts 一致；请拆开臂与手")
        allowed = ({"打开", "抓取", "释放"} if parts[0].endswith("手") else
                   {"靠近", "移动", "撤回", "推", "拉", "旋转", "按压"} if parts[0].endswith("臂") else
                   {"上升", "下降", "向目标移动", "移动"})
        if canonical(n["name"]) not in allowed:
            raise ValidationFailure("节点功能必须与唯一的臂/手/整体主体相符")
        if "整体" in parts and canonical(n["name"]) not in {"上升", "下降", "向目标移动", "移动"}:
            raise ValidationFailure("整体只表示垂直上升/下降及水平移动，不用于臂手操作")
        if set(parts) and set(parts) <= {"左手", "右手"} and canonical(n["name"]) in {"搬运", "接近", "撤回", "移动"}:
            raise ValidationFailure("空间移动由手臂承担，手负责张开、抓握、释放；不能把搬运全归给手")
        require_keys(n["tuple"], ["X", "O", "C_pre", "C_const", "E", "C_post", "R"],
                     f"task_nodes[{i}].tuple")


def _normalize(payload: dict) -> dict:
    """补齐 id、时间范围与默认字段，保证七元组结构完整。"""
    nodes = []
    for i, n in enumerate(payload.get("task_nodes", []) or []):
        n = dict(n)
        n.setdefault("id", f"node_{i + 1}")
        t = dict(n.get("tuple") or {})
        for key in ("C_pre", "C_const", "C_post"):
            v = t.get(key)
            t[key] = [v] if isinstance(v, str) else (v or [])
        r = t.get("R")
        if isinstance(r, str):
            t["R"] = [{"name": r, "origin": "observed", "steps": []}]
        elif isinstance(r, list):
            t["R"] = [x if isinstance(x, dict) else {"name": str(x), "origin": "observed", "steps": []}
                      for x in r]
        else:
            t["R"] = []
        e = t.get("E")
        if isinstance(e, list):
            t["E"] = {"process": e, "completion": []}
        elif not isinstance(e, dict):
            t["E"] = {"process": [], "completion": []}
        x = t.get("X")
        if isinstance(x, str):
            t["X"] = {"subject": x, "parts": []}
        elif isinstance(x, dict):
            # 头不参与操作：节点执行主体里不保留该部位
            x["parts"] = [p for p in expand_parts(x.get("parts") or [])
                          if normalize_part(str(p)) not in IGNORED_PARTS]
        o = t.get("O")
        t["O"] = [o] if isinstance(o, str) else (o or [])
        n["tuple"] = t
        tr = n.get("time_range")
        if isinstance(tr, list) and len(tr) == 2:
            try:
                n["time_range"] = [round(float(tr[0]), 2), round(float(tr[1]), 2)]
            except (TypeError, ValueError):
                n["time_range"] = None
        else:
            n["time_range"] = None
        refs = n.get("atomic_refs") or []
        n["atomic_refs"] = [int(r) for r in refs if str(r).isdigit()]
        nodes.append(n)
    payload["task_nodes"] = nodes
    from ..semantic import normalize_tasks
    return normalize_tasks(payload)


def run(client: VLMClient, ctx: dict) -> dict:
    meta = ctx["meta"]
    atomic = ctx["atomic"]
    viewpoint = ctx.get("viewpoint", {})
    system = load_prompt("s02c_task")
    user = fill(
        load_prompt("s02c_task", "user"),
        DURATION=f"{meta['duration']:.1f}",
        VIEWPOINT=viewpoint.get("label_cn", "未知"),
        SCENE=viewpoint.get("scene", ""),
        INTENTS=intents_table((ctx.get("intents") or {}).get("intents") or []),
        ATOMIC_TABLE=atomic_table(atomic["atomic_actions"]),
        PART_FUNCTIONS=parts_functions(),
    )
    def validate(payload: object) -> None:
        _validate(payload)
        valid_refs = {a["id"] for a in atomic["atomic_actions"]}
        ids = set()
        for node in payload["task_nodes"]:
            if not isinstance(node["id"], str) or node["id"] in ids:
                raise ValidationFailure("操作 id 必须是唯一字符串")
            ids.add(node["id"])
            refs = node.get("atomic_refs")
            if not isinstance(refs, list) or any(r not in valid_refs for r in refs) or (not refs and not (node.get("inferred") or node.get("origin") == "observed_state_goal")):
                raise ValidationFailure(f"{node['id']} 必须引用实际存在的动作 id")

    payload = client.ask(stage="s02c_task", system=system, user_text=user, validator=validate)
    return _normalize(payload)

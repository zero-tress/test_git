#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作依赖图（DAG，确定性）：把执行器级原子动作与它们之间的依赖组织成有向无环图。

节点 = 原子动作（哪个部位、什么时候、做了什么）。
边   = 依赖，取自时序关系中真正表达"谁必须先于谁"的三类：

    sequence        A 完成后 B 才开始
    maintain_until  A 持续保持，直到 B 发生
    enables         A 是 B 的前置条件（使能）

parallel / alternation 表达的是"同时 / 交替"，不是先后依赖：把它们画成边会让
整张图变成互相缠绕的网。它们只作为**布局约束**——并行/交替的动作被拉到同一列，
读图规则是"同一列 = 时间上并行或交替进行"。

"DAG"是机制保证而不是愿望：

  · 建图先做 DFS 回边检测，剔除会成环的边，记入 `dropped_edges`；
  · 分层用最长路径松弛；并行/交替只作为同层约束，且只对"硬边不可达"的对生效
    （否则会与先后依赖打架），层号只增不减；
  · 万一松弛未收敛，回退到纯依赖的最长路径分层，保证每条保留的边都从左指向右。

结果里 `layers` 一定有序无环，渲染可以直接按层排列，不必再判环。

结构进 result.json（机器可读），人看的是 render.dag_svg 画的图。
"""

from __future__ import annotations

from collections.abc import Iterator

DEP_RELATIONS = ("sequence", "enables", "maintain_until")
SOFT_RELATIONS = ("parallel", "alternation")
# 同一对节点有多条依赖边时，保留信息更强的一条
DEP_PRIORITY = {"enables": 0, "maintain_until": 1, "sequence": 2}


def _pick_edges(relations: list[dict], ids: set[int]) -> list[dict]:
    best: dict[tuple[int, int], dict] = {}
    for r in relations:
        rel = str(r.get("relation") or "")
        if rel not in DEP_RELATIONS:
            continue
        f, t = r.get("from"), r.get("to")
        if f not in ids or t not in ids or f == t:
            continue
        cur = best.get((f, t))
        if cur is None or DEP_PRIORITY[rel] < DEP_PRIORITY.get(str(cur.get("relation")), 9):
            best[(f, t)] = {
                "from": f,
                "to": t,
                "relation": rel,
                "note": str(r.get("note") or ""),
                "inferred_by": str(r.get("inferred_by") or "vlm_window"),
            }
    return list(best.values())


def _soft_pairs(relations: list[dict], ids: set[int]) -> list[tuple[int, int]]:
    """并行/交替对（布局约束：同层），去重后按 (小 id, 大 id) 返回。"""
    seen: set[tuple[int, int]] = set()
    for r in relations:
        if str(r.get("relation") or "") not in SOFT_RELATIONS:
            continue
        f, t = r.get("from"), r.get("to")
        if f not in ids or t not in ids or f == t:
            continue
        seen.add((min(f, t), max(f, t)))
    return sorted(seen)


def _back_edge_indices(order: list[int], edges: list[dict]) -> set[int]:
    """DFS 三色标记：指向"仍在递归栈里"的节点的边是回边（会成环）。"""
    adj: dict[int, list[tuple[int, int]]] = {i: [] for i in order}
    for idx, e in enumerate(edges):
        adj.setdefault(e["from"], []).append((e["to"], idx))
    color: dict[int, int] = dict.fromkeys(order, 0)
    back: set[int] = set()
    for root in order:
        if color.get(root):
            continue
        color[root] = 1
        stack: list[tuple[int, Iterator[tuple[int, int]]]] = [(root, iter(adj.get(root, [])))]
        while stack:
            u, it = stack[-1]
            pushed = False
            for v, idx in it:
                if color.get(v, 0) == 0:
                    color[v] = 1
                    stack.append((v, iter(adj.get(v, []))))
                    pushed = True
                    break
                if color.get(v) == 1:
                    back.add(idx)
            if not pushed:
                color[u] = 2
                stack.pop()
    return back


def _assign_layers(order: list[int], edges: list[dict],
                   soft: list[tuple[int, int]]) -> dict[int, int]:
    """层号（列号）：依赖边保证 to 至少比 from 深一层；并行/交替对向大取齐（同层）。

    退化情形（不收敛）时回退到纯依赖的最长路径分层：宁可放弃"并行同列"的观感，
    也不允许出现"边的方向反过来"的图。
    """
    layer: dict[int, int] = dict.fromkeys(order, 0)
    hard = [(e["from"], e["to"]) for e in edges]
    for _ in range(len(order) + 4):
        changed = False
        for u, v in hard:
            if layer[v] < layer[u] + 1:
                layer[v] = layer[u] + 1
                changed = True
        for u, v in soft:
            top = max(layer[u], layer[v])
            if layer[u] != top:
                layer[u] = top
                changed = True
            if layer[v] != top:
                layer[v] = top
                changed = True
        if not changed:
            return layer
    fallback: dict[int, int] = dict.fromkeys(order, 0)
    for _ in range(len(order) + 1):
        changed = False
        for u, v in hard:
            if fallback[v] < fallback[u] + 1:
                fallback[v] = fallback[u] + 1
                changed = True
        if not changed:
            break
    return fallback


def _reachable(edges: list[dict], src: int, dst: int) -> bool:
    """依赖子图里 src 能否走到 dst（用于判定并行/交替能否拉平）。"""
    adj: dict[int, list[int]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    seen = {src}
    stack = [src]
    while stack:
        u = stack.pop()
        if u == dst:
            return True
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return False


def _safe_soft(pairs: list[tuple[int, int]], edges: list[dict]) -> list[tuple[int, int]]:
    """只在两节点之间没有依赖路径时才允许"拉平到同层"，否则两者会互相打架。"""
    return [(u, v) for u, v in pairs
            if not _reachable(edges, u, v) and not _reachable(edges, v, u)]


def build(actions: list[dict], relations: list[dict]) -> dict:
    """构建操作依赖图：节点（带层号）+ 依赖边 + 剔除记录。"""
    if not actions:
        return {"nodes": [], "edges": [], "layers": [], "dropped_edges": [],
                "stats": {"nodes": 0, "edges": 0, "layers": 0, "dropped": 0, "soft": 0}}

    order = [int(a["id"]) for a in sorted(
        actions, key=lambda a: (float(a.get("start", 0)), float(a.get("end", 0)),
                                int(a.get("id", 0))))]
    ids = set(order)

    picked = _pick_edges(relations, ids)
    back = _back_edge_indices(order, picked)
    dropped = [e for i, e in enumerate(picked) if i in back]
    kept = [e for i, e in enumerate(picked) if i not in back]
    soft = _safe_soft(_soft_pairs(relations, ids), kept)
    layer = _assign_layers(order, kept, soft)
    # 层号归一化成 0..k-1，保证节点上的 layer 与 layers 数组完全对应
    used = sorted(set(layer.values()))
    remap = {v: i for i, v in enumerate(used)}
    layer = {k: remap[v] for k, v in layer.items()}

    amap = {int(a["id"]): a for a in actions}
    nodes = []
    for aid in order:
        a = amap[aid]
        nodes.append({
            "id": aid,
            "executor": str(a.get("executor") or ""),
            "action": str(a.get("action") or ""),
            "mode": str(a.get("mode") or ""),
            "start": round(float(a.get("start", 0)), 2),
            "end": round(float(a.get("end", 0)), 2),
            "inferred": bool(a.get("inferred")),
            "layer": int(layer[aid]),
        })

    grouped: dict[int, list[int]] = {}
    for n in nodes:
        grouped.setdefault(n["layer"], []).append(n["id"])
    layers = [grouped[c] for c in sorted(grouped)]

    return {
        "nodes": nodes,
        "edges": kept,
        "layers": layers,
        "dropped_edges": [dict(e, why="会成环的依赖边，已剔除以保证 DAG") for e in dropped],
        "stats": {
            "nodes": len(nodes),
            "edges": len(kept),
            "layers": len(layers),
            "dropped": len(dropped),
            "soft_pairs": len(soft),
        },
    }

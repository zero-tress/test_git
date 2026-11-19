"""Left-to-right layered layout for start→skill→gate→…→end flows.

The single-case operations.svg already draws operations as one long axis with
gates between them. G_case and the cross-video semantic graph show the same
kind of axis, so they get the same reading order: layers become columns and
land on the main lane unless a layer holds several nodes.
"""

from __future__ import annotations

from ..render import GS_GATE_HW, GS_H_GAP, GS_NODE_R, GS_START_R, GS_V_LANE


def _radius(node):
    return GS_START_R if node.get("kind") == "terminal" else GS_NODE_R


def _column_step(flow):
    widths = []
    for node in flow["nodes"]:
        widths.append(2 * GS_GATE_HW + 14 if node.get("kind") == "gate" else 2 * _radius(node))
    return max(widths, default=2 * GS_NODE_R) + GS_H_GAP + 34


def _layers(flow):
    nodes = {n["id"]: n for n in flow["nodes"]}
    succ, pred = {}, {}
    for edge in flow["edges"]:
        if edge["from"] in nodes and edge["to"] in nodes:
            succ.setdefault(edge["from"], []).append(edge["to"])
            pred.setdefault(edge["to"], []).append(edge["from"])
    indegree = {nid: len(pred.get(nid, [])) for nid in nodes}
    queue = [nid for nid, degree in indegree.items() if degree == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in succ.get(nid, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    layer = {}
    for nid in order:
        layer[nid] = max((layer[p] + 1 for p in pred.get(nid, []) if p in layer), default=0)
    # 环或未排到的节点放到最后一列，绝不隐藏
    tail = max(layer.values(), default=-1) + 1
    for nid in nodes:
        layer.setdefault(nid, tail)
    return layer, order


def _main_lane(flow, order, layer):
    """Prefer the path through most observed edges so branch prep stays off-axis."""
    rank = {}
    for nid in order:
        rank[nid] = layer[nid]
    best = {}
    for nid in order:
        best[nid] = (0, -1)
    for edge in flow["edges"]:
        left, right = edge["from"], edge["to"]
        if left not in rank or right not in rank:
            continue
        weight = 0 if edge.get("observed") else 1
        score = best[left][0] + weight
        # 分数相同取更长的链，避免把支路误当主轴
        if score < best[right][0] or (score == best[right][0] and rank[left] > best[right][1]):
            best[right] = (score, rank[left])
    return {nid: best[nid][0] for nid in rank}


def layout(flow):
    """Return positions and a frame; never add, remove, or merge graph elements."""
    nodes = {n["id"]: n for n in flow["nodes"]}
    if not nodes:
        return {}, {"width": 980, "height": 220, "columns": 0}
    layer, order = _layers(flow)
    cost = _main_lane(flow, order, layer)
    step = _column_step(flow)
    columns = {}
    for nid in order:
        columns.setdefault(layer[nid], []).append(nid)
    # 主轴放在最宽的一列的中点，避免长图上下留白失衡
    widest = max((len(ids) for ids in columns.values()), default=1)
    axis = GS_NODE_R + 40 + (widest - 1) * GS_V_LANE / 2
    positions = {}
    for col, ids in sorted(columns.items()):
        # 同层内按主路径代价排序：主路径节点优先落在主轴
        ids = sorted(ids, key=lambda nid: (cost[nid], nodes[nid].get("kind") != "skill", order.index(nid)))
        offsets = [0]
        for index in range(1, len(ids)):
            magnitude = (index + 1) // 2
            offsets.append(-magnitude if index % 2 else magnitude)
        for nid, offset in zip(ids, offsets):
            x = 100 + col * step
            y = axis + offset * GS_V_LANE
            positions[nid] = (x, y, "main" if offset == 0 else ("upper" if offset < 0 else "lower"))
    width = max(x for x, _, _ in positions.values()) + 100 + 60
    height = max(y for _, y, _ in positions.values()) + GS_NODE_R + 70
    top = min(y for _, y, _ in positions.values()) - GS_NODE_R - 40
    if top < 0:
        shift = -top
        positions = {nid: (x, y + shift, lane) for nid, (x, y, lane) in positions.items()}
        height += shift
    return positions, {"width": width, "height": height, "columns": max(columns) + 1}

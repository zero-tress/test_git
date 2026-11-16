"""Presentation-only branch layout using the single-case SVG visual constants."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import deque

from .render import GS_FONT, GS_GATE_HH, GS_GATE_HW, GS_H_GAP, GS_INK, GS_NODE_R, GS_START_R, GS_STYLE, GS_V_LANE

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _shortest(start, goal, successors, allowed=lambda edge: True):
    queue = deque([(start, [start])])
    while queue:
        node, path = queue.popleft()
        if goal(node):
            return path
        for edge in successors.get(node, []):
            if allowed(edge) and edge["to"] not in path:
                queue.append((edge["to"], [*path, edge["to"]]))
    return []


def layout(graph):
    """Choose coordinates from supplied topology; never add/remove/merge graph elements."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    if not nodes:
        return {}, {"width": 980, "height": 220, "main": []}
    successors = {}
    for edge in graph["edges"]:
        successors.setdefault(edge["from"], []).append(edge)
    main = _shortest(
        graph["start_node_id"],
        lambda i: i == graph["end_node_id"],
        successors,
        lambda e: e.get("gate_outcome") != "F",
    )
    if not main:
        main = _shortest(graph["start_node_id"], lambda i: i == graph["end_node_id"], successors)
    branches = []
    for edge in graph["edges"]:
        if edge.get("gate_outcome") != "F" or edge["from"] not in main or edge["to"] in main:
            continue
        walk = _shortest(edge["to"], lambda i: i in main, successors)
        if walk:
            branches.append((edge["from"], walk[:-1], walk[-1]))
    step = 2 * GS_NODE_R + GS_H_GAP
    main_y = GS_NODE_R + 40 + (len(branches) + 1) * GS_V_LANE if branches else GS_NODE_R + 40
    xs = {nid: 100 + i * step for i, nid in enumerate(main)}
    for exit_id, body, join_id in branches:
        horizontal = body[:-1] if body and nodes[body[-1]]["kind"] == "gate" else body
        extra = max(0, (len(horizontal) - 1) * step - (xs[join_id] - xs[exit_id]))
        if extra:
            for nid in main[main.index(join_id) :]:
                xs[nid] += extra
    positions = {nid: (xs[nid], main_y, "main") for nid in main}
    for branch_index, (exit_id, body, join_id) in enumerate(branches):
        upper = GS_NODE_R + 40 + branch_index * GS_V_LANE
        last_gate = bool(body and nodes[body[-1]]["kind"] == "gate")
        horizontal = body[:-1] if last_gate else body
        for i, nid in enumerate(horizontal):
            x = xs[exit_id] + (xs[join_id] - xs[exit_id]) * i / max(1, len(horizontal) - 1)
            positions.setdefault(nid, (x, upper, "upper"))
        if last_gate:
            positions.setdefault(body[-1], (xs[join_id], (upper + main_y) / 2, "upper"))
    # Additional model branches retain all nodes in separate lanes.
    for index, nid in enumerate(i for i in nodes if i not in positions):
        parents = [e["from"] for e in graph["edges"] if e["to"] == nid and e["from"] in positions]
        x = max([positions[p][0] + step for p in parents] or [100])
        positions[nid] = (x, main_y + (index + 1) * GS_V_LANE, "additional")
    width = max(x for x, y, lane in positions.values()) + GS_NODE_R + 55
    height = max(y for x, y, lane in positions.values()) + GS_NODE_R + 50
    return positions, {"width": width, "height": height, "main": main}


def _anchor(node, x, y, dx, dy):
    if node["kind"] == "gate":
        scale = 1 / (abs(dx) / GS_GATE_HW + abs(dy) / GS_GATE_HH) if dx or dy else 0
        return x + dx * scale, y + dy * scale
    radius = GS_START_R if node["kind"] == "terminal" else GS_NODE_R
    distance = math.hypot(dx, dy) or 1
    return x + radius * dx / distance, y + radius * dy / distance


def _text(parent, x, y, label, size=19):
    # Wrapping only; the displayed words are supplied by the deployed model.
    lines = str(label).splitlines()
    wrapped = []
    for line in lines:
        wrapped.extend(line[i : i + 7] for i in range(0, len(line), 7))
    start = y - (len(wrapped) - 1) * size * 0.64
    for i, line in enumerate(wrapped):
        t = ET.SubElement(
            parent,
            "text",
            {
                "x": f"{x:.1f}",
                "y": f"{start + i * size * 1.28:.1f}",
                "text-anchor": "middle",
                "dominant-baseline": "central",
                "font-size": str(size),
                "fill": GS_INK,
            },
        )
        t.text = line


def svg(graph):
    positions, frame = layout(graph)
    root = ET.Element(
        "svg",
        {
            "xmlns": SVG_NS,
            "width": str(int(frame["width"])),
            "height": str(int(frame["height"])),
            "viewBox": f"0 0 {frame['width']:.1f} {frame['height']:.1f}",
            "role": "img",
            "aria-label": graph["title"],
            "font-family": GS_FONT.replace("sans-serif", "'Droid Sans Fallback',sans-serif"),
            "style": "background:#fff",
        },
    )
    ET.SubElement(
        root,
        "rect",
        {"x": "0", "y": "0", "width": str(frame["width"]), "height": str(frame["height"]), "fill": "white"},
    )
    defs = ET.SubElement(root, "defs")
    marker = ET.SubElement(
        defs,
        "marker",
        {
            "id": "cross-arrow",
            "viewBox": "0 0 10 10",
            "refX": "9",
            "refY": "5",
            "markerWidth": "7",
            "markerHeight": "7",
            "orient": "auto-start-reverse",
        },
    )
    ET.SubElement(marker, "path", {"d": "M 0 0 L 10 5 L 0 10 z", "fill": GS_INK})
    if not positions:
        _text(root, 480, 110, "当前没有可纳入的成功流程", 20)
        return ET.tostring(root, encoding="unicode")
    nodes = {n["id"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        a, b = nodes[edge["from"]], nodes[edge["to"]]
        ax, ay, _ = positions[a["id"]]
        bx, by, _ = positions[b["id"]]
        sx, sy = _anchor(a, ax, ay, bx - ax, by - ay)
        tx, ty = _anchor(b, bx, by, ax - bx, ay - by)
        group = ET.SubElement(
            root, "g", {"class": "gs-line", "data-edge-id": edge["id"], "data-from": a["id"], "data-to": b["id"]}
        )
        style = "pending" if a["kind"] == "gate" and a["truth"] == "U" else "plain"
        color, dash, stroke = GS_STYLE[style]
        attrs = {
            "d": f"M {sx:.1f},{sy:.1f} L {tx:.1f},{ty:.1f}",
            "stroke": color,
            "stroke-width": str(stroke),
            "fill": "none",
            "marker-end": "url(#cross-arrow)",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        ET.SubElement(group, "path", attrs)
        label = edge.get("display_label", edge.get("label", ""))
        if label and edge.get("gate_outcome") is not None:
            lx, ly = (sx + tx) / 2, (sy + ty) / 2
            if abs(tx - sx) < 2:
                lx += 56
            else:
                ly -= 15
            text = ET.SubElement(
                group,
                "text",
                {
                    "x": f"{lx:.1f}",
                    "y": f"{ly:.1f}",
                    "text-anchor": "middle",
                    "font-size": "13",
                    "fill": GS_INK,
                    "stroke": "white",
                    "stroke-width": "5",
                    "paint-order": "stroke",
                },
            )
            text.text = label
    for node in graph["nodes"]:
        x, y, lane = positions[node["id"]]
        gate = node["kind"] == "gate"
        attrs = {
            "class": "gs-gate" if gate else "gs-node",
            "data-node-id": node["id"],
            "data-center-x": str(x),
            "data-center-y": str(y),
            "data-layout-lane": lane,
            "tabindex": "0",
        }
        attrs["data-gate" if gate else "data-op"] = node["id"]
        group = ET.SubElement(root, "g", attrs)
        title = ET.SubElement(group, "title")
        title.text = node["label"]
        if gate:
            ET.SubElement(
                group,
                "path",
                {
                    "d": f"M{x - GS_GATE_HW},{y} L{x},{y - GS_GATE_HH} L{x + GS_GATE_HW},{y} L{x},{y + GS_GATE_HH} Z",
                    "fill": "white",
                    "stroke": GS_INK,
                    "stroke-width": "3",
                },
            )
        else:
            radius = GS_START_R if node["kind"] == "terminal" else GS_NODE_R
            ET.SubElement(
                group,
                "circle",
                {
                    "cx": str(x),
                    "cy": str(y),
                    "r": str(radius),
                    "fill": "#f3f4f6" if node["kind"] == "terminal" else "white",
                    "stroke": GS_INK,
                    "stroke-width": "3",
                },
            )
        _text(group, x, y, node.get("display_label", node["label"]), 17 if gate else 20)
    return ET.tostring(root, encoding="unicode")

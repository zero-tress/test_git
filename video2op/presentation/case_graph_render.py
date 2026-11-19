"""绘制单视频特例图和实现子图，并提供 SVG 布局辅助函数。"""

from __future__ import annotations

import html
import unicodedata

from ..contracts.learning_contracts import graph_records


def _svg_text_width(text, size):
    """Conservative width estimate: CJK glyphs occupy one em, ASCII 0.55 em."""
    return sum(0 if unicodedata.combining(c) else
               size if unicodedata.east_asian_width(c) in {"W", "F"} else
               size * 0.55 for c in str(text))


def _svg_text_lines(text, size, max_width):
    """Wrap by estimated pixel advance, including mixed CJK/ASCII labels."""
    rows, current = [], ""
    for char in str(text):
        if char == "\n":
            rows.append(current)
            current = ""
        elif current and _svg_text_width(current + char, size) > max_width:
            rows.append(current)
            current = char
        else:
            current += char
    if current or not rows:
        rows.append(current)
    return rows


STATUS_TEXT = {"observed": "已观察", "candidate": "候选", "not_executed": "未执行"}
OUTCOME_TEXT = {"success": "成功", "failure": "失败", "not_executed": "未执行", "unknown": "未知"}
def _role_text(value):
    labels = {"role": "角色", "target": "目标", "object": "目标", "actor": "执行者", "subject": "执行者"}
    if isinstance(value, dict):
        return "；".join(f"{labels.get(key, key)}：{item}" for key, item in value.items()
                         if item not in (None, "", [], {}))
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value)
    return str(value or "")


def _sentences(values):
    if isinstance(values, str):
        values = [values]
    found = [str(value).strip() for value in values or [] if str(value).strip()]
    return "；".join(found) if found else "—"


def _evaluator(node):
    return node.get("E") if isinstance(node.get("E"), dict) else {}


def _operation_label(operations, ref):
    node = next((n for n in graph_records(operations.get("nodes") or []) if n.get("id") == ref), {})
    name = node.get("name") or ref
    if node.get("already_satisfied"):
        return f"{name}（状态已满足）"
    if node.get("inferred"):
        return f"{name}（推断）"
    return str(name)


def _operation_node(operations, ref):
    return next((n for n in graph_records((operations or {}).get("nodes") or []) if n.get("id") == ref), {})


def _operation_order(realization, operations):
    """Observed sequence order of one realization's operations; keeps all claimed steps."""
    if not operations:
        return list(realization.get("operation_refs") or [])
    known = {n.get("id") for n in graph_records(operations.get("nodes") or [])}
    claimed = [ref for ref in realization.get("operation_refs") or [] if ref in known]
    edges = {(e.get("from"), e.get("to")) for e in graph_records(operations.get("edges") or [])
             if e.get("relation") == "sequence" and e.get("from") in claimed and e.get("to") in claimed}
    order, pending = [], list(claimed)
    while pending:
        ready = [ref for ref in pending if not any(target == ref and source in pending for source, target in edges)]
        if not ready:
            ready = [pending[0]]
        order.extend(ready)
        pending = [ref for ref in pending if ref not in ready]
    return order


def _internal_order(node, operations):
    """Model-observed operation relations inside one realization, shown verbatim."""
    if not operations:
        return []
    edges = graph_records(operations.get("edges") or [])
    known = {n.get("id") for n in graph_records(operations.get("nodes") or [])}
    claimed = {ref for realization in node.get("R") or [] for ref in realization.get("operation_refs") or []}
    marks = {"parallel": "∥", "maintain_until": "⤳", "alternation": "⇄",
             "branch": "⑂", "synchronization": "⇉"}
    rows = []
    for edge in edges:
        kind = edge.get("relation")
        left, right = edge.get("from"), edge.get("to")
        if kind not in marks or left not in known or right not in known:
            continue
        # 只展示与本技能实现相关的操作关系；另一端可能是不参与语义技能的并发准备动作。
        if left not in claimed and right not in claimed:
            continue
        rows.append(f"{_operation_label(operations, left)} {marks[kind]} {_operation_label(operations, right)}")
    return rows


def _panel_rows(node, operations=None):
    """Seven-tuple rows rendered under each skill; model text is never rewritten."""
    evaluator = _evaluator(node)
    rows = [
        ("目的", str(node.get("purpose") or "—"), "#536579", 2),
        ("X", _role_text(node.get("X")) or "—", "#244a72", 1),
        ("O", _role_text(node.get("O")) or "—", "#244a72", 1),
        ("C_pre", _sentences(node.get("C_pre")), "#1b2e43", 3),
        ("C_const", _sentences(node.get("C_const")), "#1b2e43", 3),
        ("E 完成", _sentences(evaluator.get("completion")), "#3d5a78", 2),
        ("E 过程", _sentences(evaluator.get("process_constraint")), "#3d5a78", 2),
        ("E 适用", _sentences(evaluator.get("implementation_applicability")), "#3d5a78", 2),
        ("C_post", _sentences(node.get("C_post")), "#1b2e43", 3),
    ]
    internal = _internal_order(node, operations)
    if internal:
        rows.append(("实现偏序", "；".join(internal), "#17627a", 3))
    for realization in node.get("R") or []:
        rows.append((f'R {realization.get("id")}',
                     f'{realization.get("name")}（{realization.get("status")}）'
                     f'\n操作 {"、".join(realization.get("operation_refs") or []) or "—"}'
                     f'｜动作 {", ".join(map(str, realization.get("atomic_refs") or [])) or "—"}',
                     "#6a4a86", 3))
    return rows


def _limited_lines(text, size, max_width, max_lines):
    rows = _svg_text_lines(text, size, max_width)
    truncated = len(rows) > max_lines
    visible = rows[:max_lines]
    if truncated and visible:
        last = visible[-1]
        while last and _svg_text_width(last + "…", size) > max_width:
            last = last[:-1]
        visible[-1] = last + "…"
    return visible, truncated


def _node_title(node):
    evaluator = _evaluator(node)
    lines = [f'{node.get("id")} {node.get("name")}'
             f'（{STATUS_TEXT.get(node.get("status"), node.get("status"))} / '
             f'{OUTCOME_TEXT.get(node.get("outcome"), node.get("outcome"))}）',
             f'目的：{node.get("purpose")}',
             f'X 执行者：{_role_text(node.get("X"))}',
             f'O 对象：{_role_text(node.get("O"))}',
             f'C_pre 进入条件：{_sentences(node.get("C_pre"))}',
             f'C_const 过程约束：{_sentences(node.get("C_const"))}',
             f'E 完成：{_sentences(evaluator.get("completion"))}',
             f'E 过程：{_sentences(evaluator.get("process_constraint"))}',
             f'E 适用：{_sentences(evaluator.get("implementation_applicability"))}',
             f'C_post 预期效果：{_sentences(node.get("C_post"))}']
    for realization in node.get("R") or []:
        lines.append(f'R {realization.get("id")} {realization.get("name")}'
                     f'（{realization.get("status")}）操作 '
                     f'{"、".join(realization.get("operation_refs") or []) or "—"}；动作 '
                     f'{", ".join(map(str, realization.get("atomic_refs") or [])) or "—"}')
    lines.append(f'局部结果：{OUTCOME_TEXT.get(node.get("outcome"), node.get("outcome"))}；'
                 f'证据动作：{", ".join(map(str, node.get("evidence_refs") or [])) or "—"}')
    if node.get("reason"):
        lines.append(f'理由：{node.get("reason")}')
    return "\n".join(lines)


def _precedence_layers(ids, relations, kinds=("sequence", "branch")):
    """Topological layering over precedence relations; parallel keeps both in place."""
    layer = {ref: 0 for ref in ids}
    pairs = [(rel["from"], rel["to"]) for rel in relations if rel.get("relation") in kinds]
    for _ in range(len(ids) + 1):
        moved = False
        for left, right in pairs:
            if left in layer and right in layer and layer[right] < layer[left] + 1:
                layer[right] = layer[left] + 1
                moved = True
        if not moved:
            break
    return layer


def _sequence_reachable(edges, source, target):
    """True when a recorded chain of observed sequence edges connects the two."""
    adjacency = {}
    for edge in edges:
        if edge.get("relation") == "sequence":
            adjacency.setdefault(edge.get("from"), set()).add(edge.get("to"))
    seen, stack = set(), [source]
    while stack:
        current = stack.pop()
        for nxt in adjacency.get(current, ()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _operation_flow(node, operations):
    """One skill's full implementation: operations layered by observed sequence edges.

    Realizations of the same skill share one flow so that a hold spanning two
    realizations still shows up, exactly as the operations view draws it.
    """
    known = {n.get("id"): n for n in graph_records((operations or {}).get("nodes") or [])}
    ordered, owner = [], {}
    for realization in node.get("R") or []:
        for ref in realization.get("operation_refs") or []:
            if ref in known and ref not in owner:
                owner[ref] = realization.get("id")
                ordered.append(ref)
    all_edges = [e for e in graph_records((operations or {}).get("edges") or [])
                 if e.get("from") in known and e.get("to") in known]
    edges = [e for e in all_edges if e.get("from") in owner and e.get("to") in owner]
    # 分层用整张操作图：技能之间可能隔着被排除的节点（例如状态已满足的“打开”），
    # 只看技能内部会把这些步骤误判成并行。
    seq = [(e["from"], e["to"]) for e in all_edges if e.get("relation") == "sequence"]
    layer = {ref: 0 for ref in known}
    for _ in range(len(known) + 1):
        moved = False
        for left, right in seq:
            if layer[right] < layer[left] + 1:
                layer[right] = layer[left] + 1
                moved = True
        if not moved:
            break
    # 真正的并行（平行的两个操作）保持同列；其余按全局层次排序后压成紧凑列。
    levels = sorted({layer[ref] for ref in ordered})
    compact = {level: index for index, level in enumerate(levels)}
    columns = {}
    for ref in ordered:
        columns.setdefault(compact[layer[ref]], []).append(ref)
    return ordered, owner, edges, columns


def _skill_layers(nodes, relations):
    ids = [node["id"] for node in nodes]
    layer = _precedence_layers(ids, relations)
    columns = {}
    for ref in ids:
        columns.setdefault(layer[ref], []).append(ref)
    return columns


def _circled(n):
    from ..render import GS_CIRCLED

    return GS_CIRCLED[n - 1] if 1 <= n <= len(GS_CIRCLED) else str(n)


def _condition_truth(graph):
    """Per-skill C_pre truth summary for gate colouring; never invents a value."""
    rows = {}
    for obs in graph.get("condition_observations") or []:
        if obs.get("kind") == "C_pre":
            rows.setdefault(obs.get("skill_id"), []).append(obs.get("truth"))

    def truth(skill_id):
        values = rows.get(skill_id) or []
        if not values:
            return "U"
        if "F" in values:
            return "F"
        return "T" if all(value == "T" for value in values) else "U"

    return truth


def _visual_flow(graph):
    """Display-only 开始 → 技能 → 门控 → … → 结束 graph.

    The source G_case is never rewritten: gates are inserted only for drawing,
    and every branch label comes from a model-declared guard or gate_outcome.
    """
    nodes = graph.get("nodes") or []
    relations = graph.get("relations") or []
    if not nodes:
        return {"nodes": [], "edges": [], "start_node_id": "__start__", "end_node_id": "__end__"}, {}, []
    truth = _condition_truth(graph)
    skill_nodes = {node["id"]: node for node in nodes}
    ids = set(skill_nodes)
    visual_nodes = [
        {"id": "__start__", "kind": "terminal", "label": "开始", "truth": "U"},
        {"id": "__end__", "kind": "terminal", "label": "结束", "truth": "U"},
    ]
    for node in nodes:
        visual_nodes.append({"id": node["id"], "kind": "skill", "label": node.get("name") or node["id"],
                             "truth": truth(node["id"]), "detail": _node_title(node),
                             "occurrence": node.get("occurrence", "observed")})
    visual_edges, hold_edges, notes = [], [], {}
    gate_count = 0

    def new_gate(skill_id, extra=None):
        nonlocal gate_count
        gate_count += 1
        gate_id = f"__gate_{gate_count}__"
        skill = skill_nodes.get(skill_id) or {}
        lines = [f'门控 {_circled(gate_count)} · {truth(skill_id)}',
                 f'进入「{skill.get("name") or skill_id}」的 C_pre 候选（模型判断，非人工验收）']
        for text in skill.get("C_pre") or []:
            observed = next((row.get("truth") for row in graph.get("condition_observations") or []
                             if row.get("skill_id") == skill_id and row.get("kind") == "C_pre"
                             and row.get("text") == text), "U")
            lines.append(f'· [{observed}] {text}')
        lines.append("U 既不能当 T 放行，也不能当 F 判死；条件真值见 condition_observations。")
        visual_nodes.append({"id": gate_id, "kind": "gate", "label": f"门控 {_circled(gate_count)}",
                             "truth": truth(skill_id), "detail": chr(10).join(lines)})
        notes[gate_id] = {"skill_id": skill_id, "index": gate_count, **(extra or {})}
        return gate_id

    by_source = {}
    for rel in relations:
        by_source.setdefault(rel.get("from"), []).append(rel)
    for source, rows in by_source.items():
        if source not in ids:
            continue
        for rel in rows:
            if rel.get("to") not in ids:
                continue
            if rel.get("relation") == "maintain_until":
                hold_edges.append({"from": source, "to": rel["to"], "label": ""})
        rows = [rel for rel in rows if rel.get("to") in ids and rel.get("relation") != "maintain_until"]
        if not rows:
            continue
        branching = len(rows) > 1 and any(rel.get("relation") == "branch" for rel in rows)
        if branching:
            guarded = next((rel["to"] for rel in rows if skill_nodes[rel["to"]].get("C_pre")), None)
            gate_id = new_gate(guarded or source, {"branch": True})
            visual_edges.append({"from": source, "to": gate_id, "label": ""})
            for rel in rows:
                outcome = rel.get("gate_outcome")
                if outcome not in {"T", "F"}:
                    outcome = rel.get("guard_truth") if rel.get("guard_truth") in {"T", "F"} else None
                visual_edges.append({"from": gate_id, "to": rel["to"], "label": "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed",
                                     "detail": rel.get("guard") or ""})
            continue
        for rel in rows:
            target = rel["to"]
            outcome = rel.get("gate_outcome")
            if skill_nodes[target].get("C_pre"):
                gate_id = new_gate(target, {"relation": rel})
                visual_edges.append({"from": source, "to": gate_id, "label": ""})
                visual_edges.append({"from": gate_id, "to": target, "label": "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed",
                                     "detail": rel.get("guard") or ""})
            else:
                visual_edges.append({"from": source, "to": target,
                                     "label": rel.get("relation") or "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed"})
    incoming = {edge["to"] for edge in visual_edges}
    outgoing = {edge["from"] for edge in visual_edges}
    roots = [node["id"] for node in nodes if node["id"] not in incoming] or [nodes[0]["id"]]
    leaves = [node["id"] for node in nodes if node["id"] not in outgoing] or [nodes[-1]["id"]]
    for root in roots:
        visual_edges.append({"from": "__start__", "to": root, "label": "", "observed": True})
    for leaf in leaves:
        visual_edges.append({"from": leaf, "to": "__end__", "label": "", "observed": True})
    return ({"nodes": visual_nodes, "edges": visual_edges,
             "start_node_id": "__start__", "end_node_id": "__end__"}, notes, hold_edges)


def _edge_path(a, b):
    ax, ay = a
    bx, by = b
    if abs(ay - by) < 0.6 or abs(bx - ax) < 0.6:
        return f"M {ax:.1f},{ay:.1f} L {bx:.1f},{by:.1f}"
    mx = (ax + bx) / 2
    return f"M {ax:.1f},{ay:.1f} L {mx:.1f},{ay:.1f} L {mx:.1f},{by:.1f} L {bx:.1f},{by:.1f}"


def _draw_flow(parts, flow, notes, positions, header):
    """Start/gate/skill circles, black lines, branch labels and hover details."""
    from ..cross_video_render import _anchor

    by_id = {node["id"]: node for node in flow["nodes"]}
    for edge in flow["edges"]:
        left, right = by_id[edge["from"]], by_id[edge["to"]]
        if left["id"] not in positions or right["id"] not in positions:
            continue
        ax, ay, _ = positions[left["id"]]
        bx, by, _ = positions[right["id"]]
        sx, sy = _anchor(left, ax, ay, bx - ax, by - ay)
        tx, ty = _anchor(right, bx, by, ax - bx, ay - by)
        outcome = edge.get("gate_outcome")
        if left["kind"] == "gate":
            # 门控后面一律虚线：条件尚未在真实机器人上验证，不能画成已放行。
            dashed = True
        elif right["kind"] == "gate":
            dashed = edge.get("observed") is False or left.get("occurrence") == "rule_only"
        else:
            dashed = (edge.get("observed") is False or
                      edge.get("relation") in {"parallel", "alternation", "branch", "synchronization"})
        color = "#1a1a1a"
        skip = abs(tx - sx) > 330 and abs(sy - ty) < 0.6
        if skip:
            # 跨过中间步骤的分支边走上拱弧，避免与主轴连线重合而看不出分支。
            top = max(sy + header - 78, header + 18)
            attrs = (f'd="M {sx:.1f},{sy + header:.1f} C {sx:.1f},{top:.1f} '
                     f'{tx:.1f},{top:.1f} {tx:.1f},{ty + header:.1f}"')
        else:
            attrs = (f'd="M {sx:.1f},{sy + header:.1f} L {tx:.1f},{ty + header:.1f}"'
                     if abs(sy - ty) < 0.6 or abs(sx - tx) < 0.6 else
                     f'd="M {sx:.1f},{sy + header:.1f} L {(sx + tx) / 2:.1f},{sy + header:.1f} '
                     f'L {(sx + tx) / 2:.1f},{ty + header:.1f} L {tx:.1f},{ty + header:.1f}"')
        dash = ' stroke-dasharray="12 10"' if dashed else ""
        parts.append(f'<path {attrs} fill="none" stroke="{color}" stroke-width="3"{dash} '
                     f'marker-end="url(#gs-edge)"/>')
        label = edge.get("label") or ""
        if label:
            lx, ly = (sx + tx) / 2, (sy + ty) / 2 + header
            if abs(tx - sx) < 2:
                lx += 70
            else:
                ly -= 14
            text = label if len(label) <= 22 else label[:21] + "…"
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" font-size="13" '
                         f'fill="{color}" stroke="white" stroke-width="5" paint-order="stroke">'
                         f'{html.escape(text)}</text>')
    for node in flow["nodes"]:
        if node["id"] not in positions:
            continue
        x, y, lane = positions[node["id"]]
        y += header
        occurrence = node.get("occurrence", "observed")
        if node["kind"] == "gate":
            parts.append(f'<g class="gs-gate" data-gate="{html.escape(node["id"], quote=True)}">')
            parts.append(f'<title>{html.escape(node.get("detail") or node["label"])}</title>')
            hw, hh = 58, 46
            parts.append(f'<path d="M {x},{y - hh} L {x + hw},{y} L {x},{y + hh} L {x - hw},{y} Z" '
                         f'fill="#eff9f5" stroke="#159474" stroke-width="3.2"/>')
            parts.append(f'<text x="{x}" y="{y}" dominant-baseline="central" font-size="16" '
                         f'font-weight="650" fill="#176650" text-anchor="middle">'
                         f'{html.escape(node["label"])}</text>')
            parts.append('</g>')
            continue
        terminal = node["kind"] == "terminal"
        radius = 46 if terminal else 72
        stroke = "#1a1a1a" if terminal else ("#9aa7b6" if occurrence == "rule_only" else "#2363a0")
        fill = "#f3f4f6" if terminal else "#ffffff"
        dash = ' stroke-dasharray="10 7"' if occurrence == "rule_only" else ""
        parts.append(f'<g class="gs-node" data-skill="{html.escape(node["id"], quote=True)}">')
        parts.append(f'<title>{html.escape(node.get("detail") or node["label"])}</title>')
        parts.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{stroke}" '
                     f'stroke-width="3.5"{dash}/>')
        lines, _ = _limited_lines(str(node["label"]), 20, radius * 1.5, 2)
        base = y - (len(lines) - 1) * 12
        for index, line in enumerate(lines):
            parts.append(f'<text x="{x}" y="{base + index * 24}" font-size="20" font-weight="650" '
                         f'fill="#173754" text-anchor="middle" dominant-baseline="central">'
                         f'{html.escape(line)}</text>')
        parts.append('</g>')
        if occurrence == "rule_only":
            parts.append(f'<text x="{x}" y="{y + radius + 22}" font-size="12.5" fill="#7a869a" '
                         f'text-anchor="middle">规则补充 · 未直接观察</text>')


def _draw_hold(parts, hold_edges, positions, header):
    by_id = positions
    rows = 0
    for edge in hold_edges:
        if edge["from"] not in by_id or edge["to"] not in by_id:
            continue
        ax, ay, _ = by_id[edge["from"]]
        bx, by, _ = by_id[edge["to"]]
        lane = max(ay, by) + 110 + rows * 22
        parts.append(f'<g class="gs-hold"><title>{html.escape("效果持续到后序开始：" + edge["from"] + " → " + edge["to"])}</title>'
                     f'<path d="M {ax:.1f},{ay + header + 72:.1f} V {lane + header:.1f} '
                     f'H {bx:.1f} V {by + header + 72:.1f}" fill="none" stroke="#2f9e6f" '
                     f'stroke-width="2.4" stroke-dasharray="11 8" marker-end="url(#gs-edge)"/></g>')
        rows += 1
    return rows


def svg(graph, name="", operations=None):
    """Flow view: 开始 → 技能 → 门控 → … → 结束, with seven-tuple panels and realizations."""
    from .flow_layout import layout as _flow_layout

    nodes = graph.get("nodes") or []
    relations = graph.get("relations") or []
    task = graph.get("task_outcome") or {}
    column, margin, radius = 400, 90, 72
    panel_width, label_width = 366, 62
    value_width = panel_width - label_width - 24
    row_size, line_height = 13.5, 18
    header = 160

    flow, notes, hold_edges = _visual_flow(graph)
    positions, frame = (_flow_layout(flow) if flow["nodes"] else
                        ({}, {"width": 1180, "height": 238}))

    def row_height(text, max_lines):
        visible, _ = _limited_lines(text, row_size, value_width, max_lines)
        return row_size + (len(visible) - 1) * line_height

    def panel_height(node):
        return 58 + sum(row_height(text, limit) + 9 for _, text, _, limit in _panel_rows(node, operations)) + 8

    panel_h = max((panel_height(node) for node in nodes), default=120)
    panel_total = len(nodes) * (panel_width + 14) - 14 if nodes else 0
    width = max(frame["width"], panel_total + margin * 2, 1180)
    hold_rows = _draw_hold([], hold_edges, positions, header)
    flow_height = frame["height"] + hold_rows * 30 + 70
    panel_y = header + flow_height + 30
    sub_y = panel_y + panel_h + 42

    def flow_height_of(node):
        _, _, _, flow_columns = _operation_flow(node, operations)
        rows = max((len(refs) for refs in flow_columns.values()), default=1)
        return 62 + rows * 62 + 40

    sub_h = 64 + sum(flow_height_of(node) for node in nodes) + 12
    legend_y = sub_y + sub_h + 30
    height = legend_y + 210

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
             f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="\'Noto Sans CJK SC\',\'Microsoft YaHei\',sans-serif" role="img">',
             '<title>单视频特例知识 G_case</title>',
             '<defs>'
             '<marker id="gs-edge" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker>'
             '<marker id="gs-pending" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#966a12"/></marker>'
             '</defs><rect width="100%" height="100%" fill="#ffffff"/>']

    def label(x, y, text, *, size=16, max_width=270, count=3, fill="#1b2e43", weight="normal", anchor="start"):
        lines, truncated = _limited_lines(text, size, max_width, count)
        parts.append("<g>" + (f"<title>{html.escape(str(text))}</title>" if truncated else ""))
        for index, line in enumerate(lines):
            parts.append(f'<text x="{x}" y="{y + index * (size + 7)}" font-size="{size}" fill="{fill}" '
                         f'font-weight="{weight}" text-anchor="{anchor}">{html.escape(line)}</text>')
        parts.append("</g>")

    label(margin, 52, (name + " " if name else "") + "单视频特例知识 G_case｜技能 · 门控 · 七元组",
          size=32, max_width=width - margin * 2, count=1, fill="#18314b", weight="700")
    rule_only = sum(1 for node in nodes if node.get("occurrence") == "rule_only")
    label(margin, 88, f'模型 Qwen3.8-27B · {len(nodes)} 个语义技能 · {len(relations)} 条语义关系 · '
                      f'任务结果 {OUTCOME_TEXT.get(task.get("value"), task.get("value") or "未知")}'
                      + (f' · {rule_only} 个规则补充步骤' if rule_only else ''),
          size=17, max_width=width - margin * 2, count=1, fill="#536579")
    label(margin, 118, "任务判定理由：" + str(task.get("reason") or "未提供"),
          size=16, max_width=width - margin * 2, count=2, fill="#3f7fd0")

    if not nodes:
        parts.append(f'<rect x="{margin}" y="170" width="{width - margin * 2}" height="150" rx="18" '
                     f'fill="#f8fafc" stroke="#dbe4ef"/>')
        label(margin + 24, 220, "未获得足够证据建立语义技能；任务结果保持未知。", size=20,
              max_width=width - margin * 2 - 48, count=1)
        label(margin + 24, 256, "待解决：" + "；".join(map(str, graph.get("unresolved") or ["无"])),
              size=15, max_width=width - margin * 2 - 48, count=2, fill="#536579")
        parts.append('</svg>')
        return "".join(parts)

    parts.append(f'<rect x="{margin}" y="{header - 20}" width="{width - margin * 2}" '
                 f'height="{flow_height + 40}" rx="24" fill="#f7f9fc" stroke="#e0e7ef"/>')
    _draw_flow(parts, flow, notes, positions, header)
    _draw_hold(parts, hold_edges, positions, header)

    # ---- 七元组面板：每个技能一列，链路上的位置与面板解耦 ----
    start_x = max(margin, (width - panel_total) / 2) if nodes else margin
    for index, node in enumerate(nodes):
        x = start_x + index * (panel_width + 14)
        stroke = "#9aa7b6" if node.get("occurrence") == "rule_only" else "#2363a0"
        parts.append(f'<rect x="{x:.1f}" y="{panel_y}" width="{panel_width}" height="{panel_height(node)}" '
                     f'rx="14" fill="#f8fafc" stroke="#dbe4ef"/>')
        parts.append(f'<text x="{x + 16:.1f}" y="{panel_y + 27}" font-size="16" font-weight="700" '
                     f'fill="#173754">{html.escape(str(node.get("id")) + " " + str(node.get("name")))}</text>')
        parts.append(f'<text x="{x + panel_width - 16:.1f}" y="{panel_y + 27}" font-size="12.5" fill="{stroke}" '
                     f'text-anchor="end">{STATUS_TEXT.get(node.get("status"), node.get("status"))} · '
                     f'{OUTCOME_TEXT.get(node.get("outcome"), node.get("outcome"))}'
                     f'{" · 规则补充" if node.get("occurrence") == "rule_only" else ""}</text>')
        parts.append(f'<path d="M {x + 12:.1f} {panel_y + 38} H {x + panel_width - 12:.1f}" stroke="#dbe4ef"/>')
        cursor = panel_y + 50
        for label_text, text, color, limit in _panel_rows(node, operations):
            visible, _ = _limited_lines(text, row_size, value_width, limit)
            parts.append(f'<g><title>{html.escape(text)}</title>')
            parts.append(f'<text x="{x + 16:.1f}" y="{cursor + row_size}" font-size="{row_size}" '
                         f'font-weight="700" fill="#7a869a">{html.escape(label_text)}</text>')
            for line_index, line in enumerate(visible):
                parts.append(f'<text x="{x + 16 + label_width:.1f}" '
                             f'y="{cursor + row_size + line_index * line_height}" font-size="{row_size}" '
                             f'fill="{color}">{html.escape(line)}</text>')
            parts.append('</g>')
            cursor += row_height(text, limit) + 9

    # ---- 实现子图：语义技能的来源操作流（operations.svg 的车道布局）----
    parts.append(f'<rect x="{margin}" y="{sub_y}" width="{width - margin * 2}" height="{sub_h}" rx="18" '
                 f'fill="#fbfcfe" stroke="#e0e7ef"/>')
    label(margin + 24, sub_y + 30,
          "实现子图：操作节点、门控式先后与持续约束（按 operations.svg 车道布局；不是执行程序）",
          size=17, max_width=width - margin * 2 - 48, count=1, fill="#173754", weight="700")
    op_r, op_lane = 26, 62
    realization_colors = ["#6a4a86", "#2f7fa8", "#b26a00", "#a23b62", "#3b7a57"]
    color_of_r = {}
    for node in nodes:
        for index, realization in enumerate(node.get("R") or []):
            color_of_r[realization.get("id")] = realization_colors[index % len(realization_colors)]
    cursor_row = sub_y + 56
    for node in nodes:
        ordered, owner, flow_edges, flow_columns = _operation_flow(node, operations)
        lanes_here = max((len(refs) for refs in flow_columns.values()), default=1)
        if not ordered:
            parts.append(f'<text x="{margin + 24}" y="{cursor_row + 14}" font-size="13" font-weight="700" '
                         f'fill="#6a4a86">{html.escape(str(node.get("id")) + " " + str(node.get("name")))}</text>')
            parts.append(f'<text x="{margin + 340}" y="{cursor_row + 14}" font-size="12" fill="#9aa7b6">'
                         f'没有可追溯的操作节点</text>')
            cursor_row += 100
            continue
        spine_y = cursor_row + 62 + (lanes_here - 1) * op_lane
        parts.append(f'<text x="{margin + 24}" y="{cursor_row + 8}" font-size="13" font-weight="700" '
                     f'fill="#6a4a86">{html.escape(str(node.get("id")) + " " + str(node.get("name")))}</text>')
        for index, realization in enumerate(node.get("R") or []):
            c = color_of_r.get(realization.get("id"), "#7a869a")
            parts.append(f'<text x="{margin + 24 + index * 168}" y="{cursor_row + 26}" font-size="10.5" '
                         f'fill="{c}">{html.escape(str(realization.get("id")) + " " + str(realization.get("name") or ""))}</text>')
        columns_here = max(flow_columns) + 1 if flow_columns else 1
        step = min(210.0, max(96.0, (width - margin * 2 - 250) / max(columns_here, 1)))
        pos_of = {}
        for col, refs in sorted(flow_columns.items()):
            for index, ref in enumerate(refs):
                cx = margin + 200 + col * step + op_r
                cy = spine_y - (lanes_here - 1 - index) * op_lane if len(refs) > 1 else spine_y
                pos_of[ref] = (cx, cy)
                op = _operation_node(operations, ref)
                color = color_of_r.get(owner.get(ref), "#6a4a86")
                suffix = "（已满足）" if op.get("already_satisfied") else ("（推断）" if op.get("inferred") else "")
                parts.append(f'<g class="gs-op" data-op="{html.escape(str(ref), quote=True)}">')
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{op_r}" fill="#ffffff" stroke="{color}" '
                             f'stroke-width="2.4"/>')
                label_text = str(op.get("name") or ref) + suffix
                lines, _ = _limited_lines(label_text, 10.5, op_r * 1.55, 2)
                parts.append(f'<title>{html.escape(str(ref) + " " + label_text + " · " + str(owner.get(ref)))}</title>')
                for li, line in enumerate(lines):
                    ty = cy + (li - (len(lines) - 1) / 2) * 12 + 3.6
                    parts.append(f'<text x="{cx}" y="{ty}" font-size="10.5" fill="#2f2a3f" '
                                 f'text-anchor="middle">{html.escape(line)}</text>')
                parts.append('</g>')
        hold_lane = spine_y + (lanes_here - 1) * op_lane + op_r + 26
        shown = sorted(flow_columns.items())
        explicit = {(edge.get("from"), edge.get("to")) for edge in flow_edges}
        chain_edges = []
        for (_, left_refs), (_, right_refs) in zip(shown, shown[1:], strict=False):
            for left in left_refs:
                for right in right_refs:
                    if (left, right) in explicit:
                        continue
                    if _sequence_reachable(graph_records((operations or {}).get("edges") or []), left, right):
                        chain_edges.append({"from": left, "to": right, "relation": "chain"})
        for edge in flow_edges + chain_edges:
            left, right = edge.get("from"), edge.get("to")
            if left not in pos_of or right not in pos_of:
                continue
            kind = edge.get("relation")
            xa, ya = pos_of[left]
            xb, yb = pos_of[right]
            if kind in {"sequence", "chain"}:
                if xb <= xa + op_r:
                    continue
                dashed = ' stroke-dasharray="5 5"' if kind == "chain" else ""
                if abs(ya - yb) < 1:
                    parts.append(f'<path d="M {xa + op_r} {ya} L {xb - op_r} {yb}" fill="none" '
                                 f'stroke="#5b6b80" stroke-width="1.9"{dashed} marker-end="url(#gs-edge)"/>')
                else:
                    mid = (xa + xb) / 2
                    parts.append(f'<path d="M {xa + op_r} {ya} L {mid} {ya} L {mid} {yb} '
                                 f'L {xb - op_r} {yb}" fill="none" stroke="#5b6b80" stroke-width="1.9"{dashed} '
                                 f'marker-end="url(#gs-edge)"/>')
                if kind == "chain":
                    parts.append(f'<text x="{(xa + xb) / 2}" y="{min(ya, yb) - op_r + 4}" font-size="9.5" '
                                 f'fill="#9aa7b6" text-anchor="middle">经未显示的中间步骤</text>')
                continue
            if kind == "maintain_until":
                parts.append(f'<g class="gs-hold"><title>{html.escape("效果持续到后序开始：" + str(left) + " → " + str(right))}</title>'
                             f'<path d="M {xa} {ya + op_r} V {hold_lane} H {xb} V {yb + op_r}" fill="none" '
                             f'stroke="#2f9e6f" stroke-width="2.1" stroke-dasharray="8 6" '
                             f'marker-end="url(#gs-edge)"/></g>')
                continue
            if kind == "parallel":
                vertical = abs(xa - xb) < 1
                if vertical:
                    parts.append(f'<path d="M {xa} {ya + op_r} L {xb} {yb - op_r}" fill="none" stroke="#b26a00" '
                                 f'stroke-width="1.8" stroke-dasharray="5 4"/>')
                    parts.append(f'<text x="{xa + 10}" y="{(ya + yb) / 2 + 4}" font-size="10.5" fill="#b26a00">∥</text>')
                else:
                    parts.append(f'<path d="M {xa} {ya - op_r} C {xa} {ya - op_r - 26} {xb} {yb - op_r - 26} '
                                 f'{xb} {yb - op_r}" fill="none" stroke="#b26a00" stroke-width="1.8" '
                                 f'stroke-dasharray="5 4"/>')
                    parts.append(f'<text x="{(xa + xb) / 2}" y="{ya - op_r - 30}" font-size="10.5" '
                                 f'fill="#b26a00" text-anchor="middle">∥</text>')
                continue
            mark = {"alternation": "⇄", "branch": "⇂", "synchronization": "⇉"}.get(kind)
            if mark:
                parts.append(f'<text x="{(xa + xb) / 2}" y="{min(ya, yb) - op_r - 8}" font-size="10.5" '
                             f'fill="#966a12" text-anchor="middle">{html.escape(mark)}</text>')
        cursor_row += 62 + lanes_here * op_lane + 40
    if not nodes:
        parts.append(f'<text x="{margin + 26}" y="{sub_y + 74}" font-size="13" fill="#7a869a">'
                     f'没有语义技能，因此没有实现子图。</text>')

    # ---- 图例 ----
    parts.append(f'<rect x="{margin}" y="{legend_y}" width="{width - margin * 2}" height="158" rx="18" '
                 f'fill="#f8fafc" stroke="#e6ecf4"/>')
    legend_left = [
        "圆：语义技能实例；开始/结束固定画在链路两端",
        "菱形：技能 C_pre 进入条件门控；条件未知时连线为虚线",
        "实线＝已观察；虚线＝候选/规则补充；绿色虚线＝效果持续到后序开始",
    ]
    legend_right = [
        "面板：每个技能完整七元组 X · O · C_pre · C_const · E · C_post · R",
        "实现子图：同列车道上下堆叠＝并行，∥ 标注；持续约束绕行下方车道",
        "规则补充节点不计为已观察；局部结果与任务结果分开；控制器与检测器 unbound",
    ]
    for index, text in enumerate(legend_left):
        parts.append(f'<text x="{margin + 26}" y="{legend_y + 40 + index * 30}" font-size="15" fill="#334155">'
                     f'{html.escape(text)}</text>')
    for index, text in enumerate(legend_right):
        parts.append(f'<text x="{margin + 26}" y="{legend_y + 40 + index * 30}" font-size="15" fill="#334155" '
                     f'transform="translate({int((width - margin * 2) / 2)},0)">{html.escape(text)}</text>')
    label(margin + 26, legend_y + 142,
          "来源：" + str((graph.get("provenance") or {}).get("model") or "Qwen3.8-27B")
          + "；完整证据、条件真值与未决项见 G_case.json 与单视频工作台。",
          size=13, max_width=width - margin * 2 - 52, count=1, fill="#7a869a")
    parts.append('</svg>')
    return "".join(parts)

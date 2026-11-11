#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染层：把结果渲染成"人看的"页面（离线可看，无外部依赖）。

产物：
  · timeline.html / timeline.svg —— 执行器时间轴（按身体部位分行，含时序关系连线）
  · graph.svg                     —— 操作依赖图（DAG：节点=原子动作，边=先后/使能/保持依赖）
  · report.html                   —— 完整报告（意图 / 节点七元组 / 因果检验 / 条件学习 / 规则 / 校验）
  · 动作叙述（分部位 + 总览）由原子动作自动生成
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import logic as logic_mod
from . import program as program_mod
from .vocab import BODY_PARTS, RELATION_TEXT, REST_STATE, hold_category

# 配色
COLOR = {
    "transition": "#e08a2e",
    "motion": "#3f7fd0",
    "maintain": "#2f9e6f",
    "bg": "#ffffff",
    "line": "#d8dde5",
    "text": "#22272e",
    "muted": "#6b7280",
}
MODE_CN = {"transition": "建立/解除", "motion": "移动", "maintain": "保持"}
REL_COLOR = {
    "sequence": "#3f7fd0",
    "parallel": "#8b5cf6",
    "alternation": "#0891b2",
    "maintain_until": "#2f9e6f",
    "enables": "#b45309",
}


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


# ---------------------------------------------------------------
# 分部位动作叙述（自动生成，用户最关心的"手臂怎么动/手怎么动"）
# ---------------------------------------------------------------

def narrate_by_part(actions: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for a in actions:
        grouped.setdefault(str(a.get("executor") or "?"), []).append(a)
    order = {p: i for i, p in enumerate(BODY_PARTS)}
    out = []
    for part in sorted(grouped, key=lambda p: order.get(p, 99)):
        acts = sorted(grouped[part], key=lambda x: (x.get("start", 0), x.get("end", 0)))
        steps = []
        for a in acts:
            tag = []
            mode = str(a.get("mode"))
            tag.append(MODE_CN.get(mode, mode))
            if a.get("exerts_force"):
                role = a.get("force_role") or "给力"
                tag.append(f"持续{role}")
            if a.get("inferred"):
                tag.append("推理补全")
            until = a.get("until")
            until_text = until.get("text") if isinstance(until, dict) else until
            steps.append({
                "id": a.get("id"),
                "span": f"{a.get('start')}~{a.get('end')}s",
                "action": a.get("action"),
                "tags": tag,
                "object": a.get("object"),
                "state": f"{a.get('state_before') or '-'} → {a.get('state_after') or '-'}",
                "until": until_text,
                "reason": a.get("inference_reason"),
            })
        out.append({"part": part, "rest": REST_STATE.get(part, ""), "steps": steps})
    return out


def narrate_overall(tasks: dict | None, actions: list[dict]) -> str:
    if tasks and tasks.get("overall_flow"):
        return str(tasks["overall_flow"])
    return "；".join(f"{a.get('start')}s {a.get('executor')}{a.get('action')}" for a in actions[:5])


# ---------------------------------------------------------------
# 甘特图（SVG）
# ---------------------------------------------------------------

def gantt_svg(bundle: dict, width: int = 1240) -> str:
    actions = bundle.get("atomic", {}).get("atomic_actions", [])
    relations = bundle.get("relations", [])
    duration = float(bundle.get("meta", {}).get("duration") or 1.0)
    parts = [p for p in BODY_PARTS if any(a.get("executor") == p for a in actions)]
    parts += [p for p in {a.get("executor") for a in actions} if p not in parts]

    left, right, top = 96, 24, 46
    row_h = 30
    bar_h = 17
    plot_w = width - left - right
    height = top + row_h * len(parts) + 26

    def x_of(t: float) -> float:
        return left + max(0.0, min(1.0, t / duration)) * plot_w

    rows: dict[str, float] = {}
    svg: list[str] = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
               f'viewBox="0 0 {width} {height}" font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">')
    svg.append(f'<rect width="{width}" height="{height}" fill="{COLOR["bg"]}"/>')

    # 每行底纹与部位名
    for i, part in enumerate(parts):
        y = top + i * row_h
        rows[part] = y
        svg.append(f'<rect x="{left}" y="{y - 2}" width="{plot_w}" height="{row_h - 4}" '
                   f'fill="{"#f7f9fc" if i % 2 == 0 else "#ffffff"}"/>')
        svg.append(f'<text x="{left - 10}" y="{y + bar_h - 3}" font-size="13" text-anchor="end" '
                   f'fill="{COLOR["text"]}">{esc(part)}</text>')

    # 时间刻度
    step = max(1.0, round(duration / 10))
    t = 0.0
    while t <= duration + 1e-6:
        x = x_of(t)
        svg.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 22}" '
                   f'stroke="{COLOR["line"]}" stroke-dasharray="3 3"/>')
        svg.append(f'<text x="{x:.1f}" y="{top - 18}" font-size="11" text-anchor="middle" '
                   f'fill="{COLOR["muted"]}">{t:.0f}s</text>')
        t += step

    # 动作块
    rects: dict[int, tuple[float, float, float, float]] = {}
    for a in actions:
        part = a.get("executor")
        if part not in rows:
            continue
        y = rows[part]
        x0, x1 = x_of(float(a.get("start", 0))), x_of(float(a.get("end", 0)))
        w = max(3.0, x1 - x0)
        mode = str(a.get("mode"))
        fill = COLOR.get(mode, "#888")
        inferred = bool(a.get("inferred"))
        stroke = "#b45309" if inferred else "rgba(0,0,0,.18)"
        dash = ' stroke-dasharray="4 2"' if inferred else ""
        opacity = "0.92" if a.get("exerts_force") else "0.62"
        svg.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{w:.1f}" height="{bar_h}" rx="3" '
                   f'fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" stroke-width="1"{dash}/>')
        label = f"{a.get('id')}"
        if w > 46:
            label = f"{a.get('id')}. {str(a.get('action'))[:10]}"
        svg.append(f'<text x="{x0 + 4:.1f}" y="{y + bar_h - 4:.1f}" font-size="10" '
                   f'fill="#ffffff">{esc(label)}</text>')
        if a.get("exerts_force"):
            svg.append(f'<circle cx="{x0 + w - 4:.1f}" cy="{y + 4:.1f}" r="2.6" fill="#ffffff"/>')
        rects[a.get("id")] = (x0, x1, y, w)
        title = (f"#{a.get('id')} {a.get('executor')} · {a.get('action')}"
                 f"\n{MODE_CN.get(mode, mode)} · {'持续给力(' + str(a.get('force_role') or '给力') + ')' if a.get('exerts_force') else '未持续给力'}"
                 f"\n{a.get('start')}~{a.get('end')}s · 对象：{a.get('object') or '无'}")
        svg.append(f'<title>{esc(title)}</title>')

    # 关系连线
    for r in relations:
        a_id, b_id = r.get("from"), r.get("to")
        if a_id not in rects or b_id not in rects:
            continue
        ax0, ax1, ay, _ = rects[a_id]
        bx0, _bx1, by, _ = rects[b_id]
        rel = str(r.get("relation"))
        color = REL_COLOR.get(rel, "#999")
        dash = {"sequence": "", "parallel": "6 3", "alternation": "2 3",
                "maintain_until": "8 3", "enables": "1 3"}.get(rel, "4 2")
        if rel == "sequence":
            path = f'M {ax1:.1f} {ay + bar_h / 2:.1f} C {(ax1 + bx0) / 2:.1f} {ay + bar_h / 2:.1f}, ' \
                   f'{(ax1 + bx0) / 2:.1f} {by + bar_h / 2:.1f}, {bx0:.1f} {by + bar_h / 2:.1f}'
        elif rel == "maintain_until":
            path = f'M {ax0 + 2:.1f} {ay + bar_h:.1f} L {ax0 + 2:.1f} {ay + bar_h + 6:.1f} ' \
                   f'L {bx0 + 2:.1f} {by - 6:.1f} L {bx0 + 2:.1f} {by:.1f}'
        else:
            path = f'M {ax0:.1f} {ay + bar_h:.1f} C {ax0:.1f} {ay + bar_h + 12:.1f}, ' \
                   f'{bx0:.1f} {by - 12:.1f}, {bx0:.1f} {by:.1f}'
        svg.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.3" '
                   f'stroke-dasharray="{dash}" opacity="0.75"/>')
        svg.append(f'<title>{esc(RELATION_TEXT.get(rel, rel))}</title>')

    # 图例
    ly = height - 12
    lx = left
    for mode in ("transition", "motion", "maintain"):
        svg.append(f'<rect x="{lx}" y="{ly - 9}" width="12" height="10" rx="2" fill="{COLOR[mode]}"/>')
        svg.append(f'<text x="{lx + 17}" y="{ly}" font-size="11" fill="{COLOR["text"]}">'
                   f'{esc(MODE_CN[mode])}</text>')
        lx += 92
    svg.append(f'<circle cx="{lx + 4}" cy="{ly - 4}" r="3" fill="{COLOR["text"]}"/>')
    svg.append(f'<text x="{lx + 12}" y="{ly}" font-size="11" fill="{COLOR["text"]}">'
               f'块内白点=持续给力</text>')
    lx += 130
    svg.append(f'<rect x="{lx}" y="{ly - 9}" width="12" height="10" rx="2" fill="#fff" '
               f'stroke="#b45309" stroke-dasharray="3 2"/>')
    svg.append(f'<text x="{lx + 17}" y="{ly}" font-size="11" fill="{COLOR["text"]}">'
               f'虚线框=意图推理补全</text>')
    svg.append("</svg>")
    return "\n".join(svg)


# ---------------------------------------------------------------
# 操作依赖图（DAG）
# ---------------------------------------------------------------

DAG_SUB_W, DAG_ROW_H = 184, 62     # 子列宽 / 行高（一层超宽时拆成多个并排子列）
DAG_NODE_W, DAG_NODE_H = 164, 44   # 节点框
DAG_LAYER_GAP = 26                 # 层与层之间的水平间距
DAG_MAX_ROWS = 8                   # 每层超过该行数就拆成并排子列（防止图又高又窄）
DAG_EDGE_STYLE = {
    "sequence": ("#3f7fd0", "", "先后顺序：A 完成后 B 才开始"),
    "enables": ("#b45309", "", "使能：A 是 B 的前置条件"),
    "maintain_until": ("#2f9e6f", "6 3", "保持直到：A 一直保持，直到 B 发生"),
}


def dag_svg(graph: dict) -> str:
    """操作依赖图：节点=执行器级原子动作，边=先后/使能/保持依赖，同列=并行或交替。"""
    nodes = {int(n["id"]): n for n in (graph.get("nodes") or [])}
    edges = graph.get("edges") or []
    if not nodes:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="620" height="72" '
                'font-family="sans-serif"><text x="16" y="42" font-size="13" fill="#6b7280">'
                '（无动作，无法建依赖图）</text></svg>')

    groups: dict[int, list[dict]] = {}
    for n in nodes.values():
        groups.setdefault(int(n.get("layer", 0)), []).append(n)
    cols = sorted(groups)
    part_ix = {p: i for i, p in enumerate(BODY_PARTS)}
    for c in cols:
        groups[c].sort(key=lambda n: (part_ix.get(str(n.get("executor")), 99),
                                      float(n.get("start", 0)), int(n["id"])))

    pad_l, pad_t, pad_r, pad_b = 26, 76, 26, 104
    layout: dict[int, tuple[float, float]] = {}
    bands: list[tuple[float, float, float]] = []      # (起点 x, 带宽, 该列最早开始时间)
    cursor = float(pad_l)
    max_rows = 1
    for c in cols:
        items = groups[c]
        sub = max(1, -(-len(items) // DAG_MAX_ROWS))   # 子列数
        rows = -(-len(items) // sub)
        max_rows = max(max_rows, rows)
        band_w = (sub - 1) * DAG_SUB_W + DAG_NODE_W
        bands.append((cursor - 7, band_w + 14,
                      min(float(n.get("start", 0)) for n in items)))
        for i, n in enumerate(items):
            layout[int(n["id"])] = (cursor + (i % sub) * DAG_SUB_W,
                                     float(pad_t + (i // sub) * DAG_ROW_H))
        cursor += band_w + DAG_LAYER_GAP
    ncols = len(cols)
    width = int(cursor - DAG_LAYER_GAP + pad_r)
    height = pad_t + (max_rows - 1) * DAG_ROW_H + DAG_NODE_H + pad_b

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="{COLOR["bg"]}"/>',
        "<defs>",
    ]
    for rel, (color, _dash, _tip) in DAG_EDGE_STYLE.items():
        svg.append(f'<marker id="dg-{rel}" viewBox="0 0 10 10" refX="9" refY="5" '
                   f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')
    svg.append("</defs>")

    stats = graph.get("stats") or {}
    svg.append(f'<text x="{pad_l}" y="24" font-size="12.5" font-weight="600" '
               f'fill="{COLOR["text"]}">操作依赖图（DAG）：节点 = 执行器级原子动作，'
               f'边 = 先后 / 使能 / 保持依赖</text>')
    note = (f"共 {stats.get('nodes', len(nodes))} 个动作 · {stats.get('edges', len(edges))} 条依赖 · "
            f"{ncols} 列；同一列的动作在时间上并行或交替进行")
    if graph.get("dropped_edges"):
        note += f"；已剔除 {len(graph['dropped_edges'])} 条会成环的边（保证无环）"
    svg.append(f'<text x="{pad_l}" y="41" font-size="10.5" '
               f'fill="{COLOR["muted"]}">{esc(note)}</text>')

    # 层背景带 + 层头（该层最早的开始时间）
    for i, (bx, bw, t0) in enumerate(bands):
        svg.append(f'<rect x="{bx:.1f}" y="{pad_t - 10}" width="{bw:.1f}" '
                   f'height="{height - pad_t - pad_b + 20}" fill="#f8fafc" stroke="#eef2f7"/>')
        svg.append(f'<text x="{bx + 7:.1f}" y="{pad_t - 20}" font-size="10.5" '
                   f'fill="{COLOR["muted"]}">{t0:.1f}s 起</text>')
        svg.append(f'<text x="{bx + 7:.1f}" y="{pad_t - 34}" font-size="10" fill="#94a3b8">'
                   f'第 {i + 1} 列</text>')

    # 依赖边（画在节点下层）
    for e in edges:
        a_id, b_id = int(e["from"]), int(e["to"])
        if a_id not in layout or b_id not in layout:
            continue
        x1, y1 = layout[a_id]
        x2, y2 = layout[b_id]
        sx, sy = x1 + DAG_NODE_W, y1 + DAG_NODE_H / 2
        tx, ty = x2, y2 + DAG_NODE_H / 2
        rel = str(e.get("relation") or "sequence")
        color, dash, tip = DAG_EDGE_STYLE.get(rel, ("#94a3b8", "", rel))
        dx = max(26.0, (tx - sx) * 0.5)
        path = (f'M {sx:.1f} {sy:.1f} C {sx + dx:.1f} {sy:.1f}, '
                f'{tx - dx:.1f} {ty:.1f}, {tx:.1f} {ty:.1f}')
        label = tip + (f"（{e.get('note')}）" if e.get("note") else "")
        svg.append("<g>")
        svg.append(f"<title>{esc(label)}</title>")
        svg.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.4" '
                   f'stroke-dasharray="{dash}" opacity="0.85" marker-end="url(#dg-{rel})"/>')
        svg.append("</g>")

    # 节点
    for n in nodes.values():
        x, y = layout[int(n["id"])]
        mode = str(n.get("mode"))
        fill = COLOR.get(mode, "#888")
        inferred = bool(n.get("inferred"))
        stroke = "#b45309" if inferred else "rgba(0,0,0,.16)"
        dash = ' stroke-dasharray="4 2"' if inferred else ""
        action = str(n.get("action") or "")
        if len(action) > 13:
            action = action[:13] + "…"
        span = f"{n.get('start')}~{n.get('end')}s"
        head = "#" + str(n["id"]) + " " + str(n.get("executor") or "")
        title = (f"#{n['id']} {n.get('executor')} · {n.get('action')}\n{span} · "
                 f"{MODE_CN.get(mode, mode)}· {'推理补全' if inferred else '画面提取'}")
        svg.append("<g>")
        svg.append(f"<title>{esc(title)}</title>")
        svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{DAG_NODE_W}" height="{DAG_NODE_H}" '
                   f'rx="6" fill="#ffffff" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="5" height="{DAG_NODE_H}" rx="2.5" '
                   f'fill="{fill}"/>')
        svg.append(f'<text x="{x + 12:.1f}" y="{y + 15:.1f}" font-size="11" font-weight="600" '
                   f'fill="{COLOR["text"]}">{esc(head)}</text>')
        svg.append(f'<text x="{x + 12:.1f}" y="{y + 29:.1f}" font-size="10.5" '
                   f'fill="#374151">{esc(action)}</text>')
        svg.append(f'<text x="{x + 12:.1f}" y="{y + 40:.1f}" font-size="9.5" '
                   f'fill="{COLOR["muted"]}">{esc(span)}{" · 推理补全" if inferred else ""}</text>')
        svg.append("</g>")

    # 图例
    ly = height - 52
    lx = pad_l
    for mode in ("transition", "motion", "maintain"):
        svg.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="10" rx="2" fill="{COLOR[mode]}"/>')
        svg.append(f'<text x="{lx + 16}" y="{ly}" font-size="11" '
                   f'fill="{COLOR["text"]}">{esc(MODE_CN[mode])}</text>')
        lx += 84
    svg.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="10" rx="2" fill="#fff" '
               f'stroke="#b45309" stroke-dasharray="3 2"/>')
    svg.append(f'<text x="{lx + 16}" y="{ly}" font-size="11" '
               f'fill="{COLOR["text"]}">虚线框=推理补全</text>')
    ly2 = height - 24
    lx = pad_l
    for rel, short in (("sequence", "先后顺序"), ("enables", "使能（前置条件）"),
                       ("maintain_until", "保持直到")):
        color, dash, _tip = DAG_EDGE_STYLE[rel]
        svg.append(f'<line x1="{lx}" y1="{ly2 - 4}" x2="{lx + 24}" y2="{ly2 - 4}" '
                   f'stroke="{color}" stroke-width="1.6" stroke-dasharray="{dash}"/>')
        svg.append(f'<text x="{lx + 30}" y="{ly2}" font-size="11" '
                   f'fill="{COLOR["text"]}">{esc(short)}</text>')
        lx += 156
    svg.append(f'<text x="{lx}" y="{ly2}" font-size="11" fill="{COLOR["muted"]}">'
               f'箭头=依赖方向（左→右为时间推进）</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_graph(bundle: dict, out_dir: Path) -> Path:
    """独立 SVG 产物：执行器级动作依赖图（DAG，追溯用）。"""
    svg = dag_svg(bundle.get("graph") or {})
    path = out_dir / "graph.svg"
    path.write_text(svg.replace('<svg ', '<svg style="background:#fff" ', 1), encoding="utf-8")
    return path


# ---------------------------------------------------------------
# 操作图（节点 = 操作，执行器是节点属性）
# ---------------------------------------------------------------

OP_NODE_W, OP_NODE_H = 252, 122
OP_COL_GAP, OP_ROW_GAP = 108, 30
OP_PAD = (28, 92, 28, 134)
OP_LEGEND_MIN_W = 830      # 图例需要的最小画布宽度（操作少时图会很窄）
OP_EDGE_STYLE = {
    "sequence": ("#3f7fd0", "", "先后：A 完成后 B 才开始"),
    "enables": ("#b45309", "", "使能：A 是 B 的前置条件"),
    "maintain_until": ("#2f9e6f", "6 3", "保持直到：A 一直保持，直到 B 发生"),
}
OP_SOFT_STYLE = {
    "parallel": ("#8b5cf6", "并行 ∥：示范时段重叠"),
    "alternation": ("#0891b2", "交替 ⇄：两者轮流进行"),
}


def _fmt(v: object) -> str:
    """秒数显示（只用于证据时间，不是控制参数）。"""
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "?"


def _clip(text: object, n: int) -> str:
    s = str(text if text is not None else "")
    return s if len(s) <= n else s[: n - 1] + "…"


def _edge_condition(e: dict, op_graph: dict) -> str:
    """这条边承载的条件：部分重叠的用 trigger.predicate，完整依赖用意图链的 provides。"""
    t = e.get("trigger") or {}
    if t.get("predicate"):
        return str(t["predicate"])
    c = next((x for x in (op_graph.get("intent_chain") or [])
              if x.get("from") == e.get("from") and x.get("to") == e.get("to")), None)
    return str((c or {}).get("provides") or "")


def _gap_index(reasoning: dict | None) -> tuple[dict[str, list[str]], dict[str, int]]:
    """从推理检查里分出两类：缺前置条件（红）/ 其他待复核（黄）。

    区分很重要："这个操作缺一条前置条件"与"它的持续约束没被覆盖"是两回事，
    混在一起标就会变成满图报错、反而看不出真正的缺口在哪里。
    """
    gaps: dict[str, list[str]] = {}
    flags: dict[str, int] = {}
    for c in (reasoning or {}).get("checks") or []:
        nid = str(c.get("node") or "")
        if not nid:
            continue
        if c.get("kind") == "pre_coverage" and c.get("action") == "gap":
            gaps.setdefault(nid, []).append(str(c.get("condition") or ""))
        elif c.get("action") == "flag" or c.get("verdict") == "supported_partial":
            flags[nid] = flags.get(nid, 0) + 1
    return gaps, flags


def _edge_data(e: dict, rel: str) -> str:
    """操作图上的机器可读锚点：离线页靠它把一条边接回它承载的关系。"""
    return (f'data-from="{esc(str(e.get("from") or ""))}" '
            f'data-to="{esc(str(e.get("to") or ""))}" data-rel="{esc(str(rel))}"')


def operation_svg(op_graph: dict, intent: str = "", reasoning: dict | None = None) -> str:
    """操作图：节点 = 操作（执行器、时间、意图写在节点里），边 = 先后/使能/保持/并行/交替。

    与 dag_svg 的区别：这张图回答的是"为完成意图做了哪些操作、它们怎么衔接"，
    执行器降级为节点属性——换执行体时节点不用改名，只换能力映射。
    """
    nodes = op_graph.get("nodes") or []
    if not nodes:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="620" height="86" '
                'font-family="sans-serif"><text x="16" y="46" font-size="13" fill="#6b7280">'
                '（无操作节点，无法建操作图）</text></svg>')
    edges = op_graph.get("edges") or []
    stats = op_graph.get("stats") or {}
    nmap = {str(n["id"]): n for n in nodes}
    gaps, flags = _gap_index(reasoning)

    cols: dict[int, list[dict]] = {}
    for n in nodes:
        cols.setdefault(int(n.get("layer", 0)), []).append(n)
    order = sorted(cols)
    # 若 layers 已给出，用它决定列序（保证与 result.json 一致）
    layers = op_graph.get("layers") or []
    if layers:
        cols = {i: [nmap[i2] for i2 in ids if i2 in nmap] for i, ids in enumerate(layers)}
        order = sorted(cols)
    for c in order:
        cols[c].sort(key=lambda n: (float(n.get("start", 0)), float(n.get("end", 0)), n["id"]))

    pad_l, pad_t, pad_r, pad_b = OP_PAD
    pos: dict[str, tuple[float, float]] = {}
    col_x: dict[int, float] = {}
    x = float(pad_l)
    max_rows = 1
    for c in order:
        col_x[c] = x
        items = cols[c]
        max_rows = max(max_rows, len(items))
        for i, n in enumerate(items):
            pos[n["id"]] = (x, pad_t + i * (OP_NODE_H + OP_ROW_GAP))
        x += OP_NODE_W + OP_COL_GAP
    width = int(x - OP_COL_GAP + pad_r)
    width = max(width, OP_LEGEND_MIN_W)
    height = int(pad_t + max_rows * (OP_NODE_H + OP_ROW_GAP) - OP_ROW_GAP + pad_b)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="{COLOR["bg"]}"/>',
        '<defs>',
    ]
    for rel, (color, _dash, _tip) in OP_EDGE_STYLE.items():
        svg.append(f'<marker id="op-{rel}" viewBox="0 0 10 10" refX="9" refY="5" '
                   f'markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')
    for rel, (color, _tip) in OP_SOFT_STYLE.items():
        svg.append(f'<marker id="op-{rel}-d" viewBox="0 0 8 8" refX="4" refY="4">'
                   f'<circle cx="4" cy="4" r="3" fill="{color}"/></marker>')
    svg.append("</defs>")

    # 标题与任务意图
    svg.append(f'<text x="{pad_l}" y="26" font-size="14" font-weight="700" '
               f'fill="{COLOR["text"]}">操作图：节点 = 操作，执行器写在节点里</text>')
    if intent:
        svg.append(f'<text x="{pad_l}" y="46" font-size="12" fill="#3f7fd0">'
                   f'任务意图：{esc(_clip(intent, 46))}</text>')
    note = (f"{stats.get('nodes', len(nodes))} 个操作 · "
            f"顺序 {stats.get('sequence', 0)} · 并行 {stats.get('parallel', 0)} · "
            f"交替 {stats.get('alternation', 0)} · 使能 {stats.get('enables', 0)} · "
            f"执行器 {stats.get('executors', 0)} 个")
    if stats.get("holds"):
        note += f" · 持续节点 {stats.get('holds')}"
    svg.append(f'<text x="{pad_l}" y="64" font-size="10.5" '
               f'fill="{COLOR["muted"]}">{esc(note)}</text>')

    # 列头（该列最早开始时间）
    for i, c in enumerate(order):
        x0 = col_x[c]
        t0 = min(float(n.get("start", 0)) for n in cols[c]) if cols[c] else 0.0
        svg.append(f'<rect x="{x0 - 12:.1f}" y="{pad_t - 30:.1f}" width="{OP_NODE_W + 24}" '
                   f'height="{height - pad_t - pad_b + 44:.1f}" rx="12" fill="#f8fafc" '
                   f'stroke="#eef2f7"/>')
        svg.append(f'<text x="{x0:.1f}" y="{pad_t - 12:.1f}" font-size="10.5" '
                   f'fill="{COLOR["muted"]}">第 {i + 1} 步 · {t0:.1f}s 起</text>')

    # 依赖边
    for e in edges:
        if e.get("mutual"):
            continue
        a, b = nmap.get(str(e["from"])), nmap.get(str(e["to"]))
        if not a or not b or a["id"] not in pos or b["id"] not in pos:
            continue
        ax, ay = pos[a["id"]]
        bx, by = pos[b["id"]]
        sx, sy = ax + OP_NODE_W, ay + OP_NODE_H / 2
        tx, ty = bx, by + OP_NODE_H / 2
        rel = str(e.get("relation") or "sequence")
        color, dash, tip = OP_EDGE_STYLE.get(rel, ("#94a3b8", "", rel))
        if e.get("downgraded"):
            color, dash = "#d97706", "2 3"
            tip = ("已降级为仅观测先后："
                   + str(e.get("downgrade_reason") or "因果不成立"))
        elif e.get("basis") == "observed_order":
            dash = dash or "5 3"
            tip += "（仅观测到的先后，未固化为执行依赖）"
        if (e.get("trigger") or {}).get("type") == "partial":
            color, dash = "#7c3aed", "6 3"
            ev = (e.get("trigger") or {}).get("event") or {}
            tip = (f"部分重叠：前一步的条件在 {ev.get('at')}s（动作 #{ev.get('ref')}）产生，"
                   f"之后才解锁本步的后续动作；不是整段操作结束后才开始")
        if tx < sx:                      # 同列或回指：绕到右侧再回来
            tx, ty = bx + OP_NODE_W, by + OP_NODE_H / 2
            sx, sy = ax + OP_NODE_W, ay + OP_NODE_H / 2
            mid = f'M {sx:.1f} {sy:.1f} C {sx + 34:.1f} {sy:.1f}, {tx + 34:.1f} {ty:.1f}, {tx:.1f} {ty:.1f}'
            svg.append(f'<g class="op-edge" {_edge_data(e, rel)}>')
            svg.append(f'<path d="{mid}" fill="none" stroke="{color}" stroke-width="1.4" '
                       f'stroke-dasharray="{dash}" opacity="0.85" marker-end="url(#op-{rel})"/>')
            svg.append("</g>")
            continue
        dx = max(30.0, (tx - sx) * 0.45)
        path = (f'M {sx:.1f} {sy:.1f} C {sx + dx:.1f} {sy:.1f}, '
                f'{tx - dx:.1f} {ty:.1f}, {tx:.1f} {ty:.1f}')
        label = tip + (f"（{e.get('note')}）" if e.get("note") else "")
        if e.get("carries"):
            label += f"；期间持续保持：{e['carries']}"
        svg.append(f'<g class="op-edge" {_edge_data(e, rel)}>')
        svg.append(f"<title>{esc(label)}</title>")
        svg.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" '
                   f'stroke-dasharray="{dash}" opacity="0.9" marker-end="url(#op-{rel})"/>')
        # 边上直接写出它承载的条件——读者不用悬停就能知道这条边凭什么存在
        cond = _edge_condition(e, op_graph)
        if cond:
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            is_partial = (e.get("trigger") or {}).get("type") == "partial"
            if is_partial:
                ref = ((e.get("trigger") or {}).get("event") or {}).get("ref")
                text = f"⏱ #{ref} 完成 → {_clip(cond, 10)}"
                bg, bd, fg = "#f3ecff", "#c9b0f0", "#5b21b6"
            else:
                text = f"条件：{_clip(cond, 14)}"
                bg, bd, fg = "#eef4fd", "#c2d6f5", "#1d4ed8"
            w = 12 + len(text) * 9.2
            ty_lab = my + 6 if e.get("carries") else my - 8
            svg.append(f'<rect x="{mx - w / 2:.1f}" y="{ty_lab - 13:.1f}" width="{w:.1f}" '
                       f'height="17" rx="8.5" fill="{bg}" stroke="{bd}"/>')
            svg.append(f'<text x="{mx:.1f}" y="{ty_lab:.1f}" font-size="9.5" fill="{fg}" '
                       f'text-anchor="middle">{esc(text)}</text>')
        if e.get("carries"):
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            text = f"∥ {_clip(e['carries'], 16)}延续"
            w = 8 + len(text) * 8.6
            svg.append(f'<rect x="{mx - w / 2:.1f}" y="{my - 20:.1f}" width="{w:.1f}" '
                       f'height="16" rx="8" fill="#eefaf3" stroke="#9fd8bd"/>')
            svg.append(f'<text x="{mx:.1f}" y="{my - 8:.1f}" font-size="9.5" fill="#227a52" '
                       f'text-anchor="middle">{esc(text)}</text>')
        svg.append("</g>")

    # 并行 / 交替：竖括线把同列的操作显式串起来（不再只靠"同一列"暗示）
    for e in edges:
        if not e.get("mutual"):
            continue
        a, b = nmap.get(str(e["from"])), nmap.get(str(e["to"]))
        if not a or not b or a["id"] not in pos or b["id"] not in pos:
            continue
        rel = str(e.get("relation"))
        color, tip = OP_SOFT_STYLE.get(rel, ("#8b5cf6", rel))
        ax, ay = pos[a["id"]]
        bx, by = pos[b["id"]]
        xline = min(ax, bx) - 15
        y1, y2 = ay + OP_NODE_H / 2, by + OP_NODE_H / 2
        svg.append(f'<g class="op-edge soft" {_edge_data(e, rel)}>')
        svg.append(f"<title>{esc(tip)}</title>")
        svg.append(f'<path d="M {xline + 7:.1f} {y1:.1f} L {xline:.1f} {y1:.1f} '
                   f'L {xline:.1f} {y2:.1f} L {xline + 7:.1f} {y2:.1f}" fill="none" '
                   f'stroke="{color}" stroke-width="2" stroke-dasharray="4 3" opacity="0.9"/>')
        svg.append(f'<text x="{xline - 4:.1f}" y="{(y1 + y2) / 2:.1f}" font-size="13" '
                   f'font-weight="700" fill="{color}" text-anchor="middle">'
                   f'{"∥" if rel == "parallel" else "⇄"}</text>')
        svg.append("</g>")

    # 节点
    for n in nodes:
        if n["id"] not in pos:
            continue
        x0, y0 = pos[n["id"]]
        is_running = bool((n.get("purpose") or "").strip())
        is_hold = str(n.get("mode") or "") == "maintain"
        svg.append(f'<g class="op-node" data-op="{esc(str(n["id"]))}">')
        svg.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{OP_NODE_W}" height="{OP_NODE_H}" '
                   f'rx="10" fill="{"#fffaf2" if is_hold else "#ffffff"}" '
                   f'stroke="{"#e8a33d" if is_hold else "#d3dbe6"}" '
                   f'stroke-width="{1.8 if is_hold else 1.5}"'
                   + (' stroke-dasharray="6 3"' if is_hold else '') + '/>')
        svg.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="6" height="{OP_NODE_H}" rx="3" '
                   f'fill="{"#e8890c" if is_hold else "#3f7fd0"}"/>')
        title_text = _clip(n.get("name"), 13 if is_hold else 16)
        svg.append(f'<text x="{x0 + 16:.1f}" y="{y0 + 24:.1f}" font-size="13.5" '
                   f'font-weight="700" fill="{COLOR["text"]}">{esc(title_text)}</text>')
        if is_hold:
            w = 78
            svg.append(f'<rect x="{x0 + 16 + len(title_text) * 13.5 + 6:.1f}" y="{y0 + 12:.1f}" '
                       f'width="{w}" height="16" rx="8" fill="#fdefdc" stroke="#e8a33d"/>')
            svg.append(f'<text x="{x0 + 16 + len(title_text) * 13.5 + 6 + w / 2:.1f}" y="{y0 + 23.5:.1f}" '
                       f'font-size="9.5" font-weight="700" fill="#8a4b12" text-anchor="middle">'
                       f'MAINTAIN</text>')
        svg.append(f'<text x="{x0 + OP_NODE_W - 12:.1f}" y="{y0 + 24:.1f}" font-size="10" '
                   f'fill="{COLOR["muted"]}" text-anchor="end">'
                   f'{float(n.get("start", 0)):.1f}~{float(n.get("end", 0)):.1f}s</text>')
        # 主图显示构型无关的能力需求；人的部位仅留在追溯信息中。
        cx = x0 + 16
        for part in (n.get("required_capabilities") or ["能力待标注"])[:5]:
            w = 13 + len(str(part)) * 10.5
            if cx + w > x0 + OP_NODE_W - 12:
                break
            svg.append(f'<rect x="{cx:.1f}" y="{y0 + 34:.1f}" width="{w:.1f}" height="17" '
                       f'rx="8.5" fill="#eef2f8" stroke="#dde5ef"/>')
            svg.append(f'<text x="{cx + w / 2:.1f}" y="{y0 + 46:.1f}" font-size="10" '
                       f'fill="#3f566f" text-anchor="middle">{esc(part)}</text>')
            cx += w + 5
        obj = "、".join(n.get("object") or [])[:12]
        bits = []
        if obj:
            bits.append(f"对象：{obj}")
        if is_hold:
            covers = [str(x) for x in (n.get("covers") or [])]
            names = [str((nmap.get(c) or {}).get("name") or c) for c in covers]
            bits.append("覆盖：" + "、".join(names[:2]))
        alts = n.get("inner_alternations") or []
        if alts:
            bits.append("内部交替：" + "、".join(f"{a}⇄{b}" for a, b in alts[:2]))
        elif n.get("inner_parallel_count"):
            bits.append(f"内部并行 ×{n['inner_parallel_count']}")
        if bits:
            svg.append(f'<text x="{x0 + 16:.1f}" y="{y0 + 68:.1f}" font-size="10" '
                       f'fill="{COLOR["muted"]}">{esc(_clip("　".join(bits), 34))}</text>')
        purpose = str(n.get("intent") or n.get("purpose") or "").strip()
        if purpose:
            svg.append(f'<text x="{x0 + 16:.1f}" y="{y0 + 86:.1f}" font-size="10.5" '
                       f'fill="#2563eb">→ {esc(_clip(purpose, 20))}</text>')
        # 缺口带：这个操作还缺哪条前置条件（推理发现、尚未当成事实）
        miss = gaps.get(n["id"]) or []
        nflag = flags.get(n["id"], 0)
        band_y = y0 + OP_NODE_H - 22
        if miss:
            svg.append(f'<rect x="{x0 + 1:.1f}" y="{band_y:.1f}" width="{OP_NODE_W - 2}" '
                       f'height="21" rx="9" fill="#fdecec" stroke="#f3c2c2"/>')
            svg.append(f'<text x="{x0 + 12:.1f}" y="{band_y + 14.5:.1f}" font-size="10" '
                       f'fill="#9b2c2c">⚠ 缺条件：{esc(_clip("；".join(miss[:2]), 20))}</text>')
        elif nflag:
            svg.append(f'<rect x="{x0 + 1:.1f}" y="{band_y:.1f}" width="{OP_NODE_W - 2}" '
                       f'height="21" rx="9" fill="#fff8e6" stroke="#f0dca8"/>')
            svg.append(f'<text x="{x0 + 12:.1f}" y="{band_y + 14.5:.1f}" font-size="10" '
                       f'fill="#8a5a12">待复核：{nflag} 项（持续约束 / 证据）</text>')
        title = (f"{n.get('name')}\n示范执行器：{'、'.join(n.get('executors') or [])}\n"
                 f"{n.get('start')}~{n.get('end')}s\n操作意图：{n.get('intent') or '—'}"
                 + ("\n节点类型：MAINTAIN（持续维持状态，不是一个做完就结束的操作）"
                    + (f"\n保持到：{'、'.join(str(x) for x in (n.get('maintain_until') or []))}"
                       if n.get("maintain_until") else "") if is_hold else "")
                 + (f"\n内部协同：交替 {'、'.join('/'.join(p) for p in alts)} " if alts else "")
                 + (f"\n作用：{n.get('purpose')}" if is_running else ""))
        svg.append(f"<title>{esc(title)}</title>")
        svg.append("</g>")

    # 图例（分两行，窄图也不会越界）
    ly = height - 108
    lx = pad_l
    for rel, short in (("sequence", "先后顺序"), ("enables", "使能（前置条件）"),
                       ("maintain_until", "保持直到")):
        color, dash, _tip = OP_EDGE_STYLE[rel]
        svg.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 26}" y2="{ly - 4}" '
                   f'stroke="{color}" stroke-width="1.8" stroke-dasharray="{dash}"/>')
        svg.append(f'<text x="{lx + 32}" y="{ly}" font-size="11" fill="{COLOR["text"]}">'
                   f'{esc(short)}</text>')
        lx += 150
    ly2 = height - 84
    lx = pad_l
    for rel, (color, _tip) in OP_SOFT_STYLE.items():
        svg.append(f'<text x="{lx}" y="{ly2}" font-size="12" font-weight="700" '
                   f'fill="{color}">{"∥" if rel == "parallel" else "⇄"}</text>')
        svg.append(f'<text x="{lx + 16}" y="{ly2}" font-size="11" fill="{COLOR["text"]}">'
                   f'{"示范时段重叠" if rel == "parallel" else "交替进行"}</text>')
        lx += 150
    svg.append(f'<rect x="{lx}" y="{ly2 - 12}" width="34" height="15" rx="7.5" '
               f'fill="#eefaf3" stroke="#9fd8bd"/>')
    svg.append(f'<text x="{lx + 17}" y="{ly2}" font-size="9.5" fill="#227a52" '
               f'text-anchor="middle">∥ 保持</text>')
    svg.append(f'<text x="{lx + 40}" y="{ly2}" font-size="11" fill="{COLOR["text"]}">'
               f'保持延续：前一步的动作延续到本步（并行推进）</text>')
    svg.append(f'<line x1="{pad_l}" y1="{height - 60}" x2="{pad_l + 26}" y2="{height - 60}" '
               f'stroke="#94a3b8" stroke-width="1.6" stroke-dasharray="5 3"/>')
    svg.append(f'<text x="{pad_l + 32}" y="{height - 56}" font-size="11" fill="{COLOR["text"]}">'
               f'仅观测到的先后（未固化为执行依赖）</text>')
    svg.append(f'<line x1="{pad_l + 300}" y1="{height - 60}" x2="{pad_l + 326}" y2="{height - 60}" '
               f'stroke="#d97706" stroke-width="1.8" stroke-dasharray="2 3"/>')
    svg.append(f'<text x="{pad_l + 332}" y="{height - 56}" font-size="11" fill="{COLOR["text"]}">'
               f'经推理降级的依赖（因果不成立）</text>')
    svg.append(f'<text x="{pad_l}" y="{height - 32}" font-size="10.5" fill="{COLOR["muted"]}">'
               f'节点是操作（换执行体时节点不变，只换执行器能力映射）；节点内蓝字 = 该操作为后继操作提供的前置条件</text>')
    svg.append(f'<text x="{pad_l}" y="{height - 14}" font-size="10.5" fill="{COLOR["muted"]}">'
               f'橙框 MAINTAIN = 持续维持状态的节点（不自己“做完”，靠停止事件退出）；'
               f'节点底部红条 = 缺前置条件（候选，待证据）；黄条 = 待复核</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_operations(bundle: dict, out_dir: Path) -> Path:
    """独立 SVG 产物：操作图 = 门控状态机（行为树式：门控 T 时虚线变实线）。

    操作图的主视图就是这张图：圆 = 操作（保持类绿框）、菱形 = 门控，
    同一列 = 时间上重叠的一组操作，列间就是一次换挡。卡片式视图仍保留在
    `operation_svg`（追溯用，比如要看节点缺口红条时），不再是主产物。
    """
    svg = gate_svg(bundle, show_node_details=False)
    path = out_dir / "operations.svg"
    path.write_text(svg.replace('<svg ', '<svg style="background:#fff" ', 1), encoding="utf-8")
    return path


# ---------------------------------------------------------------
# 门控状态机图（操作图的行为树/状态机视图：门控 T 时虚线变实线）
#
# 布局：默认单行长图——列与门控从左到右排成一条，画布宽度按内容算（横向滚动查看）。
# 同一列 = 时间上重叠的一组操作（并行泳道上下排），列与列之间是一个门控菱形。
# （折行模式仍保留：给 gate_svg 传 wrap_width 就变蛇形，跨行的连接走行间空隙。）
#
# 线型只表达一件事：这跳放不放行。连线只用黑色，线型只有实线与虚线。
#   全图线色统一为黑，线型只有两种：实线＝已放行；虚线＝尚未放行、已被否定或持续约束（不是放行）。
# 图上不写状态字母与证据结论；节点只写动作，对象与执行器查七元组。
# ---------------------------------------------------------------

GS_NODE_R = 74                # 操作节点圆半径
GS_START_R = 46               # 开始/结束圆半径
GS_GATE_HW, GS_GATE_HH = 82.5, 51   # 门控菱形半宽 / 半高
GS_H_GAP = 58                 # 同列元素水平间距
GS_V_LANE = 202               # 并行泳道间距
GS_V_PAD = 46                 # 行内上下留白（上方留出行标题的位置）
GS_BAND_GAP = 46              # 行与行之间
GS_BAND_W = 2048              # 折行模式下的行宽上限（默认不折行：单行长图）
GS_LEGEND_MIN_W = 980         # 图例/说明文字需要的最小画布宽度
GS_PAD = (40, 150, 40, 40)    # 左 / 上 / 右 / 下
GS_FONT = "'Noto Sans CJK SC','Microsoft YaHei',sans-serif"
GS_INK = "#1a1a1a"             # 全图线色统一为黑
GS_STYLE = {
    "edge": (GS_INK, "", 3.4),            # 已放行：实线
    "pending": (GS_INK, "12 10", 3.4),    # 尚未放行：虚线
    "blocked": (GS_INK, "6 6", 3.4),      # 条件已被否定：虚线（更密）
    "hold": (GS_INK, "11 8", 3.4),         # 持续约束（保持覆盖），不是放行
    "plain": (GS_INK, "", 3.0),           # 两个操作之间没有门控的直接先后
}
GS_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _gs_wrap(text: object, per_line: int = 5, max_lines: int = 2) -> list[str]:
    t = str(text or "")
    if not t:
        return []
    lines = [t[i:i + per_line] for i in range(0, len(t), per_line)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:per_line - 1] + "…"
    return lines


_GS_BODY_WORDS = ("右臂", "左臂", "双臂", "手臂", "双手", "右手", "左手",
                  "手掌", "手指", "手部", "躯干", "上身", "下肢", "头部", "身体")

# 动作类别：剥离对象后仍偏长时，退回按动词归类（图上以动作为主）
_GS_VERB_MAP = (
    ("接近", "接近"), ("靠近", "接近"), ("移向", "接近"), ("伸向", "伸向"),
    ("抓握", "抓取"), ("抓取", "抓取"), ("握住", "抓取"), ("夹取", "抓取"),
    ("搬运", "搬运"), ("移动", "搬运"), ("转移", "搬运"), ("运至", "搬运"),
    ("放置", "放置"), ("放下", "放置"), ("安放", "放置"),
    ("释放", "释放"), ("松开", "释放"),
    ("张开", "张开"), ("闭合", "闭合"), ("合拢", "闭合"),
    ("复位", "复位"), ("收回", "复位"), ("撤回", "复位"), ("回到", "复位"),
)


def _gs_display_name(node: dict) -> str:
    """节点在图上只写动作：隐去操作对象与执行器，让图泛化。

    “接近燕麦杯”显示成“接近”，“手指张开释放燕麦杯”显示成“释放”；
    完整名字、操作对象、执行器与时间段仍在七元组与节点详情（悬停）里。
    """
    raw = str(node.get("name") or node.get("id") or "").strip()
    if not raw:
        return "操作"
    tokens: list[str] = []
    for key in ("object", "objects", "target"):
        val = node.get(key)
        if isinstance(val, str):
            tokens.append(val)
        elif isinstance(val, (list, tuple)):
            tokens.extend(str(v) for v in val)
    tokens.extend(_GS_BODY_WORDS)
    out = raw
    for token in sorted({t for t in tokens if t}, key=len, reverse=True):
        out = out.replace(token, "")
    for sep in ("至", "到", "成", "为"):
        idx = out.find(sep, 1)
        if idx >= 2:                      # “回到…”这类两字动词不截
            out = out[:idx]
    out = out.strip(" 　，,。；;、的")
    if not out:
        out = raw
    if str(node.get("mode") or "").lower() == "maintain":
        return out                        # 保持类节点保留“保持＋部位/对象”，互相可区分
    if len(out) <= 3:
        return out
    for kw, short in _GS_VERB_MAP:
        if kw in raw:
            return short
    return out


def _gs_circled(n: int) -> str:
    return GS_CIRCLED[n - 1] if 1 <= n <= len(GS_CIRCLED) else str(n)


def _gs_anchor(kind: str, x: float, y: float, side: int) -> tuple[float, float]:
    """连接点：节点落在圆周上，菱形落在左右顶点上，起点/终点圆落在圆上。"""
    if kind == "gate":
        return (x + side * GS_GATE_HW, y)
    r = GS_START_R if kind in ("start", "end") else GS_NODE_R
    return (x + side * r, y)


def _gs_edge_path(a: tuple[float, float], b: tuple[float, float],
                  a_kind: str, b_kind: str, bend: float = 0.45) -> str:
    """同一行内两点之间的连线：水平直线，或“水平—垂直—水平”的直角折线（同参考图）。"""
    ax, ay = a
    bx, by = b
    if abs(ay - by) < 0.6:
        return f"M {ax:.1f},{ay:.1f} L {bx:.1f},{by:.1f}"
    if abs(bx - ax) < 2 * (GS_H_GAP + 8):
        mx = (ax + bx) / 2
    else:
        mx = ax + (bx - ax) * bend
    return (f"M {ax:.1f},{ay:.1f} L {mx:.1f},{ay:.1f} L {mx:.1f},{by:.1f} "
            f"L {bx:.1f},{by:.1f}")


def _gs_hold_in_path(start: tuple[float, float], end: tuple[float, float]) -> str:
    """保持节点的进入线：贴着门控右侧先下折到保持泳道，再水平推进到保持节点。

    不能像普通连线那样“先水平、后下折”：保持节点现在落在它那条线的中间（左右两
    段等长），水平段会横穿主轴上的操作节点；先下折就只经过列与列之间的空隙。
    """
    ax, ay = start
    bx, by = end
    if abs(ay - by) < 0.6:
        return f"M {ax:.1f},{ay:.1f} L {bx:.1f},{by:.1f}"
    sx = min(ax + 14, bx - 12)      # 保底：下折点不能越过保持节点左缘，否则会折回
    return (f"M {ax:.1f},{ay:.1f} L {sx:.1f},{ay:.1f} L {sx:.1f},{by:.1f} "
            f"L {bx:.1f},{by:.1f}")


def _gs_take_lane(used: set, first: int, step: int) -> int:
    """从 first 出发沿 step 方向找第一个没被占的相对泳道。"""
    off = first
    while off in used:
        off += step
    return off


def _gs_take_main_lane(used: set) -> int:
    """操作节点的泳道：主轴优先，主轴被同列其它操作占了再上下就近让位。"""
    if 0 not in used:
        return 0
    k = 1
    while True:
        if -k not in used:
            return -k
        if k not in used:
            return k
        k += 1


def _gs_col_offsets(ids: list, omap: dict) -> list[int]:
    """列内节点的相对泳道：0 = 主轴，负 = 上方，正 = 下方。

    保持节点按类别固定分区（用户口径）：
      · “保持手臂不动”一类（位姿 / 托举 / 接触保持）在上方泳道；
      · “保持抓握”一类（grasp）在下方泳道。
    连续多个保持节点（保持抓握→保持位置 这种切换）就各自占一条固定的水平线，
    进入线与持续约束线不会横穿别的保持节点。

    操作节点回主轴；主轴已被同列另一个操作占用时，才按“先上后下”就近让位。
    保持节点先分配：它们是硬分区，操作节点只要求“尽量靠主轴”。
    """
    out: list[int | None] = [None] * len(ids)
    used: set[int] = set()
    for i, nid in enumerate(ids):                 # 一、保持节点先落位
        n = omap.get(str(nid)) or {}
        if str(n.get("mode") or "").lower() != "maintain":
            continue
        cat = str(n.get("hold_category") or "") or hold_category(n.get("name"))
        up = cat != "grasp"
        off = _gs_take_lane(used, -1 if up else 1, -1 if up else 1)
        used.add(off)
        out[i] = off
    for i in range(len(ids)):                     # 二、操作节点回主轴
        if out[i] is not None:
            continue
        off = _gs_take_main_lane(used)
        used.add(off)
        out[i] = off
    return [int(x) for x in out]


def gate_svg(bundle: dict, wrap_width: float | None = None, *,
             show_node_details: bool = True) -> str:
    """门控状态机图：圆=操作（只写动作），菱形=门控，全黑线，只有实线与虚线。

    线型语义：门控 T 实线（放行）；U / F 与持续约束都是虚线。图面上不写 T/U/F 字母，
    菱形里只有序号，状态与依据在悬停 `<title>` 与工作台详情里。

    默认**单行长图**：所有列与门控从左到右排成一条，画布宽度按内容算（查看器里横向滚动）。
    给 `wrap_width`（像素）时才蛇形折行：上行走右、下行走左，跨行连线走行间空隙。
    """
    if bundle.get("single_actor_version"):
        show_node_details = False
    gdoc = bundle.get("gates") or {}
    op_graph = bundle.get("operations") or {}
    ops = [n for n in op_graph.get("nodes") or [] if isinstance(n, dict)]
    cols = [c for c in (gdoc.get("columns") or []) if c]
    gates = gdoc.get("gates") or []
    if not ops or not cols:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="720" height="96" '
                f'font-family="{GS_FONT}"><text x="18" y="52" font-size="14" '
                'fill="#6b7280">（无操作节点，无法建门控图）</text></svg>')
    omap = {str(n["id"]): n for n in ops}
    edges = op_graph.get("edges") or []

    # ---- 元素序列：开始 · 列 · 门控 · 列 · 门控 …… 结束 ----
    items: list[dict] = [{"kind": "start", "w": 2 * GS_START_R, "h": 2 * GS_START_R}]
    for i, col in enumerate(cols):
        items.append({"kind": "col", "ids": list(col),
                      "w": 2 * GS_NODE_R, "h": 2 * GS_NODE_R})
        if i < len(gates):
            items.append({"kind": "gate", "gate": gates[i],
                          "w": 2 * GS_GATE_HW + 14, "h": 2 * GS_GATE_HH})
    items.append({"kind": "end", "w": 2 * GS_START_R, "h": 2 * GS_START_R})

    # ---- 单行长图（默认）；只有显式给了 wrap_width 才折行 ----
    total_w = sum(it["w"] for it in items) + GS_H_GAP * (len(items) - 1)
    bands: list[list[dict]] = []
    if wrap_width and wrap_width > 0:
        # 蛇形折行：先算需要几行，再按目标宽度切，避免最后一行只剩一两个元素
        n_bands = max(1, (int(total_w) + int(wrap_width) - 1) // int(wrap_width))
        target = total_w / n_bands
        cur: list[dict] = []
        used = 0.0
        for k, it in enumerate(items):
            add = it["w"] + (GS_H_GAP if cur else 0)
            if cur and (used + add > wrap_width
                        or (used + add > target and len(bands) < n_bands - 1
                            and k < len(items) - 1)):
                bands.append(cur)
                cur, used = [], 0.0
                add = it["w"]
            cur.append(it)
            used += add
        if cur:
            bands.append(cur)
    else:
        # 单行长图：所有元素排成一行，画布宽度按内容算（查看器里横向滚动）
        bands = [items]

    pad_l, pad_t, pad_r, pad_b = GS_PAD
    content_w = sum(it["w"] for it in items) + GS_H_GAP * (len(items) - 1)
    width = int(max(pad_l + content_w + pad_r, GS_LEGEND_MIN_W))
    y = float(pad_t)
    band_top: list[float] = []
    band_bottom: list[float] = []
    for bi, band in enumerate(bands):
        # 泳道分配：每列先算“相对泳道”（0 = 主轴，负 = 上，正 = 下，见 _gs_col_offsets），
        # 再取整个 band 需要的上方 / 下方格数——主轴落在上方格数之后的那一格。
        for it in band:
            if it["kind"] == "col":
                it["offs"] = _gs_col_offsets(it["ids"], omap)
        up = max([-min(it["offs"]) for it in band if it["kind"] == "col"] + [0])
        down = max([max(it["offs"]) for it in band if it["kind"] == "col"] + [0])
        lanes = up + 1 + down
        band_dir = 1 if bi % 2 == 0 else -1
        band_left = pad_l
        band_right = width - pad_r
        x = band_left if band_dir > 0 else band_right
        for it in band:
            it["cx"] = x + it["w"] / 2 if band_dir > 0 else x - it["w"] / 2
            x += (it["w"] + GS_H_GAP) * band_dir
        band_top.append(y)
        lane_y = [y + GS_V_PAD + GS_NODE_R + i * GS_V_LANE for i in range(lanes)]
        spine = up      # 主轴：主干节点与全部门控都落在这条水平线上
        for it in band:
            it["band_top"], it["lane_y"], it["spine"] = y, lane_y, spine
            it["cy"] = lane_y[spine] if it["kind"] != "col" else None
            if it["kind"] == "col":
                it["cys"] = [lane_y[spine + off] for off in it["offs"]]
        y = y + GS_V_PAD * 2 + 2 * GS_NODE_R + (lanes - 1) * GS_V_LANE
        band_bottom.append(y)
        y += GS_BAND_GAP
    legend_h = 268
    height = int(y - GS_BAND_GAP + pad_b + legend_h)

    pos: dict[str, tuple[float, float]] = {}
    kinds: dict[str, str] = {}
    for band in bands:
        for it in band:
            if it["kind"] == "col":
                for i, nid in enumerate(it["ids"]):
                    pos[str(nid)] = (it["cx"], it["cys"][i])
                    kinds[str(nid)] = "node"
            elif it["kind"] in ("start", "end"):
                pos[it["kind"]] = (it["cx"], it["cy"])
                kinds[it["kind"]] = it["kind"]
    for band in bands:
        for it in band:
            if it["kind"] != "gate":
                continue
            g = it["gate"]
            # 门控统一落在主轴上：主干前后两跳就是同一条直线
            it["cy"] = it["lane_y"][it["spine"]]
            pos[str(g["id"])] = (it["cx"], it["cy"])
            kinds[str(g["id"])] = "gate"

    band_of: dict[str, int] = {}
    for bi, band in enumerate(bands):
        for it in band:
            if it["kind"] == "col":
                for nid in it["ids"]:
                    band_of[str(nid)] = bi
            elif it["kind"] == "gate":
                band_of[str(it["gate"]["id"])] = bi
            else:
                band_of[it["kind"]] = bi

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{GS_FONT}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<defs>',
    ]
    for key, (color, _dash, _w) in GS_STYLE.items():
        svg.append(f'<marker id="gs-{key}" viewBox="0 0 10 10" refX="9" refY="5" '
                   f'markerWidth="9" markerHeight="9" orient="auto-start-reverse">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')
    svg.append("</defs>")

    # ---- 标题区：标题 + 副标题 + 任务意图 ----
    intents = (bundle.get("intents") or {}).get("intents") or []
    intent = str(intents[0].get("statement") or "") if intents else ""
    stats = gdoc.get("stats") or {}
    case_name = str((bundle.get("meta") or {}).get("name") or "")
    svg.append(f'<text x="{pad_l}" y="62" font-size="34" font-weight="700" '
               f'fill="#18314b">{esc(case_name)} 操作图｜门控放行时，虚线变实线</text>')
    sub = (f"共 {stats.get('gates', 0)} 个门控 · {len(ops)} 个操作节点 · "
           f"节点只写动作，操作对象与执行器见七元组")
    svg.append(f'<text x="{pad_l}" y="92" font-size="17" fill="#536579">{esc(sub)}</text>')
    if intent:
        svg.append(f'<text x="{pad_l}" y="118" font-size="16" fill="#3f7fd0">'
                   f'任务意图：{esc(_clip(intent, 64))}</text>')

    # ---- 行底衬与行标题 ----
    for bi, band in enumerate(bands):
        first, last = band[0], band[-1]
        x0 = min(it["cx"] - it["w"] / 2 for it in band) - 30
        x1 = max(it["cx"] + it["w"] / 2 for it in band) + 30
        top = first["band_top"]
        hgt = (last["lane_y"][-1] - first["lane_y"][0]) + 2 * GS_NODE_R + 2 * GS_V_PAD
        svg.append(f'<rect x="{x0:.1f}" y="{top:.1f}" width="{x1 - x0:.1f}" '
                   f'height="{hgt:.1f}" rx="28" fill="#f7f9fc" stroke="#e0e7ef"/>')
        cols_in = [it for it in band if it["kind"] == "col"]
        if not cols_in:
            continue
        head = omap.get(str(cols_in[0]["ids"][0])) or {}
        tail = omap.get(str(cols_in[-1]["ids"][-1])) or {}
        caption = ((f"第 {bi + 1} 段：" if len(bands) > 1 else "")
                   + f"{_gs_display_name(head)} → {_gs_display_name(tail)}"
                   )
        svg.append(f'<text x="{x0 + 26:.1f}" y="{top + 32:.1f}" font-size="19" '
                   f'font-weight="650" fill="#697a8f">{esc(caption)}</text>')

    def edge_class(src_id: str, dst_id: str) -> str:
        """这条连线的线型：跟随它所属门控的状态。"""
        if kinds.get(src_id) == "gate":
            st = next((g for g in gates if str(g["id"]) == src_id), {}).get("state", "U")
            return {"T": "edge", "F": "blocked"}.get(st, "pending")
        if kinds.get(dst_id) == "gate":
            st = next((g for g in gates if str(g["id"]) == dst_id), {}).get("state", "U")
            return {"T": "edge", "F": "blocked"}.get(st, "pending")
        return "plain"

    def draw(src_id: str, dst_id: str, cls: str, label: str = "",
             opacity: float = 0, path_d: str | None = None,
             visual_to: str | None = None) -> None:
        if src_id not in pos or dst_id not in pos:
            return
        ax, ay = pos[src_id]
        bx, by = pos[dst_id]
        ba, bb = band_of.get(src_id), band_of.get(dst_id)
        side = 1 if bx >= ax else -1
        color, dash, sw = GS_STYLE.get(cls, GS_STYLE["plain"])
        start = _gs_anchor(kinds[src_id], ax, ay, side)
        end = _gs_anchor(kinds[dst_id], bx, by, -side)
        if path_d is not None:
            d = path_d
        elif ba == bb:
            d = _gs_edge_path(start, end, kinds[src_id], kinds[dst_id])
        else:
            # 折行：先垂直到两行之间的空隙，水平推进，再垂直进入目标
            mid_y = (band_bottom[ba] + band_top[bb]) / 2
            sx2 = start[0] + side * 14
            d = (f"M {start[0]:.1f},{start[1]:.1f} L {sx2:.1f},{start[1]:.1f} "
                 f"L {sx2:.1f},{mid_y:.1f} L {end[0]:.1f},{mid_y:.1f} "
                 f"L {end[0]:.1f},{end[1]:.1f}")
        svg.append(f'<path class="gs-line {cls}" data-from="{esc(src_id)}" data-to="{esc(dst_id)}" d="{d}" fill="none" stroke="{color}" '
                   f'stroke-width="{sw}" stroke-dasharray="{dash}" '
                   f'marker-end="url(#gs-{cls})"'
                   + (f' data-visual-to="{esc(visual_to)}"' if visual_to else "")
                   + (f' opacity="{opacity}"' if opacity else "") + "/>")
        if label:
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            tw = 10 + len(label) * 9.4
            svg.append(f'<rect x="{mx - tw / 2:.1f}" y="{my - 21:.1f}" width="{tw:.1f}" '
                       f'height="17" rx="8.5" fill="#ffffff" stroke="#dbe3ec"/>')
            svg.append(f'<text x="{mx:.1f}" y="{my - 9:.1f}" font-size="11" '
                       f'fill="#5a6b80" text-anchor="middle">{esc(label)}</text>')

    # ---- 主干连线：开始 → 第一列；列 → 门控 → 列；最后一列 → 结束 ----
    # 保持节点（maintain）不参与主干放行链：操作 → 门控 这一段里不画它，它的进入线
    # 单独画（见下面“保持节点进入线”一段），否则门控两侧会多出 gate→hold 的折线。
    def _is_hold(nid: object) -> bool:
        return str((omap.get(str(nid)) or {}).get("mode") or "").lower() == "maintain"

    col_of = {str(n): i for i, col in enumerate(cols) for n in col}

    # ---- 持续约束的来源与终点（先定终点，保持节点才能落在它那条线的中间）----
    # “保持抓握”要一直覆盖到目标动作结束：终点取目标所在列之后的那道门控
    # （gate_{k+1}）。取之前那道会让线向左折回，看上去像一条不该有的边。
    holds: list[tuple[str, str, str]] = []
    seen_hold: set[tuple[str, str]] = set()
    for e in edges:
        if str(e.get("relation")) != "maintain_until":
            continue
        f, t = str(e.get("from")), str(e.get("to"))
        # 只有保持节点才配一条持续约束线。操作自身的支撑保持（“下蹲期间双腿
        # 保持站立支撑”）不是覆盖关系，画出来会与主干线重合，反而看不懂。
        if not _is_hold(f):
            continue
        if f in pos and t in pos and (f, t) not in seen_hold:
            seen_hold.add((f, t))
            holds.append((f, t, str(e.get("note") or "")))
    # 节点自带的 maintain_until 才是一手字段：语义层没为它建 maintain_until 边时
    # （例如「保持抓握燕麦杯」横跨两步，边只记成 parallel），图上仍要守住这条覆盖。
    for n in omap.values():
        nid = str(n.get("id"))
        if str(n.get("mode") or "").lower() != "maintain":
            continue
        for t in (n.get("maintain_until") or []):
            t = str(t)
            if nid in pos and t in pos and (nid, t) not in seen_hold:
                seen_hold.add((nid, t))
                tn = omap.get(t) or {}
                holds.append((nid, t, f"「{n.get('name')}」保持到「{tn.get('name') or t}」完成"))
    # 终点按保持节点聚合：covers ∪ maintain_until 里最靠右的那一步之后的门控。
    # 「保持抓握」覆盖搬运到放置连续几步，终点就该落在放置完成之后，而不是起手那一步；
    # 终点若全在保持节点左侧，退回它自己那列之后的门控——保证线只向右、不折回。
    hold_dst: dict[str, tuple[int, str]] = {}
    for f, t, note in holds:
        kcols = [col_of[t]] if t in col_of else []
        hn = omap.get(f) or {}
        for c in (hn.get("covers") or []):
            if str(c) in col_of:
                kcols.append(col_of[str(c)])
        if not kcols:
            continue
        k = max(max(kcols), col_of.get(f, 0))
        if f not in hold_dst or k > hold_dst[f][0]:
            hold_dst[f] = (k, note)

    # ---- 保持节点落位：摆到它那条水平线的中间 ----
    # 每个保持节点左右各一条线：左边是从前一道门控进来的进入线，右边是覆盖到终点门控
    # （或“结束”）的持续约束线。两端取中点，左右两段等长、整行更匀称；留在列位上会让
    # 右侧拖出很长一条（搬物体“保持抓握→结束”、移动物体“保持抓握→门控 ④”）。
    hold_src: dict[str, str] = {}
    for n in omap.values():
        hid = str(n.get("id"))
        if not _is_hold(hid) or hid not in pos:
            continue
        k = col_of.get(hid)
        if k is None or not (0 <= k - 1 < len(gates)):
            continue
        src = str(gates[k - 1]["id"])
        hold_src[hid] = src
        if hid not in hold_dst or src not in pos:
            continue
        kk = hold_dst[hid][0]
        dst = str(gates[kk]["id"]) if kk < len(gates) else "end"
        if dst == hid or dst not in pos:
            continue
        pos[hid] = ((pos[src][0] + pos[dst][0]) / 2, pos[hid][1])

    for nid in cols[0]:
        if not _is_hold(nid):
            draw("start", str(nid), "plain")
    for i, g in enumerate(gates):
        gid = str(g["id"])
        for nid in cols[i]:
            if not _is_hold(nid):
                draw(str(nid), gid, edge_class(str(nid), gid))
        nxt = cols[i + 1] if i + 1 < len(cols) else []
        for nid in nxt:
            if not _is_hold(nid):
                draw(gid, str(nid), edge_class(gid, str(nid)))
    for nid in cols[-1]:
        if not _is_hold(nid):
            draw(str(nid), "end", "plain")

    # ---- 直接先后（没有门控的转移）：搬运 → 放置 这类同执行器的推进 ----
    gate_between = {(i, i + 1): str(gates[i]["id"]) for i in range(len(gates))}
    for e in edges:
        f, t = str(e.get("from")), str(e.get("to"))
        if e.get("mutual") or f not in col_of or t not in col_of:
            continue
        if str(e.get("relation")) not in ("sequence", "enables"):
            continue
        cf, ct = col_of[f], col_of[t]
        if ct != cf + 1 or gate_between.get((cf, ct)):
            continue                       # 这一步由门控表达，不另画
        draw(f, t, "plain")

    # ---- 保持节点进入线：由它左侧紧邻的那道门控进入 ----
    # 保持节点不是被门控放行的操作，但它左侧仍要有一条进入线，读图时能看出这个保持
    # 从哪一步开始生效。取它所在列左边那道门控（gate_{col}），线永远向右进入、不折回；
    # 若改按语义层的前驱边取（前驱可能在更左的列），搬物体这类“前驱与保持同列或
    # 隔着好几列”的案例会被拉出一条向左跨列的长线，反而看不出层次。
    # 保持节点已按两端中点落位，进入线要贴门控先下折再水平推进（见 _gs_hold_in_path）。
    for hid, src in hold_src.items():
        if hid not in pos or src not in pos:
            continue
        ax, ay = pos[src]
        bx, by = pos[hid]
        d = _gs_hold_in_path(_gs_anchor("gate", ax, ay, 1),
                             _gs_anchor("node", bx, by, -1))
        draw(src, hid, edge_class(src, hid), path_d=d)

    # ---- 持续约束：保持节点 → 它守着的那一跳之后的门控（黑虚线，不是放行）----
    # 终点的收集（gate_{k+1} 或“结束”）与进入来源已放到前面算好，保持节点也已按两端
    # 中点落位；这一段只负责把线画出来。
    for f, (k, note) in hold_dst.items():
        dst = str(gates[k]["id"]) if k < len(gates) else "end"
        if dst == f or dst not in pos:
            continue
        color, dash, sw = GS_STYLE["hold"]
        ax, ay = pos[f]
        bx, by = pos[dst]
        side = 1 if bx >= ax else -1
        start = _gs_anchor(kinds[f], ax, ay, side)
        end = _gs_anchor(kinds[dst], bx, by, -side)
        if band_of.get(f) != band_of.get(dst):
            mid_y = (band_bottom[band_of[f]] + band_top[band_of[dst]]) / 2
            sx2 = start[0] + side * 14
            d = (f"M {start[0]:.1f},{start[1]:.1f} L {sx2:.1f},{start[1]:.1f} "
                 f"L {sx2:.1f},{mid_y:.1f} L {end[0]:.1f},{mid_y:.1f} "
                 f"L {end[0]:.1f},{end[1]:.1f}")
        elif abs(ay - by) < 0.6:
            # 同轴：从下方绕一小段再回来，避免与主干线重合
            mx1 = start[0] + 26
            dip = ay + GS_NODE_R * 0.85
            if end[0] - mx1 > 70:
                d = (f"M {start[0]:.1f},{start[1]:.1f} L {mx1:.1f},{start[1]:.1f} "
                     f"L {mx1:.1f},{dip:.1f} L {end[0] - 26:.1f},{dip:.1f} "
                     f"L {end[0] - 26:.1f},{end[1]:.1f} L {end[0]:.1f},{end[1]:.1f}")
            else:
                d = _gs_edge_path(start, end, kinds[f], kinds[dst])
        elif kinds[dst] == "gate":
            # 保持节点在主轴侧车道、终点是主轴上的门控：沿本车道推到门控正上／
            # 正下方，再垂直进入菱形尖。上下对称，既不会向左折回，也不会斜穿主轴。
            tip_y = by - GS_GATE_HH if ay < by else by + GS_GATE_HH
            d = (f"M {start[0]:.1f},{start[1]:.1f} L {bx:.1f},{start[1]:.1f} "
                 f"L {bx:.1f},{tip_y:.1f}")
        elif dst == "end":
            # 覆盖到最后一步、后面已无门控：终点落在“结束”圆上。沿本车道推到结束圆正上／
            # 正下方，再垂直进入圆顶／圆底：既不会沿主轴推进时横穿最后一列的节点
            # （“放置并释放”本就坐在主轴上），也不会与“最后一步 → 结束”的主干线重合。
            ty = by - GS_START_R if ay < by else by + GS_START_R
            d = (f"M {start[0]:.1f},{start[1]:.1f} L {bx:.1f},{start[1]:.1f} "
                 f"L {bx:.1f},{ty:.1f}")
        else:
            # 向右推进的直角折线（与参考图同构），不再向左折回
            d = _gs_edge_path(start, end, kinds[f], kinds[dst])
        svg.append(f'<g class="gs-hold"><title>{esc(note)}</title>'
                   f'<path class="gs-line hold" data-from="{esc(f)}" data-to="{esc(dst)}" d="{d}" fill="none" stroke="{color}" '
                   f'stroke-width="{sw}" stroke-dasharray="{dash}" '
                   f'marker-end="url(#gs-hold)"/></g>')

    if bundle.get("single_actor_version"):
        for edge in edges:
            if edge.get("relation") != "maintain_until":
                continue
            f, t = str(edge["from"]), str(edge["to"])
            if f not in pos or t not in pos:
                continue
            # The visible grip boundary is the gate immediately before release.
            # Keep data-to bound to the release event for the relation inspector.
            target_gate = next((str(g["id"]) for g in gates
                                if t in [str(n) for n in g.get("to") or []]), None)
            if target_gate not in pos:
                continue
            ax, ay = pos[f]
            bx, by = pos[target_gate]
            lane_y = max(y for _, y in pos.values()) + GS_NODE_R + 34
            path = (f"M {ax:.1f},{ay + GS_NODE_R:.1f} V {lane_y:.1f} "
                    f"H {bx:.1f} V {by + GS_GATE_HH:.1f}")
            draw(f, t, "hold", path_d=path, visual_to=target_gate)

    # ---- 节点 ----
    for band in bands:
        for it in band:
            if it["kind"] == "start" or it["kind"] == "end":
                label = "开始" if it["kind"] == "start" else "结束"
                svg.append(f'<circle cx="{it["cx"]:.1f}" cy="{it["cy"]:.1f}" '
                           f'r="{GS_START_R}" fill="#173754"/>')
                label_y = it["cy"] + (9 if show_node_details else 0)
                baseline = "" if show_node_details else ' dominant-baseline="central"'
                svg.append(f'<text x="{it["cx"]:.1f}" y="{label_y:.1f}" font-size="25" '
                           f'font-weight="650" fill="#ffffff" text-anchor="middle"{baseline}>{label}</text>')
                continue
            if it["kind"] == "gate":
                g = it["gate"]
                cx, cy = it["cx"], it["cy"]
                svg.append(f'<g class="gs-gate" data-gate="{esc(str(g.get("id")))}">'
                           f'<title>{esc(_gs_gate_title(g))}</title>')
                svg.append(f'<path d="M {cx:.1f},{cy - GS_GATE_HH:.1f} L {cx + GS_GATE_HW:.1f},{cy:.1f} '
                           f'L {cx:.1f},{cy + GS_GATE_HH:.1f} L {cx - GS_GATE_HW:.1f},{cy:.1f} Z" '
                           f'fill="#eff9f5" stroke="#159474" stroke-width="3.4"/>')
                # 菱形里只写编号：条件明细留在悬停详情、报告与工作台，图面保持干净
                svg.append(f'<text x="{cx:.1f}" y="{cy:.1f}" dominant-baseline="central" font-size="19" font-weight="600" '
                           f'fill="#176650" text-anchor="middle">'
                           f'门控 {_gs_circled(int(g.get("seq") or 1))}</text>')
                svg.append("</g>")
                continue
            for i, nid in enumerate(it["ids"]):
                n = omap.get(str(nid))
                if not n:
                    continue
                # 用 pos：保持节点已按两端中点重新落位，不再等同列布局坐标
                cx, cy = pos.get(str(nid), (it["cx"], it["cys"][i]))
                hold = str(n.get("mode") or "") == "maintain"
                svg.append(f'<g class="gs-node" data-op="{esc(str(nid))}">'
                           f'<title>{esc(_gs_node_title(n))}</title>')
                svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{GS_NODE_R}" '
                           f'fill="{"#fffaf0" if hold else "#ffffff"}" '
                           f'stroke="{"#c88328" if hold else "#2363a0"}" stroke-width="3.5"/>')
                name_lines = _gs_wrap(_gs_display_name(n), 5, 2)
                base = cy - (20 if show_node_details else 0) - (len(name_lines) - 1) * 11
                baseline = "" if show_node_details else ' dominant-baseline="central"'
                for j, line in enumerate(name_lines):
                    svg.append(f'<text x="{cx:.1f}" y="{base + j * 22:.1f}" font-size="22" '
                               f'font-weight="650" fill="#173754" text-anchor="middle"{baseline}>{esc(line)}</text>')
                # 协同行：蓝 = 本步主动执行器（在动），橙 = 同步保持的执行器（谁在保持）
                coord = n.get("coordination") or {}
                y_sub = cy + 12
                if show_node_details and coord and not hold:
                    for group, color in (("primary", "#2363a0"), ("holding", "#c88328")):
                        txt = "·".join(
                            f"{c.get('executor', '')}{c.get('phrase') or ''}"
                            for c in (coord.get(group) or []) if c)
                        if not txt:
                            continue
                        svg.append(f'<text x="{cx:.1f}" y="{y_sub:.1f}" font-size="12.5" '
                                   f'fill="{color}" text-anchor="middle">'
                                   f'{esc(_gs_wrap(txt, 9, 1)[0])}</text>')
                        y_sub += 15
                if show_node_details and bundle.get("learning_layer") != "semantic":
                    svg.append(f'<text x="{cx:.1f}" y="{cy + 54:.1f}" font-size="14" '
                               f'fill="#627083" text-anchor="middle">'
                               f'{float(n.get("start", 0)):.0f}–{float(n.get("end", 0)):.0f}s</text>')
                svg.append("</g>")

    # ---- 图例与判定说明 ----
    ly = height - legend_h + 12
    svg.append(f'<rect x="{pad_l}" y="{ly}" width="{width - pad_l - pad_r}" '
               f'height="{legend_h - 26}" rx="20" fill="#f8fafc" stroke="#e6ecf4"/>')
    lx = pad_l + 30
    ty = ly + 46
    for k, (key, text) in enumerate((
            ("edge", "实线：这跳已放行（门控条件成立）"),
            ("pending", "虚线：门控尚未放行，等待条件成立"),
            ("hold", "持续约束：保持覆盖后续动作，不表示已放行"))):
        y = ty + k * 42
        color, dash, sw = GS_STYLE[key]
        svg.append(f'<line x1="{lx}" y1="{y}" x2="{lx + 90}" y2="{y}" stroke="{color}" '
                   f'stroke-width="{sw}" stroke-dasharray="{dash}" '
                   f'marker-end="url(#gs-{key})"/>')
        svg.append(f'<text x="{lx + 112}" y="{y + 7}" font-size="18" '
                   f'fill="#334155">{esc(text)}</text>')
    note_y = ty + 3 * 42 + 14
    note1 = "关键门控 G = 前序操作所需效果已成立 ∧ 下一操作前置条件已成立 ∧ 必要的场景与持续约束已成立。"
    note2 = "节点内小字：蓝＝本步主动执行器，橙＝同步保持的执行器（谁在动、谁在保持）；七元组与证据在悬停详情、报告与工作台里。"
    if not show_node_details:
        note2 = "七元组与证据在悬停详情、报告与工作台里。"
    svg.append(f'<text x="{lx}" y="{note_y}" font-size="17" fill="#516277">{esc(note1)}</text>')
    svg.append(f'<text x="{lx}" y="{note_y + 30}" font-size="17" fill="#516277">{esc(note2)}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def _gs_gate_lines(g: dict, limit: int = 2) -> list[str]:
    """菱形上写的条件行。未确认的排前面——它们决定这个门控为何还没放行。"""
    checks = [c for c in (g.get("checks") or []) if c.get("gate")]
    order = {"U": 0, "F": 1, "T": 2}
    checks.sort(key=lambda c: order.get(str(c.get("state")), 3))
    return [_clip(c.get("text"), 8) for c in checks[:limit]] or ["（无条件）"]


def _gs_gate_extra(g: dict, shown: int) -> int:
    """菱形上没写下的条件条数（图上用“… 另 N 条”提示，完整明细在报告/工作台里）。"""
    return max(0, len([c for c in (g.get("checks") or []) if c.get("gate")]) - shown)


def _gs_gate_title(g: dict) -> str:
    rows = [f"门控 {_gs_circled(int(g.get('seq') or 1))} · {g.get('state')}",
            f"放行到：{'、'.join(g.get('to_names') or [])}"]
    for c in g.get("checks") or []:
        mark = "✔" if c["state"] == "T" else ("✘" if c["state"] == "F" else "○")
        kind = {"effect": "换挡条件", "prior": "必要前提", "constraint": "持续约束",
                "context": "场景前提", "pre": "前置条件"}.get(c["kind"], c["kind"])
        rows.append(f"{mark} [{kind}] {c['text']}——{c.get('evidence') or c.get('verdict')}")
    rows.append(str(g.get("reason") or ""))
    return "\n".join(rows)


def _gs_node_title(n: dict) -> str:
    rows = [f"{n.get('name')}（{'持续保持' if str(n.get('mode') or '') == 'maintain' else '操作'}）",
            f"示范执行器：{'、'.join(n.get('executors') or []) or '—'}",
            (f"时间段：{n.get('start')}~{n.get('end')}s" if n.get("atomic_refs") else "时间段：未观察到独立动作时间"),
            f"操作意图：{n.get('intent') or '—'}"]
    coord = n.get("coordination") or {}
    if coord:
        act = "、".join(f"{c.get('executor', '')}{c.get('phrase') or c.get('action') or ''}"
                        for c in (coord.get("primary") or []) if c)
        hold_ = "、".join(f"{c.get('executor', '')}{c.get('phrase') or c.get('action') or ''}"
                          for c in (coord.get("holding") or []) if c)
        rows.append(f"本步主动：{act or '—'}；同步保持：{hold_ or '—'}")
    rows += ["前置条件：" + ("；".join(n.get("pre") or []) or "—"),
             "后置条件：" + ("；".join(n.get("post") or []) or "—")]
    return "\n".join(rows)


GS_KIND_CN = {"effect": "换挡条件", "prior": "必要前提", "constraint": "持续约束",
              "context": "场景前提", "pre": "前置条件"}
GS_STATE_BG = {"T": "#159474", "F": "#c0392b", "U": "#7b8794"}


def gates_html(bundle: dict) -> str:
    """门控明细：每个换挡点的条件、状态与依据（报告里的可核查那份）。"""
    gdoc = bundle.get("gates") or {}
    gates = gdoc.get("gates") or []
    if not gates:
        return '<div class="card muted">（无门控：未建出操作图）</div>'
    stats = gdoc.get("stats") or {}
    head = (f'<p class="legend">共 {stats.get("gates", 0)} 个门控：'
            f'<b>T {stats.get("T", 0)}</b>（放行）· <b>U {stats.get("U", 0)}</b>（等待证据）· '
            f'<b>F {stats.get("F", 0)}</b>（阻断）。T / F / U 只读已有证据：'
            f'观测到才 T，被否定才 F，其余一律 U——U 既不能当 T 放行，也不能当 F 判死。</p>')
    blocks = []
    for g in gates:
        state = str(g.get("state") or "U")
        seq = int(g.get("seq") or 1)
        rows = []
        for c in g.get("checks") or []:
            kind = GS_KIND_CN.get(str(c.get("kind")), str(c.get("kind")))
            color = GS_STATE_BG.get(str(c["state"]), "#7b8794")
            extra = ""
            if c.get("kind") == "context":
                extra = '<span class="muted">（不参与放行判定）</span>'
            if c.get("quality") == "rejected":
                extra += '<span class="muted">（该条件已被反证剔除，不再当必要条件）</span>'
            rows.append(
                f'<tr><td>{esc(c.get("text"))}{extra}</td><td>{esc(kind)}</td>'
                f'<td><span class="pill" style="background:{color}">{esc(c["state"])}</span></td>'
                f'<td class="muted">{esc(c.get("evidence") or c.get("verdict"))}</td></tr>')
        title = (f'门控 {_gs_circled(seq)} · {esc(g.get("id"))}'
                 f'<span class="pill" style="background:{GS_STATE_BG.get(state, "#7b8794")}">'
                 f'{esc(state)}</span>')
        sub = (f'输入：{esc("、".join(g.get("from_names") or []))}'
               f' → 放行到：{esc("、".join(g.get("to_names") or []))}'
               f'｜{esc(g.get("reason"))}')
        blocks.append(
            '<div class="card">'
            f'<h3>{title}</h3>'
            f'<div class="sub">{sub}</div>'
            '<table class="sched"><thead><tr><th>条件（来自七元组的 PRE / POST / CONST）</th>'
            '<th>类型</th><th>状态</th><th>依据</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')
    return head + "".join(blocks)


# ---------------------------------------------------------------
# 执行器语义程序图（给机器看的那一张）
# ---------------------------------------------------------------

PROG_W = 880
PROG_X, PROG_BLOCK_W = 56, 768
PROG_LINE_H = 17.5
PROG_LABEL_W = 70
PROG_LABEL_COLOR = {
    "when": "#1d4ed8", "trig": "#7c3aed", "do": "#0f766e",
    "while": "#b45309", "until": "#be123c",
}


def _program_lines(r: dict) -> list[tuple[str, str, str]]:
    """把一个操作展开成规则块里的行：(标签, 内容, 类型)。"""
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def lab(name: str, kind: str) -> str:
        if kind in seen:
            return ""
        seen.add(kind)
        return name

    for c in r.get("when") or []:
        rows.append((lab("WHEN", "when"), str(c), "when"))
    for d in (r.get("start_guard") or {}).get("dependencies") or []:
        ev = d.get("event") or {}
        ref = ev.get("ref")
        if ev.get("type") == "action_completed":
            text = (f"#{ref} 完成才发后续步骤（该动作产生：{d.get('predicate')}）")
        else:
            text = f"{ref} 完成后可发（提供：{d.get('predicate') or '前置条件'}）"
        rows.append((lab("TRIG", "trig"), text, "trig"))
    if not rows:
        rows.append(("WHEN", "（无显式前置条件）", "when"))
    caps = (r.get("command") or {}).get("required_capabilities") or []
    rows.append(("DO", f"执行「{r.get('name')}」"
                 + (f" — 能力要求：{'、'.join(caps)}" if caps else ""), "do"))
    demo = r.get("do") or []
    if demo:
        names = "、".join(f"{s['executor']}{s['action']}" for s in demo[:4])
        rows.append(("", f"示范实现：{names}（目标执行器待绑定）", "do"))
    for c in r.get("invariants") or []:
        rows.append((lab("WHILE", "while"), f"{c} —— 违反则暂停并重规划", "while"))
    for c in r.get("until") or []:
        rows.append((lab("UNTIL", "until"), str(c), "until"))
    if not r.get("until"):
        rows.append((lab("UNTIL", "until"), "完成条件未定，需补充（禁止用示范时间代替）", "until"))
    return rows


def program_svg(program: dict, task_intent: str = "") -> str:
    """给执行器看的图：每个操作一个规则块，读图即知“什么条件成立时、做什么、做到什么状态停”。

    与给人看的操作图同一份数据（result.json 的 program 字段），只是换一种读法：
    这里不强调“为什么做”（那是给人看的），只写“等什么、做什么、停在哪”。
    """
    ops = program.get("operations") or []
    if not ops:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="620" height="86" '
                'font-family="sans-serif"><text x="16" y="46" font-size="13" fill="#6b7280">'
                '（无操作，无法生成执行器程序图）</text></svg>')

    blocks = []
    y = 132.0
    for r in ops:
        rows = _program_lines(r)
        h = 40 + len(rows) * PROG_LINE_H + 34
        blocks.append((r, rows, y, h))
        y += h + 48
    height = int(y + 30)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{PROG_W}" height="{height}" '
        f'viewBox="0 0 {PROG_W} {height}" '
        f'font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">',
        f'<rect width="{PROG_W}" height="{height}" fill="#fbfcfe"/>',
        '<defs>',
        '<marker id="pg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker>',
        '<marker id="pg-trig" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#7c3aed"/></marker>',
        "</defs>",
    ]
    svg.append(f'<text x="{PROG_X}" y="34" font-size="15" font-weight="700" '
               f'fill="{COLOR["text"]}">执行器语义程序（读图即知：什么条件成立 → 做什么 → 做到什么状态停）</text>')
    if task_intent:
        svg.append(f'<text x="{PROG_X}" y="56" font-size="12" fill="#3f7fd0">'
                   f'任务意图：{esc(_clip(task_intent, 52))}</text>')
    svg.append(f'<text x="{PROG_X}" y="76" font-size="10.5" fill="{COLOR["muted"]}">'
               f'每个块 = 一个操作的执行规则；块之间 = 触发关系。执行器待绑定，'
               f'视频秒数仅为示范证据、不作调度依据。</text>')

    # 块之间的触发线
    for i in range(len(blocks) - 1):
        r0, _rows0, y0, h0 = blocks[i]
        r1, _rows1, y1b, _h1 = blocks[i + 1]
        deps = (r1.get("start_guard") or {}).get("dependencies") or []
        color = "#7c3aed" if deps else "#94a3b8"
        marker = "pg-trig" if deps else "pg-arrow"
        xc = PROG_X + PROG_BLOCK_W / 2
        ytop = y0 + h0 + 4
        ybot = y1b - 6
        svg.append(f'<line x1="{xc:.1f}" y1="{ytop:.1f}" x2="{xc:.1f}" y2="{ybot:.1f}" '
                   f'stroke="{color}" stroke-width="1.6" marker-end="url(#{marker})"/>')
        if deps:
            ev = (deps[0].get("event") or {})
            txt = f"⚡ 触发：{r0.get('name')} 的 #{ev.get('ref')} 完成"
            w = 14 + len(txt) * 9.4
            svg.append(f'<rect x="{xc - w / 2:.1f}" y="{(ytop + ybot) / 2 - 10:.1f}" '
                       f'width="{w:.1f}" height="19" rx="9.5" fill="#f3ecff" stroke="#c9b0f0"/>')
            svg.append(f'<text x="{xc:.1f}" y="{(ytop + ybot) / 2 + 3:.1f}" font-size="10" '
                       f'fill="#5b21b6" text-anchor="middle">{esc(txt)}</text>')
        else:
            txt = "先后推进"
            svg.append(f'<text x="{xc + 8:.1f}" y="{(ytop + ybot) / 2 + 3:.1f}" font-size="9.5" '
                       f'fill="{COLOR["muted"]}">{esc(txt)}</text>')

    # 规则块
    for r, rows, y0, h in blocks:
        blocked = r.get("startable") is False
        accent = "#be123c" if blocked else "#d97706"
        svg.append(f'<rect x="{PROG_X}" y="{y0:.1f}" width="{PROG_BLOCK_W}" height="{h:.1f}" '
                   f'rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>')
        svg.append(f'<rect x="{PROG_X}" y="{y0:.1f}" width="6" height="{h:.1f}" rx="3" '
                   f'fill="{accent}"/>')
        svg.append(f'<text x="{PROG_X + 18}" y="{y0 + 24:.1f}" font-size="13" '
                   f'font-weight="700" fill="{COLOR["text"]}">'
                   f'{esc(r.get("id"))} · {esc(_clip(r.get("name"), 22))}</text>')
        span = f"示范 {float(r.get('start', 0)):.1f}~{float(r.get('end', 0)):.1f}s"
        svg.append(f'<text x="{PROG_X + PROG_BLOCK_W - 16}" y="{y0 + 24:.1f}" font-size="10" '
                   f'fill="{COLOR["muted"]}" text-anchor="end">{esc(span)}</text>')
        ly = y0 + 46
        for label, text, kind in rows:
            color = PROG_LABEL_COLOR.get(kind, "#475569")
            if label:
                svg.append(f'<text x="{PROG_X + 18}" y="{ly:.1f}" font-size="11" '
                           f'font-weight="700" fill="{color}">{esc(label)}</text>')
            svg.append(f'<text x="{PROG_X + 18 + PROG_LABEL_W}" y="{ly:.1f}" font-size="11.5" '
                       f'fill="#1f2937">{esc(_clip(text, 66))}</text>')
            ly += PROG_LINE_H
        # 状态条：诚实说明“现在还不能直接跑”
        sy = y0 + h - 26
        if blocked:
            issues = r.get("blocked_by") or []
            txt = (f"静态问题 {len(issues)} 项："
                   + "；".join(str(x) for x in issues[:2]))
            bg, bd, fg = "#fdecec", "#f3c2c2", "#9b2c2c"
        else:
            txt = "执行前需：绑定目标执行器 + 落地谓词检测 + 资源检查（静态分析不判定可执行）"
            bg, bd, fg = "#fff8e6", "#f0dca8", "#8a5a12"
        svg.append(f'<rect x="{PROG_X + 10}" y="{sy:.1f}" width="{PROG_BLOCK_W - 20}" '
                   f'height="22" rx="8" fill="{bg}" stroke="{bd}"/>')
        svg.append(f'<text x="{PROG_X + 20}" y="{sy + 15:.1f}" font-size="10" '
                   f'fill="{fg}">{esc(_clip(txt, 76))}</text>')

    svg.append(f'<text x="{PROG_X}" y="{height - 14}" font-size="10.5" fill="{COLOR["muted"]}">'
               f'同一份数据也输出为 program.json（执行层读取）与 program.txt（伪代码）；'
               f'给人看的操作图见 operations.svg</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_program_graph(bundle: dict, out_dir: Path) -> Path:
    """独立 SVG 产物：给执行器看的语义程序图。"""
    intents = bundle.get("intents", {}).get("intents") or []
    intent = str(intents[0].get("statement") or "") if intents else ""
    svg = program_svg(bundle.get("program") or {}, intent)
    path = out_dir / "program.svg"
    path.write_text(svg.replace('<svg ', '<svg style="background:#fff" ', 1), encoding="utf-8")
    return path


def render_program(bundle: dict, out_dir: Path) -> Path:
    """独立产物：给执行器看的语义程序。

    program.json  结构化（执行层直接读：WHEN/DO/UNTIL + 执行器时刻表）
    program.txt   伪代码（人看，粘出去就能改写成代码）
    """
    prog = bundle.get("program") or {}
    (out_dir / "program.json").write_text(
        json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    path = out_dir / "program.txt"
    path.write_text("\n".join(prog.get("code") or []), encoding="utf-8")
    return path


VERDICT_CN = {
    "supported": "成立", "provided": "有来源", "ambient": "环境前提",
    "covered": "覆盖", "evidenced": "有证据", "order_only": "仅观测顺序",
    "unknown": "无法判定", "unsupported": "不成立",
    "unprovided": "无来源", "uncovered": "未覆盖", "weak": "缺证据",
    "evidenced_by_unclaimed": "找到未认领证据",
}
REVISION_CN = {
    "downgrade_edge": "依赖降级", "propose_gap": "提出候选缺口",
    "flag_for_review": "待复核",
}


def reasoning_html(bundle: dict) -> str:
    """推理修正：逐条追问「这个条件真的成立吗」，并展示由此产生的图修改。"""
    r = bundle.get("reasoning") or {}
    checks = r.get("checks") or []
    if not checks:
        return "<p class='muted'>（未生成推理修正记录）</p>"
    s = r.get("stats") or {}
    out = [f"<p>共 <b>{s.get('checks', 0)}</b> 条推理检查：成立 <b>{s.get('supported', 0)}</b>、"
           f"依赖降级 <b>{s.get('downgraded', 0)}</b>、候选缺口 <b>{s.get('gaps', 0)}</b>、"
           f"待复核 <b>{s.get('flagged', 0)}</b></p>"]

    revs = [x for x in (r.get("revisions") or []) if x.get("kind") != "flag_for_review"]
    if revs:
        out.append("<h3>修正实例（真的改了图）</h3>")
        for x in revs:
            out.append(
                f"<div class='card'><h4>{esc(REVISION_CN.get(str(x.get('kind')), x.get('kind')))}："
                f"{esc(x.get('target'))}</h4>"
                f"<table class='kv'><tr><th>原判断</th><td>{esc(x.get('before'))}</td></tr>"
                f"<tr><th>现结论</th><td>{esc(x.get('after'))}</td></tr>"
                f"<tr><th>依据</th><td>{esc(x.get('why'))}</td></tr>"
                f"<tr><th>处理方式</th><td>{esc(x.get('note'))}</td></tr></table></div>")
    else:
        out.append("<p class='muted'>本轮没有需要改图的地方：逐条追问后依赖均成立；"
                   "修正机制照常记录全部判定（见下表）。</p>")

    gaps = r.get("gaps") or []
    if gaps:
        out.append("<h3>候选缺口（推理提出、尚未当成事实）</h3>")
        out.append("<table class='tbl'><thead><tr><th>操作</th><th>缺什么条件</th>"
                   "<th>为什么算缺口</th><th>下一步</th></tr></thead><tbody>")
        for g in gaps:
            out.append(f"<tr><td>{esc(g.get('node_name'))}</td>"
                       f"<td>{esc(g.get('condition'))}</td>"
                       f"<td class='muted'>{esc(g.get('evidence'))}</td>"
                       f"<td class='muted'>{esc(g.get('candidate'))}（需找证据，不直接写成事实）</td></tr>")
        out.append("</tbody></table>")

    groups: dict[str, list[dict]] = {}
    for c in checks:
        groups.setdefault(str(c.get("kind")), []).append(c)
    titles = {"edge_support": "① 依赖追问：A 声称提供给 B 的那个条件，A 真的能产生吗",
              "pre_coverage": "② 前置覆盖：每条前置条件由谁提供",
              "hold": "③ 持续约束：需要一直成立的条件，过程内是否被保持动作覆盖",
              "evidence": "④ 预期 vs 证据：操作声明的效果在画面里有无落点"}
    for kind, items in groups.items():
        out.append(f"<h3>{esc(titles.get(kind, kind))}</h3>")
        out.append("<table class='tbl'><thead><tr><th>追问</th><th>结论</th>"
                   "<th>依据</th></tr></thead><tbody>")
        for c in items:
            v = str(c.get("verdict"))
            color = {"supported": "#2f9e6f", "provided": "#2f9e6f", "covered": "#2f9e6f",
                     "evidenced": "#2f9e6f", "ambient": "#6b7280",
                     "order_only": "#6b7280", "unknown": "#6b7280",
                     "unprovided": "#d64545", "unsupported": "#d64545",
                     "uncovered": "#e08a2e", "weak": "#e08a2e",
                     "evidenced_by_unclaimed": "#b45309"}.get(v, "#888")
            out.append(f"<tr><td>{esc(c.get('question'))}</td>"
                       f"<td><span class='pill' style='background:{color}'>"
                       f"{esc(VERDICT_CN.get(v, v))}</span></td>"
                       f"<td class='muted'>{esc(c.get('evidence'))}"
                       + (f"<div class='sub'>{esc(c.get('note'))}</div>" if c.get("note") else "")
                       + "</td></tr>")
        out.append("</tbody></table>")
    return "\n".join(out)


def intent_chain_html(bundle: dict) -> str:
    """意图链：每个操作为后继操作提供了哪条前置条件（因果关系的文本化）。"""
    chain = (bundle.get("operations") or {}).get("intent_chain") or []
    ops = {n["id"]: n for n in (bundle.get("operations") or {}).get("nodes") or []}
    if not chain:
        return "<p class='muted'>（未识别到显式的条件衔接）</p>"
    rows = []
    for c in chain:
        a, b = ops.get(c.get("from")), ops.get(c.get("to"))
        rows.append(
            f"<tr><td><b>{esc((a or {}).get('name'))}</b><div class='sub'>{esc(c.get('because'))}</div></td>"
            f"<td>为</td><td><b>{esc((b or {}).get('name'))}</b>"
            f"<div class='sub'>提供：{esc(c.get('provides'))}</div></td></tr>")
    return ("<table class='tbl'><thead><tr><th>前置操作的后置效果</th><th></th>"
            "<th>后继操作的前置条件</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


# ---------------------------------------------------------------
# 关系列表 / 叙述 / 卡片
# ---------------------------------------------------------------

def relations_html(bundle: dict) -> str:
    actions = bundle.get("atomic", {}).get("atomic_actions", [])
    relations = bundle.get("relations", [])
    if not relations:
        return "<p class='muted'>（无）</p>"
    amap = {a.get("id"): a for a in actions}
    # 规则推导的“不同部位同时进行”数量大且已在时序逻辑里合并成并行组，表格里只汇总一行
    rule_parallel = [r for r in relations
                     if r.get("inferred_by") == "rule" and str(r.get("relation")) == "parallel"]
    hide = {id(r) for r in rule_parallel}
    show = [r for r in relations if id(r) not in hide]
    if not show and not rule_parallel:
        return "<p class='muted'>（无）</p>"
    parts = ["<table class='tbl'><thead><tr><th>关系</th><th>说明</th><th>备注</th><th>来源</th></tr></thead><tbody>"]
    for r in show:
        a = amap.get(r.get("from"), {})
        b = amap.get(r.get("to"), {})
        tmpl = RELATION_TEXT.get(str(r.get("relation")), "{a} → {b}")
        text = tmpl.format(a=f"#{a.get('id')} {a.get('executor')}{a.get('action')}",
                           b=f"#{b.get('id')} {b.get('executor')}{b.get('action')}")
        src = {"vlm_window": "画面提取", "rule": "规则推导"}.get(str(r.get("inferred_by")), "画面提取")
        rel = str(r.get("relation"))
        parts.append(f"<tr><td><span class='pill' style='background:{REL_COLOR.get(rel, '#888')}'>"
                     f"{esc(rel)}</span></td><td>{esc(text)}</td>"
                     f"<td class='muted'>{esc(r.get('note') or '')}</td><td class='muted'>{esc(src)}</td></tr>")
    if rule_parallel:
        parts.append(f"<tr><td class='muted'>parallel×{len(rule_parallel)}</td>"
                     f"<td class='muted' colspan='3'>另有 {len(rule_parallel)} 条「不同部位同时进行」的规则推导关系，"
                     f"已在下方「时序逻辑表达」的并行组里合并展示</td></tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def narration_html(bundle: dict) -> str:
    groups = narrate_by_part(bundle.get("atomic", {}).get("atomic_actions", []))
    if not groups:
        return "<p class='muted'>（无动作）</p>"
    blocks = []
    for g in groups:
        items = []
        for s in g["steps"]:
            tags = " ".join(f"<span class='tag'>{esc(t)}</span>" for t in s["tags"])
            extra = ""
            if s.get("until"):
                extra += f"<div class='sub'>持续到：{esc(s['until'])}</div>"
            if s.get("reason"):
                extra += f"<div class='sub'>推理理由：{esc(s['reason'])}</div>"
            obj = f" · 作用对象：{esc(s['object'])}" if s.get("object") else ""
            items.append(
                f"<li><span class='t'>{esc(s['span'])}</span> "
                f"<b>{esc(s['action'])}</b>{obj}<br>"
                f"<span class='sub'>{esc(s['state'])}</span> {tags}{extra}</li>")
        blocks.append(f"<div class='part'><h4>{esc(g['part'])}"
                      f"<span class='muted'>（不给力时：{esc(g['rest'])}）</span></h4>"
                      f"<ul class='acts'>{''.join(items)}</ul></div>")
    return "\n".join(blocks)


def flow_html(bundle: dict) -> str:
    """任务级流程（节点按时序排列的图结构）。"""
    nodes = bundle.get("task_nodes", {}).get("task_nodes", [])
    if not nodes:
        return ""
    ordered = sorted(nodes, key=lambda n: (n.get("time_range") or [1e9])[0])
    items = []
    for n in ordered:
        t = n.get("tuple") or {}
        parts = (t.get("X") or {}).get("parts") or []
        tr = n.get("time_range") or []
        span = f"{tr[0]}~{tr[1]}s" if len(tr) == 2 else ""
        items.append(
            f"<div class='flownode'><b>{esc(n.get('name'))}</b>"
            f"<div class='sub'>{esc(n.get('id'))} · {esc(span)}</div>"
            f"<div class='sub'>部位：{esc('、'.join(parts) or '—')}</div></div>")
    return "<div class='flow'>" + "<div class='arrow'>→</div>".join(items) + "</div>"


def nodes_html(bundle: dict) -> str:
    nodes = bundle.get("task_nodes", {}).get("task_nodes", [])
    if not nodes:
        return "<p class='muted'>（无）</p>"
    blocks = []
    for n in nodes:
        t = n.get("tuple", {})
        x = t.get("X") or {}
        refs = "、".join(f"#{r}" for r in (n.get("atomic_refs") or [])) or "（未绑定）"
        r_rows = []
        for r in t.get("R") or []:
            origin = "本视频做法" if r.get("origin") == "observed" else "备选做法"
            steps = " → ".join(str(s) for s in (r.get("steps") or []))
            r_rows.append(f"<li><b>{esc(r.get('name'))}</b> "
                          f"<span class='tag'>{esc(origin)}</span>"
                          + (f"<div class='sub'>{esc(steps)}</div>" if steps else "") + "</li>")
        e = t.get("E") or {}
        blocks.append(f"""
<div class='card'>
  <h3>{esc(n.get('id'))} · {esc(n.get('name'))} <span class='muted'>{esc(n.get('time_range') or '')}</span></h3>
  <p class='sub'>{esc(n.get('intent_role') or '')}</p>
  <table class='kv'>
    <tr><th>X 执行主体</th><td>{esc(x.get('subject'))}｜部位：{esc('、'.join(x.get('parts') or []))}</td></tr>
    <tr><th>O 操作对象</th><td>{esc('、'.join(t.get('O') or []))}</td></tr>
    <tr><th>C_pre 前置条件</th><td>{'<br>'.join('· ' + esc(c) for c in (t.get('C_pre') or [])) or '—'}</td></tr>
    <tr><th>C_const 约束元</th><td>{'<br>'.join('· ' + esc(c) for c in (t.get('C_const') or [])) or '—'}</td></tr>
    <tr><th>E 评价指标</th><td>过程：{'；'.join(esc(s) for s in (e.get('process') or [])) or '—'}<br>
        完成：{'；'.join(esc(s) for s in (e.get('completion') or [])) or '—'}</td></tr>
    <tr><th>C_post 后置效果</th><td>{'<br>'.join('· ' + esc(c) for c in (t.get('C_post') or [])) or '—'}</td></tr>
    <tr><th>R 候选方式集合</th><td><ul class='tight'>{''.join(r_rows) or '<li>—</li>'}</ul></td></tr>
    <tr><th>对应动作</th><td>{esc(refs)}</td></tr>
  </table>
</div>""")
    return "\n".join(blocks)


def sync_html(bundle: dict) -> str:
    sync = bundle.get("sync", {})
    if not sync:
        return "<p class='muted'>（无）</p>"
    rows = []
    for c in sync.get("checks", []):
        verdict = str(c.get("verdict"))
        color = {"yes": "#2f9e6f", "partial": "#e08a2e", "no": "#d64545"}.get(verdict, "#888")
        detail = c.get("detail") or c.get("missing") or c.get("inconsistencies") or []
        detail_html = "<br>".join("· " + esc(d) for d in detail)
        rows.append(f"<div class='check'><span class='pill' style='background:{color}'>"
                    f"{esc(verdict)}</span> <b>{esc(c.get('question'))}</b>"
                    f"<div>{esc(c.get('reason'))}</div>"
                    + (f"<div class='sub'>{detail_html}</div>" if detail_html else "") + "</div>")
    delta = ""
    if sync.get("intent_confidence_before") is not None and sync.get("intent_confidence_after") is not None:
        delta = (f"<p>意图置信度：<b>{sync['intent_confidence_before']}</b> → "
                 f"<b>{sync['intent_confidence_after']}</b>　"
                 f"<span class='sub'>{esc(sync.get('confidence_rationale') or '')}</span></p>")
    rev = sync.get("revisions") or {}
    rev_html = ""
    for key, title in (("to_intent", "对意图的修订"), ("to_graph", "对操作图的修订")):
        items = rev.get(key) or []
        if items:
            rev_html += f"<h4>{title}</h4><ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"
    return delta + "".join(rows) + rev_html


def conditions_html(bundle: dict) -> str:
    cond = bundle.get("conditions", {})
    if not cond:
        return "<p class='muted'>（无）</p>"
    out = []
    for item in cond.get("condition_learning", []):
        for key, title in (("C_pre_learning", "前置条件 C_pre"),
                           ("C_post_learning", "后置效果 C_post")):
            for e in item.get(key) or []:
                verdict = str(e.get("verdict"))
                color = {"有效": "#2f9e6f", "部分有效": "#e08a2e",
                         "无效或过度约束": "#d64545", "证据不足": "#6b7280"}.get(verdict, "#888")
                pos = e.get("positive") or {}
                na = e.get("negative_a") or {}
                nb = e.get("negative_b") or {}
                out.append(f"""
<div class='card'>
  <h4><span class='pill' style='background:{color}'>{esc(verdict)}</span>
  {esc(item.get('node_id'))} · {esc(title)}：{esc(e.get('condition'))}</h4>
  <table class='kv'>
    <tr><th>正例（成功）</th><td>{esc(pos.get('text'))}<div class='sub'>{esc(pos.get('evidence') or pos.get('reason') or '')}</div></td></tr>
    <tr><th>反例A（失败执行）</th><td>{esc(na.get('text'))}<div class='sub'>{esc(na.get('reason') or '')}</div></td></tr>
    <tr><th>反例B（未执行/未达预期）</th><td>{esc(nb.get('text'))}<div class='sub'>{esc(nb.get('reason') or '')}</div></td></tr>
  </table>
</div>""")
    summary = cond.get("effective_conditions_summary") or []
    if summary:
        out.append("<h4>经正反例检验后成立的条件</h4><ul>"
                   + "".join(f"<li>{esc(s)}</li>" for s in summary) + "</ul>")
    rejected = cond.get("rejected_conditions") or []
    if rejected:
        out.append("<h4>被剔除的条件</h4><ul>"
                   + "".join(f"<li>{esc(r.get('condition'))} —— {esc(r.get('why'))}</li>" for r in rejected)
                   + "</ul>")
    return "\n".join(out)


def rules_html(bundle: dict) -> str:
    rules = bundle.get("rules", {})
    if not rules:
        return "<p class='muted'>（无）</p>"
    out = ["<h3>5.1 时序结构</h3><table class='tbl'><thead><tr><th>模式</th><th>尺度</th>"
           "<th>成员</th><th>规则</th></tr></thead><tbody>"]
    for t in rules.get("temporal_structures", []):
        color = REL_COLOR.get(str(t.get("pattern")).lower(), "#888")
        out.append(f"<tr><td><span class='pill' style='background:{color}'>{esc(t.get('pattern'))}</span></td>"
                   f"<td>{esc(t.get('level'))}</td><td>{esc(' / '.join(t.get('members') or []))}</td>"
                   f"<td>{esc(t.get('statement'))}<div class='sub'>{esc(t.get('evidence'))}</div></td></tr>")
    out.append("</tbody></table>")
    out.append("<h3>5.2 语义约束</h3><table class='tbl'><thead><tr><th>类型</th><th>约束</th>"
               "<th>适用</th><th>违反后果</th></tr></thead><tbody>")
    for c in rules.get("constraints", []):
        out.append(f"<tr><td>{esc(c.get('type'))}</td><td>{esc(c.get('statement'))}"
                   f"<div class='sub'>{esc(c.get('reason'))}</div></td>"
                   f"<td>{esc('、'.join(c.get('applies_to') or []))}</td>"
                   f"<td>{esc(c.get('violation_consequence'))}</td></tr>")
    out.append("</tbody></table>")
    out.append("<h3>5.3 评价器</h3><table class='tbl'><thead><tr><th>节点</th><th>过程判据</th>"
               "<th>完成判据</th><th>失败信号</th></tr></thead><tbody>")
    for e in rules.get("evaluators", []):
        out.append(f"<tr><td>{esc(e.get('node_id'))}</td>"
                   f"<td>{'；'.join(esc(x) for x in (e.get('process') or []))}</td>"
                   f"<td>{'；'.join(esc(x) for x in (e.get('completion') or []))}</td>"
                   f"<td>{'；'.join(esc(x) for x in (e.get('failure_signals') or []))}</td></tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def validation_html(bundle: dict) -> str:
    v = bundle.get("validation", {})
    if not v:
        return "<p class='muted'>（无）</p>"
    color = "#2f9e6f" if v.get("passed") else "#d64545"
    out = [f"<p><span class='pill' style='background:{color}'>"
           f"{'通过' if v.get('passed') else '未通过'}</span> {esc(v.get('summary'))}</p>"]
    for c in v.get("checks", []):
        scolor = {"pass": "#2f9e6f", "warn": "#e08a2e", "fail": "#d64545"}.get(str(c.get("status")), "#888")
        detail = c.get("detail") or []
        items = ""
        if detail:
            rendered = []
            for d in detail[:12]:
                if isinstance(d, dict):
                    rendered.append(esc("；".join(f"{k}={v2}" for k, v2 in d.items() if v2 not in (None, "", []))))
                else:
                    rendered.append(esc(d))
            items = "<ul>" + "".join(f"<li>{x}</li>" for x in rendered) + "</ul>"
        out.append(f"<div class='check'><span class='pill' style='background:{scolor}'>"
                   f"{esc(c.get('status'))}</span> <b>{esc(c.get('name'))}</b>{items}</div>")
    return "\n".join(out)


# ---------------------------------------------------------------
# 页面
# ---------------------------------------------------------------

CSS = """
body{font-family:-apple-system,Segoe UI,Microsoft YaHei,Helvetica,Arial,sans-serif;
 color:#22272e;margin:0;background:#f2f4f8;line-height:1.6}
.wrap{max-width:1300px;margin:0 auto;padding:24px 18px 80px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px;border-left:4px solid #3f7fd0;padding-left:10px}
h3{font-size:15px;margin:18px 0 8px}h4{font-size:14px;margin:12px 0 6px}
.card{background:#fff;border:1px solid #e3e8ef;border-radius:8px;padding:12px 14px;margin:10px 0}
.muted{color:#6b7280;font-weight:400;font-size:12px}
.sub{color:#6b7280;font-size:12px}
.tbl{width:100%;border-collapse:collapse;background:#fff;font-size:13px}
.tbl th,.tbl td{border:1px solid #e3e8ef;padding:6px 8px;text-align:left;vertical-align:top}
.tbl th{background:#f7f9fc;font-weight:600}
.kv{width:100%;border-collapse:collapse;font-size:13px}
.kv th{width:150px;text-align:left;vertical-align:top;color:#4b5563;font-weight:600;padding:4px 8px 4px 0;border-top:1px solid #eef1f6}
.kv td{padding:4px 0;border-top:1px solid #eef1f6}
.pill{display:inline-block;color:#fff;border-radius:10px;padding:1px 8px;font-size:11px;margin-right:4px}
.tag{display:inline-block;background:#eef2f8;color:#3f566f;border-radius:8px;padding:0 6px;font-size:11px;margin-right:4px}
.part{background:#fff;border:1px solid #e3e8ef;border-radius:8px;padding:8px 12px;margin:8px 0}
ul.acts{margin:4px 0 4px 18px;padding:0}ul.acts li{margin:6px 0}
ul.tight{margin:0 0 0 16px;padding:0}
.t{display:inline-block;min-width:96px;color:#3f7fd0;font-variant-numeric:tabular-nums}
.check{background:#fff;border:1px solid #e3e8ef;border-radius:8px;padding:8px 12px;margin:8px 0}
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:6px;background:#fff;
 border:1px solid #e3e8ef;border-radius:8px;padding:12px;margin:8px 0}
.flownode{background:#eef4fd;border:1px solid #cddff5;border-radius:6px;padding:6px 10px;font-size:13px}
.arrow{color:#94a3b8;align-self:center;font-size:16px}
.legend{font-size:12px;color:#4b5563}
.logic{background:#0f172a;color:#e2e8f0;border-radius:8px;padding:12px 14px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.7;
 white-space:pre-wrap;overflow-x:auto}
.warnbox{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:10px 12px}
""" + program_mod.STYLE


def render_timeline(bundle: dict, out_dir: Path) -> Path:
    name = bundle.get("meta", {}).get("name", "case")
    svg = gantt_svg(bundle)
    (out_dir / "timeline.svg").write_text(
        svg.replace('<svg ', '<svg style="background:#fff" ', 1), encoding="utf-8")
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(name)} · 执行器时间轴</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{esc(name)} · 执行器操作时间轴</h1>
<p class="muted">视频 {esc(bundle.get('meta', {}).get('duration'))}s ｜ 视角：{esc(bundle.get('viewpoint', {}).get('label_cn'))}
 ｜ 主体：{esc(bundle.get('viewpoint', {}).get('operator'))}</p>
<p>{esc(bundle.get('intents', {}).get('intents', [{}])[0].get('statement') if bundle.get('intents', {}).get('intents') else '')}
 <span class="muted">（意图置信度 {esc((bundle.get('intents', {}).get('intents') or [{}])[0].get('confidence', ''))}）</span></p>
<div class="card">{svg}</div>
<p class="legend">提示：鼠标悬停色块可看动作详情；虚线框表示由意图推理补全的动作；
 白点表示该时段持续给力。</p>
<h2>动作叙述（按部位）</h2>
{narration_html(bundle)}
<h2>时序关系</h2>
{relations_html(bundle)}
<h2>时序逻辑表达（机器可读）</h2>
<div class="card">{logic_mod.render_html(bundle.get('temporal_logic') or {})}</div>
</div></body></html>"""
    path = out_dir / "timeline.html"
    path.write_text(page, encoding="utf-8")
    return path


def expansion_html(bundle: dict) -> str:
    """操作展开：每个操作内部有哪些可调度的子操作、什么关系、检查点在哪。"""
    ex = bundle.get("expansion") or {}
    items = ex.get("operations") or []
    if not items:
        return "<p class='muted'>（尚无展开数据）</p>"
    st = ex.get("stats") or {}
    out = [f"<p class='legend'>共 {st.get('operations', 0)} 个操作、{st.get('sub_operations', 0)} 个子操作，"
           f"其中可展开 {st.get('expandable', 0)} 个、检查点 {st.get('checkpoints', 0)} 个。"
           f"子操作全部来自已定稿的原子动作表：<b>展开只换粒度，不新增动作或状态</b>。</p>"]
    for item in items:
        subs = item.get("sub_operations") or []
        if not subs:
            continue
        rows = "".join(
            f"<tr><td>{esc(s['id'])}</td><td>{esc(s['name'])}"
            + ("<span class='sub'>（推理补全，待核实）</span>" if s.get("inferred") else "")
            + f"</td><td>{esc(s['executor'])}</td>"
            f"<td>{esc(s['capability'])}</td>"
            f"<td class='muted'>{esc(s['mode'])}</td>"
            f"<td>{_fmt(s['start'])}~{_fmt(s['end'])}s</td>"
            f"<td class='muted'>{esc(_clip(str(s.get('pre') or '—'), 22))} → "
            f"{esc(_clip(str(s.get('post') or '—'), 22))}</td></tr>"
            for s in subs)
        rels = "".join(
            f"<li>{esc(r['from'])} → {esc(r['to'])}"
            f" <span class='pill' style='background:#eef2f8'>{esc(r['relation'])}</span>"
            f" <span class='muted'>{esc(r.get('note') or '')}</span></li>"
            for r in item.get("relations") or []) or "<li class='muted'>（单步子操作，无内部关系）</li>"
        checks = "".join(
            f"<li>{esc(c['question'])}"
            f" <span class='pill' style='background:#fff8e6'>{esc(c['kind'])}</span>"
            f" <span class='muted'>{esc(c.get('note') or '')}</span></li>"
            for c in item.get("checkpoints") or []) or "<li class='muted'>（无检查点）</li>"
        out.append(f"""<div class='card'>
<h3>{esc(item['id'])} · {esc(item['name'])}
  <span class='muted'>{_fmt(item['time_range'][0])}~{_fmt(item['time_range'][1])}s</span>
  <span class='pill' style='background:{'#e8f5ec' if item.get('expandable') else '#eef2f8'}'>"
  f"{'可展开 ' + str(len(subs)) + ' 个子操作' if item.get('expandable') else '单一执行单元'}</span></h3>
<div class='sub'>操作意图：{esc(item.get('intent') or '—')}</div>
<table class='sched'><thead><tr><th>子操作</th><th>动作</th><th>执行器</th>
<th>能力需求</th><th>模式</th><th>时段</th><th>状态变化</th></tr></thead><tbody>{rows}</tbody></table>
<div class='sub'>子操作之间的关系：</div><ul class='tight'>{rels}</ul>
<div class='sub'>执行层要设的检查点：</div><ul class='tight'>{checks}</ul>
</div>""")
    return "\n".join(out)


def contract_html(bundle: dict) -> str:
    """可执行契约：导出给执行侧的语义图、谓词表与验证方式。"""
    c = bundle.get("contract") or {}
    nodes = c.get("nodes") or {}
    table = bundle.get("predicates") or {}
    preds = table.get("predicates") or []
    if not nodes:
        return "<p class='muted'>（尚未导出契约）</p>"
    rows = []
    for nid, n in nodes.items():
        role = "MAINTAIN" if str(n.get("mode")) == "MAINTAIN" else ""
        until = "、".join(n.get("maintain_until") or [])
        mu = ("<br><span class='muted'>maintain_until: " + esc(until) + "</span>") if until else ""
        x = n.get("x-video2op") or {}
        rows.append(
            f"<tr><td>{esc(nid)}</td><td>{esc(n.get('name'))}"
            + (f"<br><span class='pred post'>{esc(role)}</span>" if role else "")
            + f"</td><td>{esc(n.get('phase'))}</td><td>{esc(n.get('subject'))}</td>"
            f"<td class='muted'>{esc('、'.join(n.get('pre') or []) or '—')}</td>"
            f"<td class='muted'>{esc('、'.join(n.get('post') or []) or '—')}</td>"
            f"<td class='muted'>{esc('、'.join(n.get('implementation') or []))}</td>"
            f"<td class='muted'>{esc('、'.join(n.get('dependencies') or []) or '—')}"
            f"<br><span class='sub'>{esc(_clip(str(x.get('operation_name') or ''), 14))}</span>{mu}</td></tr>")
    pred_rows = "".join(
        f"<tr><td>{esc(p['id'])}</td><td>{esc(p['text'])}</td>"
        f"<td class='muted'>{esc(p['verb'])}</td><td class='muted'>{esc(p.get('agent'))}</td>"
        f"<td class='muted'>{esc(p.get('polarity'))}</td></tr>"
        for p in preds[:40])
    more = (f"<p class='sub'>（共 {len(preds)} 条，此处列前 40 条；完整表在 result.json 的"
            f" <code>predicates</code>）</p>") if len(preds) > 40 else ""
    return f"""<p class='legend'>导出两份文件：<code>semantic_graph.yaml</code>（语义图，字段对齐执行侧的
节点 schema）与 <code>execution_policy.yaml</code>（实现选择策略，参数与超时留空待绑定）。
条件在契约里用<b>谓词名</b>表示，原文保留在谓词表里——导出只给条件命名，不改写条件。
<b>这一步不代表机器人已能执行</b>：谓词检测器、参数绑定和真实动作实现都要在执行侧接上。</p>

<h3>谓词表（图上的条件名）</h3>
<table class='sched'><thead><tr><th>谓词</th><th>原文</th><th>谓语</th><th>主体</th><th>极性</th></tr></thead>
<tbody>{pred_rows}</tbody></table>{more}

<h3>导出的语义图节点</h3>
<table class='sched'><thead><tr><th>节点</th><th>名称</th><th>阶段</th><th>执行主体</th>
<th>前置（谓词）</th><th>后置（谓词）</th><th>候选方式</th><th>依赖</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>

<h3>怎么验证它接得上</h3>
<div class='card'><div class='code'>python tools/verify_contract.py {esc(c.get('graph_id'))}
# 1 用执行侧的 load_operation_graph 加载 —— 字段与依赖环在加载时就被拒绝
# 2 用 GraphInstantiator 绑到 TaskContext 上 —— 看执行器/实现/资源接不接得上
# 3 用 Dummy 动作跑一遍调度 —— 看依赖顺序与 MAINTAIN 生命周期走得通不通
# 4 列出还需注册的谓词检测器 —— 这就是“待绑定”的具体内容</div></div>"""


def render_report(bundle: dict, out_dir: Path) -> Path:
    name = bundle.get("meta", {}).get("name", "case")
    intents = bundle.get("intents", {}).get("intents", [])
    op_graph = bundle.get("operations") or {}
    gate_graph = gate_svg(bundle)
    gate_detail = gates_html(bundle)
    orchestration = str(op_graph.get("orchestration") or "")
    intent_html = ""
    for it in intents:
        parts = "、".join(f"{bp.get('part')}（{bp.get('role')}）" for bp in it.get("required_body_parts", []))
        ev = "<br>".join(f"· {e.get('t')}s {e.get('what')}" for e in (it.get("evidence") or [])
                         if isinstance(e, dict))
        intent_html += f"""<div class='card'>
<h3>{esc(it.get('id'))} · {esc(it.get('statement'))}
 <span class='pill' style='background:#3f7fd0'>置信度 {esc(it.get('confidence'))}</span>
 <span class='muted'>{esc(it.get('intent_type'))}</span></h3>
<table class='kv'>
<tr><th>为何是这个意图</th><td>{ev}</td></tr>
<tr><th>所需身体部位</th><td>{esc(parts) or '—'}</td></tr>
<tr><th>所需能力</th><td>{esc('、'.join(it.get('required_capabilities') or [])) or '—'}</td></tr>
<tr><th>期望终态</th><td>{esc(it.get('expected_final_state')) or '—'}</td></tr>
</table></div>"""

    meta = bundle.get("meta", {})
    vp = bundle.get("viewpoint", {})
    html_doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(name)} · 操作图报告</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{esc(name)} · 任务语义操作图报告</h1>
<p class="muted">时长 {esc(meta.get('duration'))}s ｜ {esc(meta.get('width'))}×{esc(meta.get('height'))} @{esc(meta.get('fps'))}fps
 ｜ 生成流水线 video2op v{esc(bundle.get('pipeline', {}).get('code_version'))}</p>

<h2>操作图 · 门控状态机（节点 = 操作，菱形 = 门控）</h2>
<p class="legend">这是交付主图：圆 = 操作（只写动作，保持类操作画成暖色框），菱形 = <b>门控</b>——
 前序操作的效果、下一操作的前置条件、以及必须持续成立的约束同时成立，才放行。
 <b>实线</b>＝门控已确认为 T（放行）；<b>虚线</b>＝U 等待证据 / F 阻断 / 持续约束（保持覆盖后续动作），
 连线只用黑色、只有实线与虚线两种线型；图面上不写 T/U/F 字母，状态与依据在悬停与下面的门控明细里。
 同一列 = 时间上重叠的一组操作（并行泳道上下排），列与列之间就是一次换挡；
 行首标题是该段的起止操作与示范时间。悬停节点 / 菱形看前置、后置条件与证据。
 （卡片式操作图保留在 `render.operation_svg`，需要看节点缺口红条时用。）</p>
<div class="card" style="overflow-x:auto">{gate_graph}</div>

<h3>门控明细：每个换挡点凭什么放行</h3>
{gate_detail}
<h3>调度口径（先做什么、谁和谁一起做）</h3>
<div class="card">{esc(orchestration) or '<span class="muted">（无）</span>'}</div>
<h3>意图链：每个操作为了什么</h3>
{intent_chain_html(bundle)}

<h2>待绑定的操作语义契约</h2>
<p class="legend">每个操作给出 <b>WHEN / DO / UNTIL</b> 与持续约束。
目标执行器、技能、谓词检测器和资源约束仍需绑定；视频时间只用于追溯示范。
证据缺口与未知条件保留待核实，不把静态分析等同于机器人可启动。</p>
{program_mod.render_html(bundle.get('program') or {})}

<h2>操作展开：每个操作内部怎么执行</h2>
<p class='legend'>概览图上一步是一个节点；展开后能看到它里面的子操作、它们的关系，
以及执行层要在哪里设检查点。<b>保持覆盖</b>（hold_covers）表示后者在前者持续成立期间完成，
不是简单的“同时发生”。</p>
{expansion_html(bundle)}

<h2>可执行契约：交给执行侧的那一份</h2>
{contract_html(bundle)}

<h2>推理修正：每条依赖真的成立吗</h2>
<p class="legend">对图里每条候选依赖追问两件事：<b>它声称提供的条件是什么</b>、
<b>前一步是否真的能产生这个条件</b>。结论分四类：成立 / 依赖降级（因果不成立，
只保留观测到的先后）/ 候选缺口（条件无人提供，需找证据）/ 待复核。
机器只改<b>依赖与必要子图</b>，不改写视频事实：被降级的节点仍然在图上，
只是不再声称它使能了后一步。</p>
{reasoning_html(bundle)}

<h2>① 视角判别</h2>
<div class="card"><b>{esc(vp.get('label_cn'))}</b>
 <span class="pill" style="background:#3f7fd0">置信度 {esc(vp.get('confidence'))}</span>
 <div>操作者：{esc(vp.get('operator'))}；场景：{esc(vp.get('scene'))}</div>
 <div class="sub">依据：{esc('；'.join(vp.get('evidence') or []))}</div>
 <div class="sub">可见部位：{esc('、'.join(vp.get('visible_parts_hint') or []))}；物体：{esc('、'.join(vp.get('visible_objects') or []))}</div>
</div>

<h2>② 2a 任务意图（含置信度与所需部位）</h2>
{intent_html}

<h2>② 2b 执行器时间轴</h2>
<div class="card">{gantt_svg(bundle)}</div>

<h2>② 2b 执行器级动作依赖图（追溯视图）</h2>
<p class="legend">上面那张操作图是交付主图；这一张是它下面的<b>可追溯视图</b>：节点是执行器级原子动作（哪个部位、第几秒、做了什么），
箭头是先后/使能/保持依赖。同一列的动作在时间上并行或交替进行（图宽时可在卡片内横向滚动）。</p>
<div class="card" style="overflow-x:auto">{dag_svg(bundle.get('graph') or {})}</div>

<h2>② 2b 动作叙述（按部位）</h2>
{narration_html(bundle)}

<h2>② 2b 时序关系</h2>
{relations_html(bundle)}

<h2>② 2b 时序逻辑表达（机器可读）</h2>
<div class="card">{logic_mod.render_html(bundle.get('temporal_logic') or {})}</div>

<h2>② 2b 任务级操作节点（七元组）</h2>
{flow_html(bundle)}
{nodes_html(bundle)}

<h2>③ 同步因果检验</h2>
{sync_html(bundle)}

<h2>④ 正反例条件学习</h2>
{conditions_html(bundle)}

<h2>⑤ 语义层规则</h2>
{rules_html(bundle)}

<h2>⑥ 校验与待复核</h2>
{validation_html(bundle)}
</div></body></html>"""
    path = out_dir / "report.html"
    path.write_text(html_doc, encoding="utf-8")
    return path

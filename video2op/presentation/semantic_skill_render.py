"""Escaped, standalone two-layer diagrams of model-produced semantic knowledge."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from .case_graph_render import _svg_text_lines


def esc(value):
    return html.escape(str(value), quote=True)


def _circled(n):
    from ..render import GS_CIRCLED

    return GS_CIRCLED[n - 1] if 1 <= n <= len(GS_CIRCLED) else str(n)


def _sentences(value):
    if isinstance(value, dict):
        return "；".join(f"{key}：{val}" for key, val in value.items()) or "—"
    if isinstance(value, (list, tuple)):
        return "；".join(str(v) for v in value) or "—"
    return str(value or "—")


def _skill_detail(skill, node):
    evaluator = skill.get("E") or {}
    lines = [f'{node.get("id")} {skill.get("name")}',
             f'目的：{skill.get("purpose")}',
             f'X 执行者：{_sentences(skill.get("X"))}',
             f'O 对象：{_sentences(skill.get("O"))}',
             f'C_pre 进入条件：{_sentences(skill.get("C_pre"))}',
             f'C_const 过程约束：{_sentences(skill.get("C_const"))}',
             f'E 完成：{_sentences(evaluator.get("completion"))}',
             f'E 过程：{_sentences(evaluator.get("process_constraint"))}',
             f'E 适用：{_sentences(evaluator.get("implementation_applicability"))}',
             f'C_post 预期效果：{_sentences(skill.get("C_post"))}',
             f'R：{", ".join(skill.get("R") or []) or "—"}',
             f'局部结果：{node.get("outcome") or "unknown"}']
    if node.get("occurrence") == "rule_only":
        lines.append(f'规则补充：{node.get("reason") or "无来源观察"}')
    return "\n".join(lines)


def _visual_flow(graph):
    """Start/gate/skill/end view; source task nodes and relations stay unchanged."""
    skills = {s["id"]: s for s in graph["skills"]}
    task = graph["task_nodes"]
    if not task:
        return {"nodes": [], "edges": [], "start_node_id": "__start__", "end_node_id": "__end__"}, {}
    ids = {n["id"] for n in task}
    visual_nodes = [
        {"id": "__start__", "kind": "terminal", "label": "开始", "truth": "U"},
        {"id": "__end__", "kind": "terminal", "label": "结束", "truth": "U"},
    ]
    for node in task:
        skill = skills[node["skill_id"]]
        visual_nodes.append({"id": node["id"], "kind": "skill",
                             "label": node.get("name") or skill["name"],
                             "truth": "U", "occurrence": node.get("occurrence", "observed"),
                             "detail": _skill_detail(skill, node)})
    visual_edges, notes = [], {}
    gate_count = 0

    def new_gate(skill_id, check=None):
        nonlocal gate_count
        gate_count += 1
        gate_id = f"__gate_{gate_count}__"
        skill = skills[skill_id]
        check = check or {}
        lines = [f'门控 {_circled(gate_count)} · {check.get("guard_truth") or "U"}',
                 f'进入「{skill.get("name")}」的条件检查',
                  f'条件：{check.get("guard") or _sentences(skill.get("C_pre"))}',
                  f'当前上下文：{_sentences(check.get("check_context"))}',
                 "U 既不能当 T 放行，也不能当 F 判死。"]
        visual_nodes.append({"id": gate_id, "kind": "gate", "label": f"门控 {_circled(gate_count)}",
                              "truth": check.get("guard_truth") or "U", "detail": "\n".join(lines)})
        notes[gate_id] = skill_id
        return gate_id

    by_source = {}
    for rel in graph.get("relations") or []:
        by_source.setdefault(rel.get("from"), []).append(rel)
    for source, rows in by_source.items():
        if source not in ids:
            continue
        rows = [rel for rel in rows if rel.get("to") in ids]
        if not rows:
            continue
        branching = len(rows) > 1 and any(rel.get("relation") == "branch" for rel in rows)
        if branching:
            by_id = {n["id"]: n for n in task}
            check = next((rel for rel in rows if rel.get("guarded_skill_id") in skills), None)
            true_target = next((rel["to"] for rel in rows if rel.get("gate_outcome") == "T"), rows[0]["to"])
            guarded = check["guarded_skill_id"] if check else by_id[true_target]["skill_id"]
            gate_id = new_gate(guarded, check or next((r for r in rows if r.get("gate_outcome") == "T"), rows[0]))
            visual_edges.append({"from": source, "to": gate_id, "label": ""})
            for rel in rows:
                outcome = rel.get("gate_outcome")
                if outcome not in {"T", "F"}:
                    outcome = rel.get("guard_truth") if rel.get("guard_truth") in {"T", "F"} else None
                visual_edges.append({"from": gate_id, "to": rel["to"], "label": "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed"})
            continue
        for rel in rows:
            target = rel["to"]
            skill = skills[next(n for n in task if n["id"] == target)["skill_id"]]
            outcome = rel.get("gate_outcome")
            if skill.get("C_pre") or rel.get("condition_check"):
                check = rel.get("condition_check") or {}
                gate_id = new_gate(check.get("guarded_skill_id") or next(n for n in task if n["id"] == target)["skill_id"], check)
                visual_edges.append({"from": source, "to": gate_id, "label": ""})
                visual_edges.append({"from": gate_id, "to": target, "label": "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed"})
            else:
                visual_edges.append({"from": source, "to": target,
                                     "label": rel.get("relation") or "",
                                     "gate_outcome": outcome, "relation": rel.get("relation"),
                                     "observed": rel.get("status") == "observed"})
    incoming = {edge["to"] for edge in visual_edges}
    outgoing = {edge["from"] for edge in visual_edges}
    roots = [n["id"] for n in task if n["id"] not in incoming] or [task[0]["id"]]
    leaves = [n["id"] for n in task if n["id"] not in outgoing] or [task[-1]["id"]]
    for root in roots:
        visual_edges.append({"from": "__start__", "to": root, "label": "", "observed": True})
    for leaf in leaves:
        visual_edges.append({"from": leaf, "to": "__end__", "label": "", "observed": True})
    return ({"nodes": visual_nodes, "edges": visual_edges,
             "start_node_id": "__start__", "end_node_id": "__end__"}, notes)


def svg(graph):
    from ..cross_video_render import layout as _flow_layout
    from .case_graph_render import _draw_flow

    task = graph["task_nodes"]
    skills = {s["id"]: s for s in graph["skills"]}
    tuples = {row["skill_id"]: row for row in graph.get("skill_tuples", [])}
    realizations = {r["id"]: r for r in graph["realizations"]}
    margin, header = 60, 160
    flow, notes = _visual_flow(graph)
    positions, frame = (_flow_layout(flow) if flow["nodes"] else
                        ({}, {"width": 1180, "height": 238}))
    card_width, card_gap = 300, 16
    cards_total = len(skills) * (card_width + card_gap) - card_gap if skills else 0
    width = max(frame["width"], cards_total + margin * 2, 1180)
    card_y = header + frame["height"] + 90

    def detail_height(skill):
        skill = {**skill, **tuples.get(skill["id"], {})}
        lines = [skill.get("purpose") or ""]
        for key in ("X", "O", "C_pre", "C_const", "C_post"):
            lines.append(_sentences(skill.get(key)))
        evaluator = skill.get("E") or {}
        lines.extend(_sentences(evaluator.get(k)) for k in
                     ("completion", "process_constraint", "implementation_applicability"))
        lines.extend(skill.get("R") or [])
        for rid in skill.get("R") or []:
            realization = realizations.get(rid) or {}
            lines.append(realization.get("name") or rid)
            lines.extend(" · ".join(str(n.get("name") or n.get("id")) for n in item.get("nodes") or [])
                         for item in realization.get("source_subgraphs") or [])
        has_tuple = skill["id"] in tuples
        return 120 + sum(len(_svg_text_lines(value, 12, card_width - (90 if has_tuple else 24)))
                         * (20 if has_tuple else 17) for value in lines)

    card_h = max((detail_height(skill) for skill in skills.values()), default=260) + 70
    legend_y = card_y + card_h + 40
    height = legend_y + 170

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
             f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="\'Noto Sans CJK SC\',\'Microsoft YaHei\',sans-serif" role="img">',
             f'<title>{esc(graph.get("title", "跨视频语义操作图"))}</title>',
             '<defs>'
             '<marker id="gs-edge" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker>'
             '</defs><rect width="100%" height="100%" fill="#ffffff"/>']

    def text(x, y, value, size=16, color="#1b2e43", weight="normal", anchor="start"):
        parts.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
                     f'font-weight="{weight}" text-anchor="{anchor}">{esc(value)}</text>')

    def wrap(x, y, value, *, size=12, max_width=card_width - 24, color="#334155"):
        lines = _svg_text_lines(value, size, max_width)
        for index, line in enumerate(lines):
            text(x, y + index * (size + 5), line, size, color)

    text(margin, 52, graph.get("title", "跨视频语义操作图"), 30, "#18314b", "700")
    text(margin, 86, "任务语义技能 → 多种实现方式；开始/门控/结束与七元组保留", 16, "#536579")
    text(margin, 116, f'{graph.get("purpose", "")}', 15, "#3f7fd0")
    rule_only = sum(1 for node in task if node.get("occurrence") == "rule_only")
    text(margin, 140, f'{len(task)} 个任务节点 · {len(skills)} 个语义技能 · '
                       f'{len(graph.get("relations") or [])} 条时序关系'
                       + (f' · {rule_only} 个规则补充节点' if rule_only else ''),
         14, "#64748b")

    if not task:
        text(margin + 24, header + 60, "没有可纳入的任务节点。", 18, "#475569")
        parts.append('</svg>')
        return "".join(parts)

    parts.append(f'<rect x="{margin}" y="{header - 20}" width="{width - margin * 2}" '
                 f'height="{frame["height"] + 40}" rx="22" fill="#f7f9fc" stroke="#e0e7ef"/>')
    _draw_flow(parts, flow, {}, positions, header)

    # ---- 技能卡片：七元组 + 实现集合 R ----
    start_x = max(margin, (width - cards_total) / 2)
    for index, skill in enumerate(skills.values()):
        skill = {**skill, **tuples.get(skill["id"], {})}
        x = start_x + index * (card_width + card_gap)
        parts.append(f'<rect x="{x:.1f}" y="{card_y}" width="{card_width}" height="{card_h}" rx="14" '
                     f'fill="#faf5ff" stroke="#b79ad6"/>')
        wrap(x + 12, card_y + 26, skill.get("name"), size=18, max_width=card_width - 24, color="#75509a")
        wrap(x + 12, card_y + 56, skill.get("purpose") or "", size=12, max_width=card_width - 24)
        cursor = card_y + 100
        evaluator = skill.get("E") or {}
        rows = [("X", _sentences(skill.get("X"))), ("O", _sentences(skill.get("O"))),
                ("C_pre", _sentences(skill.get("C_pre"))),
                ("C_const", _sentences(skill.get("C_const"))),
                ("E 完成", _sentences(evaluator.get("completion"))),
                ("E 过程", _sentences(evaluator.get("process_constraint"))),
                ("E 适用", _sentences(evaluator.get("implementation_applicability"))),
                ("C_post", _sentences(skill.get("C_post")))]
        for label_text, value in rows:
            text(x + 12, cursor, label_text, 11, "#7a869a", "700")
            wrap(x + 74, cursor, value, size=11, max_width=card_width - 90)
            cursor += max(1, len(_svg_text_lines(value, 11, card_width - 90))) * 16 + 4
        text(x + 12, cursor + 6, "R 实现集合", 11, "#7a869a", "700")
        cursor += 26
        for rid in skill.get("R") or []:
            realization = realizations.get(rid) or {}
            text(x + 12, cursor, f'{rid} {realization.get("name") or ""}', 11, "#6a4a86", "700")
            cursor += 16
            names = []
            for item in realization.get("source_subgraphs") or []:
                path_label = " · ".join(str(n.get("name") or n.get("id")) for n in item.get("nodes") or [])
                if path_label not in names:
                    names.append(path_label)
            wrap(x + 12, cursor, "操作：" + " / ".join(names), size=10.5, max_width=card_width - 24,
                 color="#475569")
            cursor += max(1, len(_svg_text_lines("操作：" + " / ".join(names), 10.5, card_width - 24))) * 15 + 4
            sources = [v.split(":")[0] for v in realization.get("source_realization_refs") or []]
            if (graph.get("graph_requirements") or {}).get("presentation_policy", {}).get("show_source_labels", True):
                text(x + 12, cursor, "来源：" + " / ".join(sources), 10, "#64748b")
            cursor += 16

    parts.append(f'<rect x="{margin}" y="{legend_y}" width="{width - margin * 2}" height="140" rx="18" '
                 f'fill="#f8fafc" stroke="#e6ecf4"/>')
    legend = [
        "圆：语义技能的任务节点；开始/结束固定画在链路两端",
        "菱形：进入下游技能的条件检查；条件未知时连线为虚线",
        "实线＝已观察/候选主路径；虚线＝候选/规则补充支路；规则补充节点单独标注",
    ]
    for index, line in enumerate(legend):
        text(margin + 24, legend_y + 40 + index * 28, line, 15, "#334155")
    text(margin + 24, legend_y + 126,
         f'Qwen3.8-27B / 8032 · 因果尚未证实 · 执行绑定待完成 · 来源与证据见 workbench.html',
         13, "#7a869a")
    parts.append('</svg>')
    return "".join(parts)


def render(graph, cases, out):
    out = Path(out)
    (out / "semantic_operation_graph.svg").write_text(svg(graph), encoding="utf-8")
    links = []
    source_rows = []
    for case in cases:
        target = Path(os.path.relpath(case["workbench"], out)).as_posix()
        links.append(f'<a href="{esc(target)}">{esc(case["case_id"])} · 单视频工作台</a>')
        case_graph_target = Path(os.path.relpath(Path(case["source"]).parent / "G_case.json", out)).as_posix()
        outcome = case["graph"].get("task_outcome", {})
        if not isinstance(outcome, dict):
            outcome = {"value": outcome}
        case_gaps = case["graph"].get("unresolved", [])
        skill_outcomes = "；".join(f'{node["id"]} {node["name"]}: {node["outcome"]}'
                                   for node in case["graph"]["nodes"])
        source_rows.append(f'<tr><td><strong>{esc(case["case_id"])}</strong><p><a href="{esc(target)}">单视频工作台</a><br><a href="{esc(case_graph_target)}">G_case原始知识</a></p></td><td><strong>{esc(outcome.get("value", "unknown"))}</strong><p>{esc(outcome.get("reason", "未提供结果说明"))}</p></td><td><ul>{"".join("<li>" + esc(item) + "</li>" for item in case_gaps)}</ul></td><td>{esc(skill_outcomes)}</td></tr>')
    ambiguity_panel = f'<section class="scope"><h2>任务范围与模型保留的疑点</h2><p>任务结果与各局部技能结果分别记录。局部技能完成不自动表示总任务完成；流程末端是否满足目标效果，须结合模型给出的结果说明与证据范围判断。下面保留各次分析的原始结果与待确认项。</p><table><thead><tr><th>来源与证据</th><th>任务结果及模型原始理由</th><th>单视频未决项</th><th>局部技能结果</th></tr></thead><tbody>{"".join(source_rows)}</tbody></table><h3>跨视频归纳的待确认项</h3><ul>{"".join("<li>" + esc(item) + "</li>" for item in graph["unresolved"])}</ul></section>'
    sections = []
    realizations = {r["id"]: r for r in graph["realizations"]}
    tuples = {row["skill_id"]: row for row in graph.get("skill_tuples", [])}
    for skill in graph["skills"]:
        rs = []
        for rid in skill["R"]:
            r = realizations[rid]
            sources = []
            for item in r.get("source_subgraphs", []):
                target = Path(os.path.relpath(item["workbench"], out)).as_posix()
                names = {n["id"]: n.get("name", n["id"]) for n in item["nodes"]}
                operation_labels = " · ".join(names.values())
                relations = "；".join(f'{names.get(e["from"], e["from"])} [{e["relation"]}] {names.get(e["to"], e["to"])}'
                                      for e in item["relations"])
                sources.append(f'<li><a href="{esc(target)}">{esc(item["source_realization_ref"])}</a> · {esc(item["outcome"])}<p>操作：{esc(operation_labels)}</p><p>关系：{esc(relations or "没有已记录的时序边")}</p><details><summary>来源子图</summary><pre>{esc(json.dumps({"nodes": item["nodes"], "relations": item["relations"]}, ensure_ascii=False, indent=2))}</pre></details></li>')
            usage = "（仅条件对照证据）" if r.get("usage") == "contrast_only" else ""
            rs.append(f'<details open><summary>{esc(r["name"] + usage)}</summary><p>{esc(r["effect_alignment_reason"])}</p><ul>{"".join(sources)}</ul></details>')
        summary = tuples.get(skill["id"])
        fields = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")
        contract = {key: (summary or skill)[key] for key in fields}
        if summary is not None:
            contract.update(status="归纳候选", evidence=summary["evidence"], evidence_gaps=summary["evidence_gaps"])
        contract = json.dumps(contract, ensure_ascii=False, indent=2)
        sections.append(f'<section id="skill-{esc(skill["id"])}"><h2>{esc(skill["name"])}</h2><p>{esc(skill["purpose"])}</p>{"".join(rs)}<details><summary>技能合同与评价规则</summary><pre>{esc(contract)}</pre></details></section>')
    decisions = "".join(f'<tr><td>{esc(d["condition"])}</td><td>{esc(d["decision"])}</td><td>{esc(d["reason"])}</td></tr>'
                        for d in graph["condition_learning"]["condition_decisions"])
    report = json.dumps(graph["validation"], ensure_ascii=False, indent=2)
    tuple_link = '<a href="skill_tuples.json">通用技能七元组</a>' if "skill_tuples" in graph else ""
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(graph.get("title", "跨视频语义知识"))}</title>
<style>body{{margin:0;background:#f4f7fa;color:#243347;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}}header,main{{max-width:1450px;margin:auto;padding:24px}}h1{{color:#163c53}}nav{{display:flex;gap:18px;flex-wrap:wrap}}a{{color:#275faf}}.diagram{{overflow:auto;background:white;border:1px solid #d9e2ed;border-radius:12px;margin:22px 0}}.diagram img{{display:block;max-width:none;width:min(2300px,180vw)}}section{{background:white;border:1px solid #dce3ed;border-radius:12px;padding:20px;margin:20px 0}}details{{border-left:3px solid #af96ce;padding:10px 15px;margin:12px 0}}summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;border:1px solid #dce3ed;padding:10px;vertical-align:top}}.badge{{color:#735588;background:#f1eafb;border-radius:20px;padding:5px 12px;font-size:13px}}</style>
<header><h1>{esc(graph.get("title", "跨视频语义操作图"))}</h1><p>{esc(graph.get("purpose", ""))}</p><p><span class="badge">8032 · Qwen3.8-27B</span> <span class="badge">语义候选 · 因果待验证 · 执行待绑定</span></p><nav><a href="G_semantic.json">完整知识</a><a href="semantic_operation_graph.svg">独立SVG</a><a href="condition_decisions.json">正反例条件</a><a href="semantic_rules.json">语义规则</a><a href="validation.json">校验</a>{tuple_link}{"".join(links)}</nav></header>
<main>{ambiguity_panel}<div class="diagram"><img src="semantic_operation_graph.svg" alt="语义技能与多种实现子图"></div><p>上层展示技能间关系；下层展示实现来源。展开技能可查看合同、局部成功/失败/未执行/未知结果及原视频工作台。</p>{"".join(sections)}<section><h2>条件归纳决策</h2><table><thead><tr><th>条件</th><th>处理</th><th>证据与理由</th></tr></thead><tbody>{decisions}</tbody></table></section><section><h2>结构与引用校验</h2><pre>{esc(report)}</pre></section></main></html>'''
    (out / "workbench.html").write_text(text, encoding="utf-8")
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=workbench.html"><a href="workbench.html">跨视频语义操作图</a>', encoding="utf-8")

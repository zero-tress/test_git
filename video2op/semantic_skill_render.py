"""Escaped, standalone two-layer diagrams of model-produced semantic knowledge."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from .case_graph import _svg_text_lines, _svg_text_width


def esc(value):
    return html.escape(str(value), quote=True)


def svg(graph):
    task = graph["task_nodes"]
    skills = {s["id"]: s for s in graph["skills"]}
    realizations = {r["id"]: r for r in graph["realizations"]}
    width = max(1200, max(len(task), len(skills)) * 290 + 100)
    max_r = max((len(s["R"]) for s in skills.values()), default=1)
    height = max(950, 700 + max_r * 210)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#64748b"/></marker><marker id="realizes" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#5289dd"/></marker></defs>',
             '<rect width="100%" height="100%" fill="#f8fafc"/>',
             '<style>text{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif} .small{font-size:13px;fill:#475569} .body{font-size:16px;fill:#243347}</style>']

    def text(x, y, value, size=16, color="#243347", weight="normal"):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{esc(value)}</text>')

    def wrap(x, y, value, max_width=215, size=14, maxlines=3, color="#243347", weight="normal"):
        rows = _svg_text_lines(value, size, max_width)
        visible = rows[:maxlines]
        if len(rows) > maxlines and visible:
            last = visible[-1]
            while last and _svg_text_width(last + "…", size) > max_width:
                last = last[:-1]
            visible[-1] = last + "…"
        parts.append(f'<g><title>{esc(value)}</title>')
        for index, line in enumerate(visible):
            text(x, y + index * (size + 5), line, size, color, weight)
        parts.append('</g>')

    wrap(50, 52, graph.get("title", "跨视频语义操作图"), width - 100, 29, 1, "#12324d", "bold")
    text(50, 84, "任务语义技能 → 多种实现子图；来源路径与局部结果保留", 17, "#475569")
    parts.append(f'<rect x="30" y="112" width="{width - 60}" height="260" rx="18" fill="#eff8f0" stroke="#86b58c"/>')
    text(50, 142, "第1层 · 任务语义操作图", 20, "#23643b", "bold")
    positions = {}
    for index, node in enumerate(task):
        x = 55 + index * 290
        positions[node["id"]] = x
        parts.append(f'<a href="#skill-{esc(node["skill_id"])}"><rect x="{x}" y="180" width="245" height="145" rx="12" fill="white" stroke="#4a9b65" stroke-width="2"/></a>')
        skill = skills[node["skill_id"]]
        wrap(x + 14, 205, node.get("name", skill["name"]), 215, 18, 2, "#23643b", "bold")
        wrap(x + 14, 252, "效果：" + "；".join(map(str, skill["C_post"])), 215, 13, 2)
        text(x + 14, 296, f'来源实例 {len(node["source_members"])} · 实现 {len(skill["R"])}', 13, "#475569")
        text(x + 14, 317, "语义候选 · 控制器待绑定", 12, "#735588")
    for index, edge in enumerate(graph["relations"]):
        x1 = positions[edge["from"]] + 245
        x2 = positions[edge["to"]]
        color = "#a77a29" if edge["relation"] == "branch" else "#64748b"
        if x2 > x1:
            y = 253 + (index % 3) * 11
            parts.append(f'<path d="M{x1} {y} H{x2}" fill="none" stroke="{color}" stroke-width="1.7" marker-end="url(#arrow)"/>')
            text((x1 + x2) / 2 - 24, y - 6, edge["relation"], 10, color)
        else:
            y = 340 + (index % 3) * 8
            parts.append(f'<path d="M{x1 - 122} 325 V{y} H{x2 + 122} V325" fill="none" stroke="{color}" stroke-dasharray="4 3" marker-end="url(#arrow)"/>')
    skill_columns = {sid: index for index, sid in enumerate(skills)}
    for node in task:
        x1 = positions[node["id"]] + 122
        x2 = 55 + skill_columns[node["skill_id"]] * 290 + 127
        parts.append(f'<path d="M{x1} 326 C{x1} 390 {x2} 388 {x2} 438" fill="none" stroke="#5289dd" stroke-width="1.4" stroke-dasharray="6 5" marker-end="url(#realizes)"/>')
    parts.append('<rect x="40" y="393" width="510" height="33" rx="5" fill="#f8fafc"/>')
    text(50, 414, "第2层 · 技能的实现方式与来源操作子图", 20, "#75509a", "bold")
    for col, skill in enumerate(skills.values()):
        x = 55 + col * 290
        parts.append(f'<g id="skill-{esc(skill["id"])}"><rect x="{x}" y="438" width="255" height="{105 + len(skill["R"]) * 210}" rx="12" fill="#faf5ff" stroke="#b79ad6"/>')
        wrap(x + 12, 465, skill["name"], 231, 18, 2, "#75509a", "bold")
        wrap(x + 12, 514, skill["purpose"], 231, 12, 1)
        for row, rid in enumerate(skill["R"]):
            r = realizations[rid]
            y = 535 + row * 210
            parts.append(f'<rect x="{x + 9}" y="{y}" width="237" height="192" rx="9" fill="white" stroke="#c4b5d5"/>')
            wrap(x + 19, y + 25, r["name"], 215, 16, 2)
            examples = r.get("source_subgraphs", [])
            first = examples[0] if examples else {}
            node_names = {n["id"]: n.get("name", n["id"]) for n in first.get("nodes", [])}
            operation_labels = "操作：" + " · ".join(node_names.values())
            wrap(x + 19, y + 74, operation_labels if node_names else "见来源操作图", 215, 13, 2)
            relation_labels = "；".join(f'{node_names.get(e["from"], e["from"])} {e["relation"]} {node_names.get(e["to"], e["to"])}'
                                      for e in first.get("relations", []))
            wrap(x + 19, y + 115, relation_labels or "时序关系见来源详情", 215, 10, 1)
            wrap(x + 19, y + 145, "来源：" + " / ".join(v.split(":")[0] for v in r["source_realization_refs"]), 215, 12, 1, "#475569")
            outcomes = sorted({example["outcome"] for example in examples})
            wrap(x + 19, y + 167, "局部结果：" + " / ".join(outcomes), 215, 11, 1)
        parts.append('</g>')
    text(50, height - 78, "图例：灰色实线＝语义时序关系；蓝色虚线＝技能到实现集合的映射。", 15, "#475569")
    text(50, height - 52, "下层操作列表不隐含先后；实际关系按来源类型保留。图结构结束不等于任务成功。", 15, "#475569")
    text(50, height - 25, "Qwen3.8-27B / 8032 · 因果尚未证实 · 执行绑定待完成 · 详情与证据见 workbench.html", 14, "#64748b")
    parts.append('</svg>')
    return "\n".join(parts)


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
            rs.append(f'<details open><summary>{esc(r["name"])}</summary><p>{esc(r["effect_alignment_reason"])}</p><ul>{"".join(sources)}</ul></details>')
        contract = json.dumps({key: skill[key] for key in ("X", "O", "C_pre", "C_const", "E", "C_post", "R")}, ensure_ascii=False, indent=2)
        sections.append(f'<section id="skill-{esc(skill["id"])}"><h2>{esc(skill["name"])}</h2><p>{esc(skill["purpose"])}</p>{"".join(rs)}<details><summary>技能合同与评价规则</summary><pre>{esc(contract)}</pre></details></section>')
    decisions = "".join(f'<tr><td>{esc(d["condition"])}</td><td>{esc(d["decision"])}</td><td>{esc(d["reason"])}</td></tr>'
                        for d in graph["condition_learning"]["condition_decisions"])
    report = json.dumps(graph["validation"], ensure_ascii=False, indent=2)
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(graph.get("title", "跨视频语义知识"))}</title>
<style>body{{margin:0;background:#f4f7fa;color:#243347;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}}header,main{{max-width:1450px;margin:auto;padding:24px}}h1{{color:#163c53}}nav{{display:flex;gap:18px;flex-wrap:wrap}}a{{color:#275faf}}.diagram{{overflow:auto;background:white;border:1px solid #d9e2ed;border-radius:12px;margin:22px 0}}.diagram img{{display:block;max-width:none;width:min(2300px,180vw)}}section{{background:white;border:1px solid #dce3ed;border-radius:12px;padding:20px;margin:20px 0}}details{{border-left:3px solid #af96ce;padding:10px 15px;margin:12px 0}}summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;border:1px solid #dce3ed;padding:10px;vertical-align:top}}.badge{{color:#735588;background:#f1eafb;border-radius:20px;padding:5px 12px;font-size:13px}}</style>
<header><h1>{esc(graph.get("title", "跨视频语义操作图"))}</h1><p>{esc(graph.get("purpose", ""))}</p><p><span class="badge">8032 · Qwen3.8-27B</span> <span class="badge">语义候选 · 因果待验证 · 执行待绑定</span></p><nav><a href="G_semantic.json">完整知识</a><a href="semantic_operation_graph.svg">独立SVG</a><a href="condition_decisions.json">正反例条件</a><a href="semantic_rules.json">语义规则</a><a href="validation.json">校验</a>{"".join(links)}</nav></header>
<main>{ambiguity_panel}<div class="diagram"><img src="semantic_operation_graph.svg" alt="语义技能与多种实现子图"></div><p>上层展示技能间关系；下层展示实现来源。展开技能可查看合同、局部成功/失败/未执行/未知结果及原视频工作台。</p>{"".join(sections)}<section><h2>条件归纳决策</h2><table><thead><tr><th>条件</th><th>处理</th><th>证据与理由</th></tr></thead><tbody>{decisions}</tbody></table></section><section><h2>结构与引用校验</h2><pre>{esc(report)}</pre></section></main></html>'''
    (out / "workbench.html").write_text(text, encoding="utf-8")
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=workbench.html"><a href="workbench.html">跨视频语义操作图</a>', encoding="utf-8")

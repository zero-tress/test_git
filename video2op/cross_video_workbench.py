"""Cross-video workbench using the single-case CSS/JS with exact model tuple values."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .model_merged_graph import FIELDS
from .workbench import CSS, JS

TITLES = {
    "X": "执行主体",
    "O": "操作对象",
    "C_pre": "前置条件",
    "C_const": "过程约束",
    "E": "评价指标",
    "C_post": "后置效果",
    "R": "候选实现方式",
}


def esc(value):
    return html.escape(str(value), quote=True)


def pretty(value):
    return "<pre>" + esc(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def link(label, path):
    return '<a href="' + esc(path) + '">' + esc(label) + "</a>"


def clips_html(clips):
    return "".join(
        '<div class="clip"><video controls preload="none" src="'
        + esc(c["path"])
        + '"></video><div>'
        + link("打开片段", c["path"])
        + "</div></div>"
        for c in clips
    )


def sources_html(rows):
    blocks = []
    for row in rows:
        basis = (
            '<div class="inf-note">用户指定流程中的规则步骤，未声明该视频已观测到；无伪造时间或片段。</div>'
            if row.get("basis") == "user_requirement" and row.get("observed") is False
            else ""
        )
        timing = (
            "未定位独立时间范围"
            if row.get("start_sec") is None
            else str(row["start_sec"]) + "～" + str(row["end_sec"]) + " 秒"
        )
        blocks.append(
            '<div class="source-item"><b>'
            + esc(row.get("name", row["case_id"]))
            + "</b> · "
            + link("原视频", row["source_video"])
            + " · "
            + link("模型记录", row["model_result"])
            + "<div class='purpose'>"
            + esc(timing)
            + "</div>"
            + basis
            + clips_html(row.get("clips", []))
            + pretty({"evidence_refs": row.get("evidence_refs", [])})
            + "</div>"
        )
    return (
        '<details class="evidence-fold"><summary>展开实例与证据</summary>' + "".join(blocks) + "</details>"
        if blocks
        else ""
    )


def details_html(view):
    out = []
    for node in view["nodes"]:
        gate = node["kind"] == "gate"
        attribute = "data-gate" if gate else "data-id"
        label = node.get("display_label", node["label"])
        content = '<div class="dhead"><div class="dtitle"><span class="dname">' + esc(label) + "</span></div></div>"
        if node["kind"] == "operation":
            content += '<div class="dintent">' + esc(node["label"])
            if node.get("state_context"):
                content += '<div class="purpose">' + esc(node["state_context"]) + "</div>"
            content += '</div><div class="dsec"><div class="dsec-t">七元组 ⟨X, O, C_pre, C_const, E, C_post, R⟩</div>'
            for key in FIELDS:
                content += (
                    '<div class="trow"><div class="tkey">'
                    + esc(key + " · " + TITLES[key])
                    + '</div><div class="tval">'
                    + pretty(node["seven_tuple"][key])
                    + "</div></div>"
                )
            content += "</div>"
        elif gate:
            content += (
                '<div class="dintent">'
                + esc(node["predicate"])
                + '</div><div class="dsec"><div class="dsec-t">模型条件判断</div>'
                + pretty({"state": node["truth"], "reason": node["reason"]})
                + "</div>"
            )
        else:
            content += (
                '<div class="dintent">'
                + (
                    "最后一个操作直接连接结束，无结束门控或完成验证。"
                    if node["id"] == view["end_node_id"]
                    else "归纳流程从此进入。"
                )
                + "</div>"
            )
        content += sources_html(node.get("sources", []))
        out.append(
            '<section class="detail" ' + attribute + '="' + esc(node["id"]) + '" hidden>' + content + "</section>"
        )
    for index, edge in enumerate(view["edges"]):
        out.append(
            '<section class="detail" data-edge="'
            + str(index)
            + '" hidden><div class="dhead"><span class="dname">关系与条件</span></div>'
            + pretty(edge)
            + "</section>"
        )
    return "".join(out)


def support_html(view):
    examples = []
    for item in view.get("contrastive_examples", []):
        examples.append(
            '<div class="source-item"><b>'
            + esc(item["skill_id"])
            + " · "
            + esc({"success": "成功", "failure": "失败", "unknown": "未知"}.get(item["outcome"], item["outcome"]))
            + "</b><p>"
            + esc(item.get("reason", ""))
            + "</p>"
            + clips_html(item.get("clips", []))
            + "</div>"
        )
    sections = [
        (
            "正反例学习",
            "".join(examples)
            + pretty(view.get("contrastive_skill_definitions", []))
            + pretty(view.get("contrastive_condition_comparisons", [])),
        ),
        (
            "归纳与规则说明",
            pretty(
                {
                    "merge_review": view.get("merge_review", []),
                    "simplifications": view.get("simplifications", []),
                    "functional_realizations": view.get("functional_realizations", []),
                    "entry_policy": view.get("entry_policy"),
                    "limitations": view.get("limitations", []),
                }
            ),
        ),
        (
            "实例与模型追溯",
            pretty(
                {
                    "approach_review": view.get("approach_review", []),
                    "rule_only_occurrences": view.get("rule_only_occurrences", []),
                    "source_decisions": view.get("source_decisions", []),
                    "model_provenance": view.get("model_provenance"),
                }
            ),
        ),
    ]
    return "".join(
        '<details class="fold-sec"><summary>' + esc(title) + "</summary>" + body + "</details>"
        for title, body in sections
    )


def render(view, drawing):
    template = (Path(__file__).parent / "templates/merged_workbench.html").read_text()
    payload = {
        "gates": [{"id": n["id"]} for n in view["nodes"] if n["kind"] == "gate"],
        "edges": [{**e, "idx": i} for i, e in enumerate(view["edges"])],
    }
    values = {
        "__TITLE__": esc(view["title"]),
        "__COUNTS__": str(sum(n["kind"] == "operation" for n in view["nodes"]))
        + " 个语义操作 · "
        + str(sum(n["kind"] == "gate" for n in view["nodes"]))
        + " 个条件门控",
        "__NATIVE_CSS__": CSS,
        "__NATIVE_JS__": JS,
        "__GRAPH_SVG__": drawing,
        "__NODE_DETAILS__": details_html(view),
        "__SUPPORT_HTML__": support_html(view),
        "__VIEW_JSON__": json.dumps(payload, ensure_ascii=False).replace("<", r"\u003c"),
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template

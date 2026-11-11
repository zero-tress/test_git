"""Restore the original node/gate view and the project's actual actors."""
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
backup = root / "backups/semantic_view_correction_20261022"
def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor: {name}: {old[:70]}")
    b = backup / name
    b.parent.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(p, b)
    p.write_text(text.replace(old, new), encoding="utf-8")

# Local learning schema: retain actual demonstrated actors, never cast them into
# a different project's robot-role enum.
import yaml
peer_schema = root.parent / "semantic_exec_opgraph202610141638/schemas/semantic_op_graph.schema.yaml"
schema = yaml.safe_load(peer_schema.read_text(encoding="utf-8"))
schema["$id"] = "urn:video2op:semantic-learning-graph"
schema["title"] = "视频学习任务语义图（原项目执行主体）"
schema["$defs"]["role"] = {"type": "string", "enum": ["操作者", "整体", "左臂", "右臂", "左手", "右手"]}
schema["$defs"]["executor"] = {
    "type": "object", "additionalProperties": False, "required": ["subject", "parts"],
    "properties": {"subject": {"$ref": "#/$defs/role"},
                   "parts": {"type": "array", "uniqueItems": True,
                             "items": {"enum": ["整体", "左臂", "右臂", "左手", "右手"]}}}}
target = root / "video2op/schemas/semantic_learning_graph.schema.yaml"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8")

edit("video2op/semantic.py", 'PEER = Path(', 'SCHEMA = Path(__file__).parent / "schemas/semantic_learning_graph.schema.yaml"\n\nPEER = Path(')
edit("video2op/semantic.py", '"X": {"subject": "OperationSystem"}', '"X": {"subject": "操作者", "parts": []}')
edit("video2op/semantic.py", '"X": {"subject": "ArmGripperSystem"}', '"X": deepcopy(t.get("X") or {"subject": "操作者", "parts": []})')
edit("video2op/semantic.py", '(PEER / "schemas/semantic_op_graph.schema.yaml").read_text(encoding="utf-8")', 'SCHEMA.read_text(encoding="utf-8")')
# Delete the unwanted card layout, route every learning page through the original renderer.
p = root / "video2op/semantic.py"
text = p.read_text(encoding="utf-8")
start = text.index("def svg(")
end = text.index("def validate(", start)
edit("video2op/semantic.py", text[start:end], '''def render(bundle: dict, out: Path) -> None:
    """Original operation circles/gate diamonds; tuple details open on click."""
    from . import render as original_render
    from . import workbench
    out.mkdir(parents=True, exist_ok=True)
    original_render.render_operations(bundle, out)
    data = workbench.build(out, bundle=bundle)
    page = workbench.render(data)
    for name in ("workbench.html", "report.html"):
        (out / name).write_text(page, encoding="utf-8")


''')
edit("video2op/pipeline.py", '    bundle["semantic_graph"] = semantic.build(bundle)', '    bundle["predicates"] = predicates.build(bundle)\n    bundle["gates"] = gates.build(bundle)  # view of semantic conditions, not execution scheduling\n    bundle["semantic_graph"] = semantic.build(bundle)')
edit("video2op/pipeline.py", '("program", "contract", "execution_policy", "expansion", "gates")', '("program", "contract", "execution_policy", "expansion")')

edit("video2op/workbench.py", 'def build(case_dir: Path) -> dict:\n    bundle = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))',
'''def build(case_dir: Path, *, bundle: dict | None = None) -> dict:
    if bundle is None:
        bundle = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))''')
edit("video2op/workbench.py", '    intent_items = bundle.get("intents") or []', '    intent_items = (bundle.get("intents") or {}).get("intents") or []')
edit("video2op/workbench.py", '        "case": case_dir.name,', '        "case": case_dir.name,\n        "learning_layer": bundle.get("learning_layer"),')
edit("video2op/workbench.py", 'def render(data: dict) -> str:\n', 'def render(data: dict) -> str:\n    if data.get("learning_layer") == "semantic":\n        return render_semantic(data)\n')
# No new graph or click-handler implementation: reuse original markup, CSS and JS.
p = root / "video2op/workbench.py"
text = p.read_text(encoding="utf-8")
new = '''
def render_semantic(data: dict) -> str:
    """Keep the original workbench frame and node-click tuple interaction."""
    payload = json.dumps({k: v for k, v in data.items() if k != "main_svg"},
                         ensure_ascii=False).replace("</", "<\\/")
    details = []
    for node in data["nodes"]:
        details.append(f\'''<section class="detail" data-id="{e(node["id"])}" hidden>
<div class="dhead"><div class="dtitle"><span class="dname">{e(node["name"])}</span>
<span class="cid">{e(node["id"])}</span></div></div>
<div class="dintent"><span class="tlab">操作目的</span>{e(node["intent"])}</div>
<div class="dsec"><div class="dsec-t">七元组 Si = ⟨X, O, C_pre, C_const, E, C_post, R⟩</div>
{tuple_rows(node, data["predicate_by_text"])}</div>
<div class="dsec"><div class="dsec-t">示范证据</div>{evidence_html(node, data["atomic"])}</div>
</section>\''')
    details.extend(gate_detail_html(g) for g in data.get("gates") or [])
    details.extend(edge_detail_html(x) for x in data["edges"])
    return f\'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data["case"])} · 语义操作图工作台</title><style>{CSS}</style></head>
<body><header class="top"><h1>{e(data["case"])} · 语义操作图工作台</h1>
<div class="sub">任务意图：{e(data["task_intent"])} ｜ 点击操作节点展开七元组</div>
<div class="chips"><span class="chip">{len(data["nodes"])} 个语义操作</span>
<span class="chip">校验：{e(data["validation"].get("summary"))}</span></div></header>
<div id="app"><div id="graphPane"><div id="figure">{data["main_svg"]}</div>
<div class="figcap">圆为操作、菱形为条件门控，沿用原操作图形式。
图上只显示动作；点击节点在右侧查看七元组，点击菱形查看条件与证据，Esc 取消选择。
条件未知不代表失败，图形不表示机器人已执行。</div>
{timeline_html(data)}
<details class="fold-sec"><summary>校验与待复核</summary>
<div>{e(data["validation"].get("summary"))}</div></details></div>
<div id="detailPane"><div id="detailEmpty">点击主图中的操作节点查看七元组。</div>
{"".join(details)}</div></div><script>const WB = {payload};{JS}</script></body></html>\'''


'''
edit("video2op/workbench.py", "def export(case_dir:", new + "def export(case_dir:")
# Explicit actor semantics, including a task-level check.
edit("video2op/semantic.py", 'R 是候选集合，不能选定执行策略、绑定左右臂或填写设备参数。',
'R 是候选集合，不能选定执行策略或填写设备参数。X 保留原项目的操作者及整体/左右臂/左右手，禁止虚构机器人系统名称。整体仅用于垂直上升/下降与水平方向移动，不表示姿态调整或臂手抓取。')
edit("video2op/abstraction.py", '仅前倾而高度变化不清时写整体“调整操作位置”，不得凭姿态推断下降成功。',
'整体只表示垂直上升/下降和水平方向移动（为轮臂式小车保留）；不得用整体表达姿态调整、静止、抓取或手臂抬物。仅前倾且高度变化不清时不生成整体动作，记录观察不确定性。')
edit("video2op/abstraction.py", '                if value.get("mode") != "motion":',
'''                candidate = dict(value)
                normalize_overall_action(candidate)
                if candidate.get("action") not in {"上升", "下降", "向目标移动", "移动"}:
                    issues.append(f"{here}: 整体只允许垂直上升/下降及水平移动")
                if value.get("mode") != "motion":''')
edit("video2op/stages/s02c_task.py", '        canonical(n["name"])',
'''        canonical(n["name"])
        parts = (n.get("tuple", {}).get("X") or {}).get("parts") or []
        if "整体" in parts and canonical(n["name"]) not in {"上升", "下降", "向目标移动", "移动"}:
            raise ValidationFailure("整体只表示垂直上升/下降及水平移动，不用于臂手操作")''')
edit("video2op/prompts/s02b_atomic.system.txt",
'只前倾且高度变化不清写“调整操作位置”。手臂抬物仍是手臂动作。',
'整体只表示垂直上升/下降与水平移动。仅前倾且高度变化不清时不要生成整体动作；手臂抬物仍是手臂动作。')
print("Restored original graph renderer, original actors and whole-body boundary.")

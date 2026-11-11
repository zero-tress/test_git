"""Apply reviewed learning boundary edits on the cloud workspace."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
backup = root / "backups/semantic_learning_v3_20261021"
def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"patch anchor missing: {name}: {old[:60]}")
    b = backup / name
    b.parent.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(p, b)
    p.write_text(text.replace(old, new), encoding="utf-8")

edit("video2op/abstraction.py", "手的抓握与手臂托举保持仍应保留，移动同时持物时也不能丢掉它们。", "持续抓握与托举只写 C_const，不生成保持动作或保持类型。")
edit("video2op/stages/common.py", 'text += "\\n" + PROMPT_POLICY', 'from ..semantic import POLICY\n        text += "\\n" + PROMPT_POLICY + "\\n" + POLICY')
edit("video2op/stages/s02b_atomic.py", '("transition", "motion", "maintain")', '("transition", "motion")')
edit("video2op/stages/s02b_atomic.py", '"请重新观察并分别记录臂运动与手抓握保持，无法确认则在missing_or_unclear说明"', '"请分别记录臂运动与抓握状态变化，持续抓握写约束；无法确认请说明"')
edit("video2op/stages/s02c_task.py", '        require_keys(n["tuple"],', '        from ..semantic import canonical\n        canonical(n["name"])\n        require_keys(n["tuple"],')
edit("video2op/stages/s02c_task.py", '    payload["task_nodes"] = nodes\n    return payload', '    payload["task_nodes"] = nodes\n    from ..semantic import normalize_tasks\n    return normalize_tasks(payload)')
edit("video2op/stages/s02d_link.py", 'or "maintain"', 'or "transition"')
edit("video2op/stages/s02d_link.py", '("transition", "motion", "maintain")', '("transition", "motion")')
edit("video2op/stages/s02d_link.py", 'mode = "maintain"', 'mode = "transition"')
edit("video2op/stages/s02d_link.py", '        next_id += 1', '        from ..semantic import is_hold\n        if is_hold(m):\n            continue\n        next_id += 1')
edit("video2op/stages/s02d_link.py", '        raise ValidationFailure("links / missing_actions 必须是数组")', '        raise ValidationFailure("links / missing_actions 必须是数组")\n    from ..semantic import is_hold\n    if any(is_hold(m) for m in payload["missing_actions"]):\n        raise ValidationFailure("不允许补保持动作；请将持续状态写入 C_const")')

# Keep historical deterministic builder callable for historical consumers, while the
# online and offline learning entrypoints now use only the semantic path.
edit("video2op/pipeline.py", '    workbench,\n)', '    workbench,\n    semantic,\n)')
edit("video2op/pipeline.py", '    new_actions = [dict(m) for m in (new_actions or [])]', '    new_actions = [dict(m) for m in (new_actions or []) if not semantic.is_hold(m)]')
edit("video2op/pipeline.py", '    s02b_merge.stitch_maintains(actions)\n', '')
anchor = 'def run_case(video: Path, force: bool = False, verbose: bool = True) -> dict:'
addition = '''def build_learning_graph(bundle: dict) -> None:
    """Task-level learning boundary; historical execution builder is not used."""
    from .abstraction import validate_bundle
    semantic.normalize_observations(bundle)
    validate_bundle(bundle)
    bundle["ignored_parts"] = ignored_parts.purge(bundle)
    semantic.normalize_tasks(bundle.get("task_nodes") or {})
    bundle["operations"] = operations.build(
        bundle.get("task_nodes") or {},
        (bundle.get("atomic") or {}).get("atomic_actions") or [],
        bundle.get("relations") or [], semantic_only=True)
    bundle["reasoning"] = reasoning.audit(bundle)
    bundle["semantic_graph"] = semantic.build(bundle)
    bundle["learning_layer"] = "semantic"
    bundle["operation_abstraction_version"] = "3.0"
    for key in ("program", "contract", "execution_policy", "expansion", "gates"):
        bundle.pop(key, None)


''' + anchor
edit("video2op/pipeline.py", anchor, addition)
edit("video2op/operations.py", '          relations: list[dict]) -> dict:', '          relations: list[dict], *, semantic_only: bool = False) -> dict:')
p = root / "video2op/operations.py"
text = p.read_text(encoding="utf-8")
begin = text.index('    _adopt_orphan_maintains(ops, amap)', text.index('def build('))
end = text.index('    chains = _chains(ops, edges)', begin)
old = text[begin:end]
new = '    holds = []\n    if semantic_only:\n        edges = _reduce_sequences(_edges(ops, relations))\n    else:\n' + ''.join('    ' + line if line.strip() else line for line in old.splitlines(keepends=True))
edit("video2op/operations.py", old, new)
edit("video2op/pipeline.py", 'meta["name"] + "_operation_v2"', 'meta["name"] + "_semantic_v3"')
edit("video2op/pipeline.py", '    ctx["relations"] = merged["temporal_relations"]', '    ctx["relations"] = merged["temporal_relations"]\n    semantic.normalize_observations(ctx)')
p = root / "video2op/pipeline.py"
text = p.read_text(encoding="utf-8")
begin = text.index('    # 先验补全（确定性规则）', text.index('def run_case'))
end = text.index('    stage("s03_sync"', begin)
edit("video2op/pipeline.py", text[begin:end], '    # 持续状态作为约束，禁止先验补保持动作或用保持填补时间轴。\n    semantic.normalize_observations(ctx)\n\n')
edit("video2op/pipeline.py", '    build_operation_graph(bundle)\n', '    build_learning_graph(bundle)\n')
edit("video2op/pipeline.py", 's06_validate.run(bundle)', 'semantic.validate(bundle)')
p = root / "video2op/pipeline.py"
text = p.read_text(encoding="utf-8")
begin = text.index('    render.render_timeline(bundle, out_dir)', text.index('def run_case'))
end = text.index('    timings["render_export"]', begin)
edit("video2op/pipeline.py", text[begin:end], '    semantic.export(bundle, out_dir)\n    semantic.render(bundle, out_dir)\n\n')
edit("video2op/pipeline.py", 'f"program.svg · program.json · timeline.html · graph.svg"', 'f"semantic_graph.yaml · action_catalog.json"')
edit("video2op/pipeline.py", 'operations.svg（门控状态机）', 'operations.svg（语义七元组）')
# New observations should never be instructed to produce holds by contradictory examples.
edit("video2op/prompts/s02b_atomic.system.txt", "手的接触、抓握、保持抓握、松开必须用该侧手单独记录。", "手的接触、抓握、松开用该侧手记录；持续状态写入约束。")
p = root / "video2op/prompts/s02b_atomic.system.txt"
text = p.read_text(encoding="utf-8")
begin = text.index('例如观察到抓着把手拉动')
end = text.index('这里只是分类示例', begin)
edit("video2op/prompts/s02b_atomic.system.txt", text[begin:end], '例如抓着把手拉动：记录臂向后拉动(motion)，记录手建立抓握与释放(transition)；中间抓持作为持续约束。\n')
p = root / "video2op/prompts/s02b_atomic.system.txt"
text = p.read_text(encoding="utf-8")
begin = text.index('【动作与保持】')
end = text.index('主动发力', begin)
edit("video2op/prompts/s02b_atomic.system.txt", text[begin:end], '【动作类型】\ntransition：建立/解除状态。motion：连续位置变化。只有这两种类型，不生成保持动作。\n持续抓握、托举、稳定接触写入任务约束；静止区间不填动作。\n')
edit("video2op/prompts/s02b_atomic.system.txt", 'maintain_until 是保持到指定动作结束；', '不输出 maintain_until 动作关系；')
edit("video2op/prompts/s02b_atomic.system.txt", 'transition | motion | maintain', 'transition | motion')
edit("video2op/prompts/s02b_atomic.system.txt", 'sequence | parallel | alternation | maintain_until | enables', 'sequence | parallel | alternation | enables')
edit("video2op/prompts/s02c_task.system.txt", '接近、建立抓持、提升如果各自建立后续所需的条件，可以独立成为操作；不能仅为凑节点数量合并。', '接近、接触、抓持、提升作为抓取的观察步骤保留在 atomic_refs；任务节点将捡起、抬起、举起统一为抓取。')
# Select semantic validation for every caller that now receives a semantic bundle.
edit("video2op/stages/s06_validate.py", 'def run(bundle: dict) -> dict:\n', 'def run(bundle: dict) -> dict:\n    if bundle.get("learning_layer") == "semantic":\n        from ..semantic import validate\n        return validate(bundle)\n')
print("Learning v3 patches applied; originals:", backup)

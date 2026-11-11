from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
backup=root/'backups/semantic_learning_v3_20261021'
def put(name,text):
 p=root/name; b=backup/name
 b.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and not b.exists(): shutil.copy2(p,b)
 p.write_text(text,encoding='utf-8')
def change(name,old,new):
 p=root/name; t=p.read_text()
 if old not in t: raise RuntimeError(name+': '+old[:50])
 put(name,t.replace(old,new))

change('video2op/pipeline.py','def build_operation_graph(bundle: dict) -> None:', 'def build_legacy_execution_graph(bundle: dict) -> None:')
change('video2op/pipeline.py','def run_case(video:', 'def build_operation_graph(bundle: dict) -> None:\n    """Public builder: learning output is always a semantic graph."""\n    build_learning_graph(bundle)\n\n\ndef run_case(video:')
# Historical tests explicitly exercise the old execution adapter, never learning.
for name in ('tests/test_operation_v2.py','tests/test_ignored_text.py','tests/test_contract_export.py','tests/test_semantic_contract.py'):
 change(name,'from video2op.pipeline import build_operation_graph','from video2op.pipeline import build_legacy_execution_graph as build_operation_graph')
change('video2op/vocab.py','ACTIVITY_MODES = [MODE_TRANSITION, MODE_MOTION, MODE_MAINTAIN]', 'ACTIVITY_MODES = [MODE_TRANSITION, MODE_MOTION]  # maintain is legacy-read compatibility only')
change('video2op/vocab.py','"旋转", "保持位置"', '"旋转"')
change('video2op/vocab.py','"支撑", "保持抓握"', '"支撑"')
change('video2op/prompts/s03_sync.system.txt','动作链有没有断（例如物体被举起了，但抓握的保持动作缺失）', '动作链与持续约束是否完整（例如搬运时 C_const 是否要求抓持持续成立）')
put('video2op/prompts/s02d_link.system.txt', '''你是动作链归属与必要缺口分析专家，输出严格 JSON。
对每个任务节点关联实际 atomic_ids，检查接近、接触、建立抓握与释放的实际证据。
只补有必要性依据的状态变化或运动缺口，全部标 inferred=true；不能补写成功或新目标。
补全执行器仅为整体、左臂、右臂、左手、右手。
不得补保持动作、保持类型或 maintain_until。持续抓握、托举、稳定接触是 C_const 约束。
不得凭空补动作来填满静止区间；意图不能作为补动作的充分证据。
chain_comment 每节点一句，说明真正缺口与未覆盖约束，交给任务节点约束复核。
mode 仅为 transition/motion；时间不能超出视频。
输出：
{
 "links": [{"node_id":"node_1","atomic_ids":[1,2],"chain_comment":"实际动作与约束的证据情况"}],
 "missing_actions": [],
 "orphan_atomic_ids": [],
 "notes": "不确定内容与约束缺口"
}
若确需补 missing_actions，每项含 node_id/executor/action/mode/start/end/object/reason/inferred=true/confidence。
''')
# Route both established offline learning entrypoints through semantic export.
change('tools/rebuild_semantics.py','from video2op import graph, render, media','from video2op import graph, render, media, semantic')
p=root/'tools/rebuild_semantics.py'; t=p.read_text()
start=t.index('    render.render_timeline(bundle, out)')
end=t.index('    print(json.dumps',start)
put('tools/rebuild_semantics.py',t[:start]+'    semantic.export(bundle, out)\n    semantic.render(bundle, out)\n'+t[end:])
# render_case now preserves the original by rebuilding to a new named review folder.
put('tools/render_case.py', '''"""Rebuild saved video observations to a separate semantic v3 review directory."""
from pathlib import Path
import sys
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config
from migrate_learning_v3 import main

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python tools/render_case.py <已有案例目录名>；复合旧节点请用 rebuild_semantics.py --refresh-task")
    source = config.OUTPUT_DIR / sys.argv[1] / "result.json"
    target = config.OUTPUT_DIR / (sys.argv[1] + "_semantic_v3_review_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    sys.argv = [sys.argv[0], str(source), str(target)]
    main()
''')
# Enforce the boundary even if a caller invokes the old export entrypoint.
change('video2op/contract.py','    contract = build_contract(bundle)\n    policy = build_policy(contract)', '    if bundle.get("learning_layer") == "semantic":\n        from . import semantic\n        if out_dir is not None:\n            semantic.export(bundle, Path(out_dir))\n        return {"semantic_graph": bundle["semantic_graph"]}\n    contract = build_contract(bundle)\n    policy = build_policy(contract)')
# Fix provenance on normalization: do not coerce a hold observation into motion.
change('video2op/stages/s02b_atomic.py', '        a = dict(a)\n        a["id"]', '        a = dict(a)\n        from ..semantic import is_hold\n        if is_hold(a):\n            continue\n        a["id"]')
change('video2op/stages/s02d_link.py', '    if any(is_hold(m) for m in payload["missing_actions"]):', '    if any(str(m.get("mode") or "").lower() not in ("transition", "motion")\n           for m in payload["missing_actions"]):\n        raise ValidationFailure("补全动作只允许 transition / motion")\n    if any(is_hold(m) for m in payload["missing_actions"]):')
print('Learning entrypoints and prompt policy finalized')

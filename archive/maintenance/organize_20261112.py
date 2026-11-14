from pathlib import Path
import os, json, hashlib, shutil, re
R=Path('/home/wj/codex-workspace/videostudy_operation').resolve()
assert R.is_dir() and (R/'.git').is_dir()
os.chdir(R)
A=R/'archive'; D=R/'docs'
for p in [A/'experiments',A/'fixtures',A/'tools',A/'maintenance',D/'history',D/'reports',D/'prompts']:
    p.mkdir(parents=True,exist_ok=True)
assert not (A/'maintenance/cleanup_20261112.json').exists()
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(p):
    fs=sorted(x for x in p.rglob('*') if x.is_file()) if p.is_dir() else [p]
    return [{'path':str(x.relative_to(R)),'bytes':x.stat().st_size,'sha256':digest(x)} for x in fs]
before=sum(p.stat().st_size for p in R.rglob('*') if p.is_file())
# Preserve exact bytes of provenance-bearing outputs. Existing consumers retain their paths.
moves=[]
for name in ['semantic_16_20261107','_baseline_20261111','semantic_learning_20261111_final']:
    source=R/'output'/name; target=A/'experiments'/name
    assert source.is_dir() and not source.is_symlink() and not target.exists()
    source.rename(target)
    source.symlink_to(Path('../archive/experiments')/name,target_is_directory=True)
    moves.append({'from':str(source.relative_to(R)),'to':str(target.relative_to(R)),'compatibility_symlink':True})
source=R/'output/抓取2_semantic_v3';target=A/'fixtures/抓取2_semantic_v3'
source.rename(target)
moves.append({'from':'output/抓取2_semantic_v3','to':'archive/fixtures/抓取2_semantic_v3'})
for name in ['backups','logs']:
    source=R/name;target=A/('source_backups' if name=='backups' else 'logs')
    source.rename(target)
    moves.append({'from':name,'to':str(target.relative_to(R))})
# Archive one-time source patchers and dated experiment drivers; active migration/render helpers remain.
historical=[
'add_grasp_preparation_20261022.py','add_state_frame_evidence_ui_20261022.py',
'arm_hand_scope_20261022.py','correct_semantic_view_20261022.py','finalize_delivery_20261012.py',
'finish_learning_v3.py','fix_release_gate_20261022.py','integrate_state_frames_20261022.py',
'refresh_release_gate_outputs_20261022.py','repair_semantic_outputs_20261022.py',
'replay_state_frame_pipeline_20261022.py','run_live_stateframes_20261022.py',
'simplify_operations_svg_20261012.py','single_actor_upgrade_20261022.py',
'upgrade_learning_v3.py','validate_state_frames_20261022.py']
for name in historical:
    (R/'tools'/name).rename(A/'tools'/name)
    moves.append({'from':'tools/'+name,'to':'archive/tools/'+name})
# Move prose out of project root; rewrite local Markdown links using original file locations.
doc_moves={}
for p in R.glob('*.md'):
    if p.name=='README.md': target=D/'history/README_before_20261112.md'
    elif p.name=='按两张图完成任务验收报告.md': target=D/'reports'/p.name
    else: target=D/'history'/p.name
    doc_moves[p]=target
for p in (R/'MyPersonal_Prompt').glob('*'):
    if p.is_file(): doc_moves[p]=D/'prompts'/p.name
texts={p:p.read_text() for p in doc_moves}
for source,target in doc_moves.items():
    source.rename(target)
    def link(m):
        raw=m.group(2)
        if '://' in raw or raw.startswith('#'): return m.group(0)
        base,sep,anchor=raw.partition('#')
        old=(source.parent/base).resolve()
        new=doc_moves.get(old,old)
        if new.exists():
            ref=os.path.relpath(new,target.parent).replace(os.sep,'/')+(sep+anchor if sep else '')
            return m.group(1)+ref+m.group(3)
        return m.group(0)
    text=re.sub(r'(\]\()([^)\n]+)(\))',link,texts[source])
    if target.parent==D/'history':
        text='> 历史记录：保留原版本的设计与结果；当前入口和能力边界以项目根目录 README.md 为准。部分旧输出已清理，见 docs/reports/项目整理_20261112.md。\n\n'+text
    target.write_text(text)
    moves.append({'from':str(source.relative_to(R)),'to':str(target.relative_to(R))})
(R/'MyPersonal_Prompt').rmdir()
# Snapshot retained evidence hashes so organization can be verified independently.
retained=[]
for p in [R/'data',R/'knowledge_base',R/'eval',R/'output/semantic_learning_20261111_delivery',A/'experiments',A/'fixtures']:
    retained.extend(inventory(p))
# Delete only the superseded generated outputs, each constrained to this project's output.
keep={'semantic_16_20261107','_baseline_20261111','semantic_learning_20261111_final','semantic_learning_20261111_delivery'}
deleted=[]; deleted_groups=[]
for p in sorted((R/'output').iterdir()):
    if p.name in keep: continue
    assert p.parent==R/'output' and p.resolve().is_relative_to(R/'output') and not p.is_symlink()
    rows=inventory(p);deleted.extend(rows)
    deleted_groups.append({'path':str(p.relative_to(R)),'files':len(rows),'bytes':sum(x['bytes'] for x in rows),'reason':'superseded_generated_output_or_temporary_work'})
    if p.is_dir(): shutil.rmtree(p)
    else: p.unlink()
cache_rows=[]
for p in sorted(R.rglob('*'),key=lambda x:len(x.parts),reverse=True):
    # Leave archived provenance snapshots and backups byte-for-byte intact.
    if A in p.parents: continue
    if p.is_dir() and p.name in {'__pycache__','.pytest_cache','.ruff_cache'}:
        assert p.resolve().is_relative_to(R)
        rows=inventory(p);cache_rows.extend(rows);shutil.rmtree(p)
(R/'output/current').symlink_to('semantic_learning_20261111_delivery',target_is_directory=True)
(R/'output/runs').mkdir()
# Default single-video runs get an isolated directory even without --output-root.
p=R/'run.py';s=p.read_text()
s=s.replace('import argparse\n','import argparse\nfrom datetime import datetime\n')
old='''    if args.output_root:
        from video2op import config
        config.OUTPUT_DIR = args.output_root.resolve()
        config.WORK_DIR = config.OUTPUT_DIR / "_work"
'''
new='''    from video2op import config
    config.OUTPUT_DIR = (args.output_root.resolve() if args.output_root else
                         config.ROOT / "output" / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    config.WORK_DIR = config.OUTPUT_DIR / "_work"
    print(f"输出目录：{config.OUTPUT_DIR}")
'''
assert old in s;s=s.replace(old,new);p.write_text(s)
p=R/'video2op/config.py';s=p.read_text().replace('OUTPUT_DIR = ROOT / "output"                # 产物','OUTPUT_DIR = ROOT / "output" / "runs"       # 单视频产物；CLI再按运行时间隔离');p.write_text(s)
p=R/'tools/finish_semantic_learning.py';s=p.read_text().replace('import argparse\n','import argparse\nfrom datetime import datetime\n')
s=s.replace('default=ROOT/"output/semantic_learning_20261111_delivery"','default=ROOT/"output/runs"/("semantic_learning_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f"))')
old='    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)'
new='''    out=args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("输出目录已有文件，请指定新目录；当前交付不会被覆盖")
    out.mkdir(parents=True,exist_ok=True)'''
assert old in s;s=s.replace(old,new);p.write_text(s)
p=R/'tools/run_model_validation.py';s=p.read_text().replace('import json\n','import json\nimport argparse\nfrom datetime import datetime\n')
s=s.replace('OUT = ROOT / "output/semantic_learning_20261111/model_validation"','OUT = ROOT / "output/runs" / ("model_validation_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))')
s=s.replace('def main():\n    OUT.mkdir', '''def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    OUT = args.out.resolve()
    if OUT.exists() and any(OUT.iterdir()):
        ap.error("输出目录已有文件，请指定新目录")
    OUT.mkdir''')
s=s.replace('output/抓取2_semantic_v3/result.json','archive/fixtures/抓取2_semantic_v3/result.json');p.write_text(s)
p=R/'tools/validate_semantic_delivery.py';s=p.read_text()
s=s.replace('model=ROOT/"output/semantic_learning_20261111/model_validation"','model=ROOT/"output/current/model_validation"')
s=s.replace('(ROOT/"按两张图完成任务验收报告.md").write_text(text)','(ROOT/"docs/reports/按两张图完成任务验收报告.md").write_text(text)')
p.write_text(s)
p=R/'.gitignore';s=p.read_text()
start=s.index('# Large experiment');end=s.index('# Media:')
s='''# Generated outputs; provenance snapshots retain compatibility paths.
/output/*
!/output/README.md
!/output/index.html
/archive/experiments/*
!/archive/experiments/semantic_16_20261107/
/archive/experiments/semantic_16_20261107/*
!/archive/experiments/semantic_16_20261107/source_backup/
!/archive/experiments/semantic_16_20261107/source_backup/**
/archive/fixtures/*
/archive/source_backups/
/archive/logs/
/archive/maintenance/*.json
/logs/
*.log

'''+s[end:];p.write_text(s)
manifest={'date':'2026-11-12','before_file_bytes':before,'moves':moves,'deleted_groups':deleted_groups,'deleted_files':deleted,'cache_files':cache_rows,'retained_evidence':retained}
(A/'maintenance/cleanup_20261112.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'deleted_groups':len(deleted_groups),'deleted_files':len(deleted),'deleted_bytes':sum(x['bytes'] for x in deleted),'cache_bytes':sum(x['bytes'] for x in cache_rows),'moves':len(moves),'retained_files':len(retained)},ensure_ascii=False))

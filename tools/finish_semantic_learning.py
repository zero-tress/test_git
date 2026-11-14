"""Rebuild reviewed/development and blind holdout artifacts in a new experiment."""
from pathlib import Path
import argparse
from datetime import datetime
import json
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.knowledge import extract
from video2op.holdout import explain, cluster_observed_instances
from video2op.knowledge_base import ingest
from video2op.pattern_verification import summarize

ROOT=Path(__file__).resolve().parents[1]

def save(p, value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=ROOT/"output/runs"/("semantic_learning_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f")))
    args=ap.parse_args(argv)
    out=args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("输出目录已有文件，请指定新目录；当前交付不会被覆盖")
    out.mkdir(parents=True,exist_ok=True)
    old=ROOT/"output/semantic_16_20261107"
    manifest=json.loads((old/"manifest.json").read_text())
    groups={"knowledge_development":[r for r in manifest["cases"] if r["split"]=="development"],
            "knowledge_all_16":manifest["cases"],
            "holdout_observations":[r for r in manifest["cases"] if r["split"]=="holdout"]}
    for name, rows in groups.items():
        command=[sys.executable,"-B",str(ROOT/"learn.py"),"--inputs"]+[str(old/"cases"/("video_"+r["id"]+"_semantic_v3")/"result.json") for r in rows]
        command+=["--out",str(out/name),"--task-predictions",str(ROOT/"eval/task_predictions.json")]
        if name!="holdout_observations":
            command+=["--observed-truth",str(ROOT/"eval/observed_truth.json")]
        if name=="knowledge_all_16":
            command+=["--allow-holdout-references"]
        with (out/(name+".log")).open("w") as log:
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,text=True)
        if result.returncode:
            print((out/(name+".log")).read_text()[-6000:])
            return result.returncode
        print(name+" completed",flush=True)
    development=json.loads((out/"knowledge_development/knowledge.json").read_text())
    holdout=[]
    for f in sorted((out/"holdout_observations/cases").glob("*/result.json")):
        holdout.append(extract(json.loads(f.read_text()),str(f)))
    held=explain(development,holdout)
    uids={r["sha256"]:r["id"] for r in manifest["cases"]}
    for row in held:row["case_id"]=uids[row["video_uid"]]
    save(out/"holdout_evaluation.json",held)
    save(out/"cluster_comparison.json",cluster_observed_instances(development))
    pattern_cases=[]
    for f in sorted((out/"knowledge_development/cases").glob("*/result.json")):
        b=json.loads(f.read_text())
        pattern_cases.append({"bundle":b,"video_uid":b["source_video_sha256"]})
    save(out/"temporal_pattern_verification.json",summarize(pattern_cases))
    index=ingest(json.loads((out/"knowledge_development/skill_tuples.json").read_text()),ROOT/"knowledge_base")
    save(out/"knowledge_base_index.json",index)
    refs=json.loads((ROOT/"eval/observed_truth.json").read_text())["observations"]
    predictions=json.loads((ROOT/"eval/task_predictions.json").read_text())
    conflicts=[{"case_id":r["case_id"],"fields":[k for k in ["outcome","goal_satisfied_final","method","drop"] if r[k]!=p[k]],
                "reference":{k:r[k] for k in ["outcome","goal_satisfied_final","method","drop"]},
                "model":{k:p[k] for k in ["outcome","goal_satisfied_final","method","drop"]}}
               for r,p in zip(refs,predictions) if any(r[k]!=p[k] for k in ["outcome","goal_satisfied_final","method","drop"])]
    save(out/"reference_conflicts.json",conflicts)
    cases=[]
    for f in sorted((out/"knowledge_all_16/cases").glob("*/result.json")):
        b=json.loads(f.read_text())
        cases.append({"case_id":uids[b["source_video_sha256"]],"path":str(f),
                      "task_outcome":b["task_observation"]["outcome"],
                      "drop":b["task_observation"]["drop"],"validation":b["validation"]})
    summary={"cases":len(cases),"development_videos":len(development["sources"]),
             "holdout_videos":len(held),"development_skills":len(development["skills"]),
             "development_instances":len(development["instances"]),
             "development_realizations":sum(len(s["realizations"]) for s in development["skills"]),
             "structural_passes":sum(c["validation"]["passed"] for c in cases),
             "check_counts":sorted({len(c["validation"]["checks"]) for c in cases}),
             "knowledge_validation":development["validation"],
             "reference_model_conflicts":conflicts,
             "evaluation_note":"Development references are explicitly reviewed inputs; blind holdout matching uses model observations, never reference labels. All-16 is retrospective display."}
    save(out/"verification_summary.json",summary)
    save(out/"experiment_results.json",{"summary":summary,"cases":cases,"holdout":held})
    (out/"实跑总结.md").write_text("# 视频语义学习实跑总结\n\n"+
        f"16段案例；结构检查通过 {summary['structural_passes']}/16；每段 {summary['check_counts']} 项检查。\n\n"+
        f"development：13段，{summary['development_skills']}类技能，{summary['development_instances']}个实例，{summary['development_realizations']}个实现候选。\n\n"+
        "任务级观察与局部子任务分开。04/12为任务失败，03/11为未执行搬移；09目标成功且过程掉落。原始模型输出保留。\n\n"+
        "留出02/06/14仅以模型观察参与结构解释匹配，参考标签只用于报告对照。匹配不证明前置条件、因果适用性或机器人执行成功。\n\n"+
        "证据不足的约束、模式和局部效果保持候选；模型补充验证结果见model_validation/results.json。\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in {"knowledge_validation","reference_model_conflicts"}},ensure_ascii=False))
    return 0

if __name__=="__main__":raise SystemExit(main())

"""Validate the complete delivery against frozen inputs and write an evidence-based ledger."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video2op.skill_tuple import project,validate_projection
from video2op.semantic_interface import validate_files
from video2op.knowledge_base import query

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args();out=args.out.resolve()
    model=ROOT/"output/semantic_learning_20261111/model_validation"
    if model.exists() and not (out/"model_validation").exists():
        shutil.copytree(model,out/"model_validation")
    baseline=ROOT/"output/_baseline_20261111"
    old=ROOT/"output/semantic_16_20261107"
    changes=[]
    for f in baseline.rglob("*"):
        if f.is_file() and (not (old/f.relative_to(baseline)).is_file() or sha(f)!=sha(old/f.relative_to(baseline))):
            changes.append(str(f.relative_to(baseline)))
    unexpected=[x for x in changes if x!="finalize_experiment.py"]
    if unexpected:raise ValueError("Frozen prior outputs changed: "+str(unexpected))
    manifest=json.loads((ROOT/"eval/manifest.json").read_text())
    for r in manifest["media"]:
        if sha(r["source"])!=r["sha256"]:raise ValueError("Input bytes changed: "+r["id"])
    knowledge={}
    for name in ["knowledge_development","knowledge_all_16"]:
        k=json.loads((out/name/"knowledge.json").read_text())
        errors=validate_projection(k,project(k))
        if errors or not k["validation"]["passed"]:raise ValueError(errors or k["validation"])
        knowledge[name]=k
    dev=knowledge["knowledge_development"]
    held=json.loads((out/"holdout_evaluation.json").read_text())
    if {r["video_uid"] for r in held}&{s["video_uid"] for s in dev["sources"]}:raise ValueError("holdout leakage")
    interfaces=[]
    effect_counts=Counter();warnings=Counter()
    for p in sorted((out/"knowledge_all_16/cases").glob("*/result.json")):
        b=json.loads(p.read_text())
        if not b["validation"]["passed"] or len(b["validation"]["checks"])!=12:raise ValueError("case regression")
        warnings.update(c["id"] for c in b["validation"]["checks"] if c["status"]=="warn")
        result=validate_files(p.parent)
        if not result["passed"]:raise ValueError(result)
        interfaces.append({"case":p.parent.name,**result})
        ev=json.loads((p.parent/"effect_evidence_audit.json").read_text())
        effect_counts.update(r["verification_status"] for r in ev["records"])
    for s in dev["skills"]:
        if query(ROOT/"knowledge_base",s["skill_id"])["skill"]["skill_id"]!=s["skill_id"]:raise ValueError("KB query failed")
    test=subprocess.run([sys.executable,"-B","-m","pytest","-q","-p","no:cacheprovider"],cwd=ROOT,text=True,capture_output=True)
    if test.returncode:raise RuntimeError(test.stdout+test.stderr)
    (out/"pytest_final.log").write_text(test.stdout+test.stderr)
    spec=[
    ("①",["视频输入","第一视角及视角分类","可选文字描述"],[1,1,1]),
    ("②a",["任务多假设意图","局部子任务与技能候选","置信度与证据","复合任务抽象"],[0,1,1,0]),
    ("②b",["状态抽取","对象身份与绑定","对象关系和状态变化","时序关系表示","单视频特例操作图"],[1,1,1,1,1]),
    ("③",["意图解释操作图","操作图实现意图","前后状态一致性","逐候选置信度更新"],[1,1,0,1]),
    ("④",["前置条件观察对照","后置条件观察对照","成功失败及未执行分开统计","有效条件与反例证据"],[0,0,1,0]),
    ("⑤",["Sequence/Parallel/Alternation语义时序","独立语义约束产物","评价规则与检测器接口"],[0,1,1]),
    ("⑥",["同义特例聚类","同一目的的多实现整合","通用语义操作图","冻结知识后的留出解释"],[0,1,1,1]),
    ("⑦",["类型与引用一致性","前后置条件衔接校验","时序一致性校验","因果合理性","来源与置信记录","知识库固化与版本检索"],[1,1,1,0,1,1]),
    ("A",["Skill Tuple七字段","实现方式集合R","公共及分支语义约束","评价规则Evaluator","时序知识与来源"],[1,1,0,1,0])]
    evidence_by_box = {
        "①": ["run.py", "video2op/stages/s02a_intent.py", str(out.relative_to(ROOT)/"model_validation/results.json")],
        "②a": ["video2op/stages/s03_sync.py", "video2op/learning_alignment.py", str(out.relative_to(ROOT)/"model_validation/results.json")],
        "②b": ["video2op/semantic.py", str(out.relative_to(ROOT)/"knowledge_all_16/cases"), str(out.relative_to(ROOT)/"knowledge_development/knowledge.json")],
        "③": ["video2op/stages/s03_sync.py", "video2op/semantic_checks.py", str(out.relative_to(ROOT)/"delivery_validation.json")],
        "④": ["video2op/task_observations.py", "video2op/condition_induction.py", str(out.relative_to(ROOT)/"knowledge_development/effective_conditions.json")],
        "⑤": ["video2op/temporal_learning.py", str(out.relative_to(ROOT)/"knowledge_development/constraints.json"), str(out.relative_to(ROOT)/"knowledge_development/evaluators.json")],
        "⑥": ["video2op/holdout.py", str(out.relative_to(ROOT)/"holdout_evaluation.json"), str(out.relative_to(ROOT)/"cluster_comparison.json")],
        "⑦": ["video2op/semantic_checks.py", "video2op/knowledge_base.py", str(out.relative_to(ROOT)/"delivery_validation.json"), "knowledge_base/index.json"],
        "A": ["video2op/skill_tuple.py", str(out.relative_to(ROOT)/"knowledge_development/skill_tuples.json"), str(out.relative_to(ROOT)/"temporal_pattern_verification.json")]}
    checklist=[]
    for box,labels,flags in spec:
        for label,complete in zip(labels,flags):
            checklist.append({"id":"P%02d"%(len(checklist)+1),"box":box,"requirement":label,
                              "status":"complete" if complete else "partial",
                              "mechanism_evidence":evidence_by_box[box],
                              "remaining":"" if complete else "见验收报告：实视频候选覆盖、逐命题审阅、受控反例或跨实现公共条件证据不足。"})
    assert len(checklist)==38
    ledger={"schema_version":"diagram_checklist.v1","scope":"图1①—⑦+A；图2仅语义层及待绑定接口",
            "mapping_note":"本轮按图重新拆分为38项；原16完成/18部分/4未做没有逐条账本，不沿用。",
            "status_definition":"complete表示约定机制和相应产物验证完成，不表示所有学习结论均为真或因果已证实。",
            "items":checklist,"counts":dict(Counter(r["status"] for r in checklist))}
    save(ROOT/"eval/checklist_38.json",ledger);save(out/"checklist_38.json",ledger)
    report={"pytest":test.stdout.strip().splitlines()[-1],"interface_cases":interfaces,
            "prior_output_changes":changes,"unexpected_prior_output_changes":unexpected,
            "source_media_checked":len(manifest["media"]),"effect_verification_counts":dict(effect_counts),
            "case_warning_counts":dict(warnings),"checklist_counts":ledger["counts"]}
    save(ROOT/"eval/delivery_validation.json",report);save(out/"delivery_validation.json",report)
    local_counts={n:{"sources":len(k["sources"]),"skills":len(k["skills"]),"instances":len(k["instances"]),
                    "R":sum(len(s["realizations"]) for s in k["skills"])} for n,k in knowledge.items()}
    lines=["# 按两张图完成任务验收报告","",
           "日期：2026-11-11。服务器项目："+str(ROOT)+"。","",
           "## 已交付","",
           "- "+report["pytest"]+"；原367项基线全部保留，新增27项参数化检查。",
           "- 16段案例均通过12项结构检查；同时保留每项warn，不把结构通过写成语义成功。",
           "- 两套知识、Skill Tuple、约束、Evaluator、有效条件统计、谓词映射、任务技能层级图和待绑定接口已生成。",
           "- 任务目标、模型观察、已有参考标注分别保存；原始模型误判保留，原标注不改。",
           "- 04/12任务失败、03/11未执行搬移、09目标成功且过程掉落。任务标签不覆盖局部抓握等子任务。",
           "- 版本知识库可按skill_id/version检索；参数和检测器继续unbound。",
           "- 历史finalize脚本的effective_model键错误已修正；新的收尾入口tools/finish_semantic_learning.py在新目录生成全部报告。","",
           "## 实测规模","",
           json.dumps(local_counts,ensure_ascii=False,indent=2),"",
           "相比旧development的5类/28实例/20R，增加了显式给定任务层的搬移并结束接触契约。6类不代表自主发现了6种新技能。","",
           "## 留出验收",""]
    for r in held:
        lines.append("- "+r["case_id"]+"："+r["decision"]+"；只核验目标契约、对象类别、操作与关系对应；适用条件和机器人复用仍未验证。")
    lines+=["","development只使用13段；holdout_observations不加载参考标签。评估使用初始task_audit，不使用由标注分歧触发的密集复核结果。all-16是含参考标注的事后展示。","",
            "## 尚需证据","",
            "- 本轮3段真实模型样例、9次调用已完成；未获得多意图候选或排序反转，不声明已完成该项实证。",
            "- 实视频模式仍为Sequence/Parallel；Alternation/Branch/Synchronization的结构能力和测试存在，真实支持与人工确认不足，verified模式为0。",
            "- 原子效果的模型observed与人工/参考verified分开；现有标注未逐项证实208条局部效果，不批量升级。",
            "- 分支条件已保留在R内，公共C_pre/C_const保留缺口；部分原始条件尚不能对应最终案例谓词，见case_predicate_bindings.json的needs_review。",
            "- 观察状态聚类不使用seed目的/效果特征，但目前只是字面状态对照，不能当作已验证的语义同义聚类。",
            "- 失败和未执行进入实证统计；现有观察数据不能识别普遍因果条件，需要受控反例、实现方式对照和逐命题审阅。",
            "- 三态验证状态与T/F/U真假、四态outcome分别保存；未报告掉落的参考记录保持U。",
            "- B用途、C机器人反馈闭环、行为子树与执行侧实现属于本轮范围外。","",
            "## 逐项账本","",
            "38项为本轮重新映射："+json.dumps(ledger["counts"],ensure_ascii=False)+"。不继承原清单未提供证据的16/18/4，不宣称38/38完成。","",
            "|编号|图中位置|要求|状态|","|---|---|---|---|"]
    lines += ["|"+r["id"]+"|"+r["box"]+"|"+r["requirement"]+"|"+r["status"]+"|" for r in checklist]
    lines += ["","## 产物入口","",str(out),"",
              "- knowledge_development/review.html：13段已审阅任务层归纳和七元组。",
              "- knowledge_all_16/review.html：全部16段事后展示。",
              "- holdout_evaluation.json / experiment_results.json / verification_summary.json / 实跑总结.md。",
              "- delivery_validation.json / checklist_38.json / reference_conflicts.json。",
              "- model_validation/results.json：真实调用与候选、时序结果。",
              "- eval/manifest.json / eval/baseline_report.json；output/_baseline_20261111保留原实验副本。",""]
    text="\n".join(lines)
    (ROOT/"按两张图完成任务验收报告.md").write_text(text)
    (out/"按两张图完成任务验收报告.md").write_text(text)
    print(json.dumps({"tests":report["pytest"],"interfaces":len(interfaces),"ledger":ledger["counts"],
                      "holdout":[(r["case_id"],r["decision"]) for r in held]},ensure_ascii=False))
if __name__=="__main__":main()

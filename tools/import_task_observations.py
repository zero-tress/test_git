"""Import existing task references separately from blind model audit observations."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video2op.task_observations import reference_from_annotation,prediction_from_audit
ROOT=Path(__file__).resolve().parents[1]
def main():
    old=ROOT/"output/semantic_16_20261107"
    ann=ROOT/"data/16段视频_命名标注/标注数据.json"
    manifest=json.loads((old/"manifest.json").read_text())
    splits={r["id"]:r["split"] for r in manifest["cases"]}
    refs=[];predictions=[]
    for row in json.loads(ann.read_text())["视频标注"]:
        ref=reference_from_annotation(row,str(ann))
        ref["split"]=splits[row["编号"]];refs.append(ref)
        source=old/"task_audit"/row["编号"]/"result.json"
        dense=old/"task_audit_review"/row["编号"]/"result.json"
        pred=prediction_from_audit(json.loads(source.read_text()),row["SHA256"],ref["task_contract"],str(source))
        pred.update(case_id=row["编号"],split=splits[row["编号"]],
                    dense_review_available=dense.exists(),dense_review_used=False)
        predictions.append(pred)
    (ROOT/"eval").mkdir(exist_ok=True)
    values={"observed_truth.json":{"schema_version":"observed_task_truth.v1","observations":refs,
                                  "policy":"Existing references; reviewer identity was not recorded; not new manual annotation. Unreported process anomalies remain unknown."},
            "task_predictions.json":predictions}
    for name,value in values.items():
        (ROOT/"eval"/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    print("Imported 16 task references and 16 independently stored model observations.")
if __name__=="__main__":main()

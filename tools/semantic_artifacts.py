"""Standalone exports/checks for saved semantic knowledge and case observations."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video2op.skill_tuple import export
from video2op.holdout import explain,cluster_observed_instances
from video2op.knowledge import extract
from video2op.pattern_verification import summarize

def main(mode=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--cases",nargs="*",type=Path,default=[])
    ap.add_argument("--reviews",type=Path)
    args=ap.parse_args()
    if mode=="project":
        export(json.loads(args.input.read_text()),args.out);return
    if mode=="bindings":
        catalog=json.loads(args.input.read_text())
        value={"bindings":catalog,"policy":"接口线索，待执行侧绑定；不证明行为子树已接通"}
    elif mode=="cluster":
        value=cluster_observed_instances(json.loads(args.input.read_text()))
    elif mode=="holdout":
        cases=[]
        for path in args.cases:
            if path.is_dir():path=path/"result.json"
            cases.append(extract(json.loads(path.read_text()),str(path)))
        value=explain(json.loads(args.input.read_text()),cases)
    elif mode=="patterns":
        cases=[]
        for path in sorted(args.input.glob("*/result.json")):
            b=json.loads(path.read_text());cases.append({"bundle":b,"video_uid":b["source_video_sha256"]})
        value=summarize(cases,json.loads(args.reviews.read_text()) if args.reviews else None)
    else:raise ValueError(mode)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__":main()

"""Resume only cross-video learning after fixing decoded-frame timestamps."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/搬移盒子"
RECORD = OUT / "_cross_resume_20261119"
def save(path, data):
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    tmp.replace(path)
def main():
    m=json.loads((OUT/"run_manifest.json").read_text())
    if len(m["cases"])!=16 or any(c["status"]!="complete" for c in m["cases"]):
        raise RuntimeError("All sixteen original cases must be complete")
    for row in m["cases"]:
        if hashlib.sha256(Path(row["result"]).read_bytes()).hexdigest()!=row["result_sha256"]:
            raise RuntimeError("Single-video result changed")
    if "--check" in sys.argv:
        print("All sixteen case result hashes match; cross-video-only resume ready.")
        return 0
    RECORD.mkdir(exist_ok=False)
    save(RECORD/"previous_manifest.json",m)
    m.update(status="running",cross_video_status="running",
             cross_video_resumed=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
             cross_video_resume_log=str(RECORD/"cross_video.log"))
    m.pop("error",None)
    m.pop("finished",None)
    save(OUT/"run_manifest.json",m)
    index=OUT/"index.html"
    previous=index.read_text()
    (RECORD/"previous_index.html").write_text(previous)
    index.write_text(previous.replace("批次状态：failed","批次状态：running")+
                    '<p>跨视频学习已续跑：<a href="knowledge/progress.json">进度记录</a></p>')
    args=[sys.executable,"-u","-B","tools/learn_semantic_graph.py","--inputs",
          *[c["result"] for c in m["cases"]],"--out",str(OUT/"knowledge"),
          "--allow-8032","--resume","--refresh-prompts"]
    with (RECORD/"cross_video.log").open("xb") as log:
        code=subprocess.run(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT).returncode
    m.update(status="complete" if code==0 else "failed",
             cross_video_status="complete" if code==0 else "failed",
             finished=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
    if code:
        m["error"]="Cross-video resume exit code "+str(code)
    else:
        m["knowledge"]="knowledge/workbench.html"
    save(OUT/"run_manifest.json",m)
    text=index.read_text().replace("批次状态：running","批次状态："+m["status"])
    if code==0:
        text+='<p><a href="knowledge/workbench.html">跨视频学习工作台</a></p>'
    index.write_text(text)
    return code
if __name__=="__main__":
    raise SystemExit(main())

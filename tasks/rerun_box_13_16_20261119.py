"""Restart 13--16 independently, preserving prior artifacts and model-only judgments."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import html
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "output/搬移盒子"
RECORD = OUT / "_rerun_20261119"
def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def preflight():
    from video2op.learning_contracts import source_fingerprint
    m = json.loads((OUT/"run_manifest.json").read_text())
    if m["status"] != "failed":
        raise RuntimeError("Expected stopped failed batch; refusing duplicate launch")
    if m["code_sha256"] != source_fingerprint():
        raise RuntimeError("Original source changed; refusing silent version mixing")
    if len(m["cases"]) != 16:
        raise RuntimeError("Expected original sixteen inputs")
    for row in m["cases"][:12]:
        if row["status"] != "complete" or digest(Path(row["result"])) != row["result_sha256"]:
            raise RuntimeError("Completed source result changed")
    for row in m["cases"]:
        if digest(Path(row["video"])) != row["video_sha256"]:
            raise RuntimeError("Video source changed")
    if RECORD.exists():
        raise RuntimeError("Rerun record exists; refusing duplicate launch")
    return m
def case_dir(row):
    return OUT/"cases"/(Path(row["video"]).stem+"_semantic_v3")
def pages(m):
    items=[]
    for row in m["cases"]:
        directory=case_dir(row)
        directory.mkdir(parents=True,exist_ok=True)
        name=html.escape(Path(row["video"]).stem)
        state=html.escape(row["status"])
        local_links = "".join('<li><a href="'+f+'">'+label+'</a></li>'
            for f,label in [("workbench.html","单视频工作台"),("operations.svg","操作图"),("G_case.svg","特例图")]
            if (directory/f).exists())
        if row in m["cases"][12:]:
            (directory/"index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>'+name+
                '</title><h1>'+name+'</h1><p>运行状态：'+state+'</p><ul>'+local_links+'</ul><p><a href="stages/">阶段文件</a></p>',encoding="utf-8")
        target="workbench.html" if (directory/"workbench.html").exists() else "index.html"
        relative=(directory/target).relative_to(OUT).as_posix()
        items.append('<li><a href="'+html.escape(relative,quote=True)+'">'+name+'</a>：'+state+'</li>')
    cross='<p><a href="knowledge/workbench.html">跨视频学习工作台</a></p>' if (OUT/"knowledge/workbench.html").exists() else ''
    (OUT/"index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>搬移盒子</title>'+
        '<h1>搬移盒子 · 视频学习</h1><p>批次状态：'+html.escape(m["status"])+'</p><ul>'+''.join(items)+'</ul>'+cross+
        '<p><a href="_rerun_20261119/">本次重跑日志</a> · <a href="run_manifest.json">运行记录</a></p>',encoding="utf-8")
def checkpoint(m):
    save(OUT/"run_manifest.json",m)
    pages(m)
def one(video):
    from video2op import config
    from video2op.pipeline import run_case
    config.OUTPUT_DIR=OUT/"cases"
    config.WORK_DIR=OUT/"_work"
    description=(ROOT/"tasks/搬移盒子_任务背景_20261118.txt").read_text()
    b=run_case(Path(video),force=True,description=description)
    if b.get("errors") or not b.get("case_graph") or not b.get("validation",{}).get("passed"):
        raise RuntimeError("Complete validated single-video learning not finished")
def main():
    m=preflight()
    if "--check" in sys.argv:
        print("Preflight passed: original source, sixteen video hashes and first twelve completed results match.")
        return 0
    RECORD.mkdir(parents=True)
    save(RECORD/"original_manifest.json",m)
    if (OUT/"index.html").exists():
        shutil.copy2(OUT/"index.html",RECORD/"previous_index.html")
    for row in m["cases"][12:]:
        directory=case_dir(row)
        if directory.exists():
            archive=RECORD/"previous_cases"/directory.name
            archive.parent.mkdir(parents=True,exist_ok=True)
            directory.resolve().relative_to(OUT.resolve())
            archive.resolve().relative_to(OUT.resolve())
            shutil.move(str(directory),str(archive))
        row.update(status="pending")
        for key in ["result","result_sha256","error"]:
            row.pop(key,None)
    m.update(status="running",rerun_started=now(),rerun_ids=[13,14,15,16],
             failure_policy="continue_remaining_cases; cross_video_requires_all_complete")
    m.pop("error",None)
    checkpoint(m)
    for row in m["cases"][12:]:
        row.update(status="running",started=now())
        checkpoint(m)
        log=RECORD/(Path(row["video"]).stem+".log")
        row["rerun_log"]=str(log)
        print("START",Path(row["video"]).name,flush=True)
        try:
            with log.open("xb") as stream:
                proc=subprocess.run([sys.executable,"-u","-B",str(Path(__file__).resolve()),"--one",row["video"]],
                    cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
            if proc.returncode:
                raise RuntimeError("Single-video process exit code "+str(proc.returncode))
            result=case_dir(row)/"result.json"
            if digest(Path(row["video"])) != row["video_sha256"]:
                raise RuntimeError("Video changed during analysis")
            if not all((case_dir(row)/name).is_file() for name in ["result.json","workbench.html","operations.svg","G_case.json","G_case.svg"]):
                raise RuntimeError("Required case artifacts missing")
            row.update(status="complete",result=str(result),result_sha256=digest(result))
        except Exception as exc:
            row.update(status="failed",error=str(exc))
            print("FAILED; continuing next video:",Path(row["video"]).name,str(exc),flush=True)
        row["finished"]=now()
        checkpoint(m)
    if any(row["status"]!="complete" for row in m["cases"]):
        m.update(status="partial_failed",error="Some cases failed; all videos 13--16 were attempted; cross-video learning not started.")
        checkpoint(m)
        return 1
    m["cross_video_status"]="running"
    checkpoint(m)
    args=[sys.executable,"-u","-B","tools/learn_semantic_graph.py","--inputs",
          *[row["result"] for row in m["cases"]],"--out",str(OUT/"knowledge"),"--allow-8032"]
    if (OUT/"knowledge/run_manifest.json").exists():
        args.append("--resume")
    with (RECORD/"cross_video.log").open("xb") as stream:
        code=subprocess.run(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT).returncode
    m.update(status="complete" if code==0 else "failed",cross_video_status="complete" if code==0 else "failed",
             finished=now())
    if code:
        m["error"]="Cross-video process exit code "+str(code)
    else:
        m["knowledge"]="knowledge/workbench.html"
    checkpoint(m)
    return code
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--one":
        one(sys.argv[2])
    else:
        raise SystemExit(main())

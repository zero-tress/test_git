"""One-shot isolated background launcher for the user-authorized sixteen-video batch."""
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path("/home/wj/codex-workspace/videostudy_operation")
OUT = ROOT / "output/搬移盒子"
STATE = ROOT / ".runtime/搬移盒子_20261118"
CONDA = Path("/home/wj/miniconda3")
def save(value):
    (STATE / "process.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
def limits():
    size = 4 * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (size, size))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128,128))
    resource.setrlimit(resource.RLIMIT_CORE, (0,0))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    os.nice(10)
def main():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = (STATE / "launch.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    videos = sorted((ROOT / "data/16段视频_命名标注/视频").glob("*.mp4"))
    if len(videos) != 16:
        raise RuntimeError("Expected exactly sixteen videos")
    OUT.mkdir(parents=True, exist_ok=True)
    if any(OUT.iterdir()):
        raise RuntimeError("Output must be empty; refusing to reuse results")
    cmd = ["/usr/bin/bwrap", "--unshare-all", "--share-net", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
    for folder in ["/usr", "/bin", "/sbin", "/lib", "/lib64"]:
        if Path(folder).exists():
            cmd += ["--ro-bind", folder, folder]
    cmd += ["--dir", "/etc"]
    for file in ["/etc/ld.so.cache", "/etc/localtime", "/etc/os-release"]:
        if Path(file).exists():
            cmd += ["--ro-bind", file, file]
    for file in ["/etc/alternatives/libblas.so.3-x86_64-linux-gnu", "/etc/alternatives/liblapack.so.3-x86_64-linux-gnu"]:
        if Path(file).exists():
            cmd += ["--ro-bind", str(Path(file).resolve()), file]
    cmd += ["--ro-bind", str(CONDA), str(CONDA), "--ro-bind", str(ROOT), str(ROOT),
            "--bind", str(OUT), str(OUT), "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for key, value in {"HOME":str(OUT), "PATH":"/usr/bin:/bin", "LANG":"C.UTF-8",
                       "PYTHONDONTWRITEBYTECODE":"1", "OMP_NUM_THREADS":"1",
                       "OPENBLAS_NUM_THREADS":"1", "MKL_NUM_THREADS":"1",
                       "V2O_BASE_URL":"http://127.0.0.1:8032", "V2O_MODEL":"qwen3.8-27b"}.items():
        cmd += ["--setenv", key, value]
    cmd += ["--chdir", str(ROOT), "--", str(CONDA / "bin/conda"), "run", "--no-capture-output",
            "-n", "study", "python", "-u", "-B", "tools/learn_video_knowledge.py",
            "--videos", *map(str, videos), "--out", str(OUT),
            "--description", str(ROOT / "tasks/搬移盒子_任务背景_20261118.txt"), "--allow-8032"]
    info = {"supervisor_pid":os.getpid(), "started":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "status":"starting", "video_count":len(videos), "output":str(OUT),
            "log":str(STATE / "run.log"), "cpu_cores":1, "memory_gib":4, "gpu":False,
            "duration_limit":None, "model_endpoint":"http://127.0.0.1:8032"}
    save(info)
    with (STATE / "run.log").open("xb") as log:
        process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   preexec_fn=limits)
        info.update(status="running", sandbox_pid=process.pid)
        save(info)
        code = process.wait()
    info.update(status="complete" if code == 0 else "failed", exit_code=code,
                finished=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
    save(info)
if __name__ == "__main__":
    main()

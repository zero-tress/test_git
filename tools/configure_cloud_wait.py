"""Extend only optional wall-clock waiting for authorized model evaluation."""

import shutil
import time
from pathlib import Path

p = Path("/home/wj/.local/share/codex-cloud-mcp/server.py")
s = p.read_text()
changes = [
    ("min(120, int(args.get('timeout_seconds', 30)))", "min(1200, int(args.get('timeout_seconds', 30)))"),
    ("timeout_max_seconds=120,", "timeout_max_seconds=1200, timeout_default_seconds=30,"),
    (
        "max 120 wall seconds.",
        "default 30 wall seconds, optional timeout_seconds up to 1200 for authorized long model waits.",
    ),
    ("minimum=1, maximum=120)", "minimum=1, maximum=1200, default=30)"),
    ("version='1.1.0'", "version='1.1.1'"),
]
for old, new in changes:
    if old not in s:
        raise ValueError("Missing anchor: " + old)
    s = s.replace(old, new)
compile(s, str(p), "exec")
backup = p.with_name("server.py.before-long-wait-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(p, backup)
staged = p.with_name("server.py.wait-staged")
staged.write_text(s, encoding="utf-8")
staged.chmod(p.stat().st_mode)
staged.replace(p)
print("Optional wall timeout maximum: 1200 seconds; default 30 seconds unchanged.")
print("CPU time remains 60 seconds, memory 4 GiB, 1 CPU, GPU disabled.")
print("Backup:", backup)

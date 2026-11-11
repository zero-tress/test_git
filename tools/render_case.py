"""Rebuild saved video observations to a separate semantic v3 review directory."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrate_learning_v3 import main

from video2op import config

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python tools/render_case.py <已有案例目录名>；复合旧节点请用 rebuild_semantics.py --refresh-task")
    source = config.OUTPUT_DIR / sys.argv[1] / "result.json"
    target = config.OUTPUT_DIR / (sys.argv[1] + "_semantic_v3_review_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    sys.argv = [sys.argv[0], str(source), str(target)]
    main()

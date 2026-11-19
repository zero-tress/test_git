"""Run on the server in conda study with access to its existing model service."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video2op import config
from video2op.single_video.pipeline import run_case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--reuse-cache", action="store_true",
                        help="允许缓存；这样的运行不作冷启动速度比较")
    args = parser.parse_args()
    video = args.video.resolve()
    previous = config.OUTPUT_DIR / video.stem / "result.json"
    baseline = json.loads(previous.read_text(encoding="utf-8")).get("pipeline", {}) if previous.exists() else {}
    started = time.perf_counter()
    result = run_case(video, force=not args.reuse_cache)
    measured = time.perf_counter() - started
    current = result["pipeline"]
    old_stats = baseline.get("llm_stats", {})
    new_stats = current.get("llm_stats", {})
    comparable = (bool(old_stats.get("calls")) and not old_stats.get("cache_hits")
                  and not new_stats.get("cache_hits") and not old_stats.get("failures")
                  and not new_stats.get("failures") and old_stats.get("seconds", 0) > 0
                  and new_stats.get("seconds", 0) > 0
                  and baseline.get("model") == current.get("model"))
    report = {
        "video": str(video), "baseline_source": str(previous),
        "baseline": baseline, "current": current,
        "external_wall_seconds": round(measured, 3),
        "cold_model_comparison_available": comparable,
        "model_time_ratio_old_over_new": (
            round(old_stats["seconds"] / new_stats["seconds"], 3) if comparable else None),
        "validation": result["validation"]["summary"],
        "quality_review_required": True,
        "notes": [
            "历史 wall_seconds 不包括建图与渲染，不直接作为总耗时加速比。",
            "模型耗时比仅供相同模型、无缓存、无失败的记录比较；服务器负载也会影响。",
            "需人工确认目标、动作边界、上肢保持和整体升降正确，不能只比较速度。",
        ],
    }
    out = config.OUTPUT_DIR / (video.stem + "_operation_v2")
    (out / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("baseline", "current")},
                     ensure_ascii=False, indent=2))
    return 0 if result["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

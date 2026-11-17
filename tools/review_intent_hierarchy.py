"""Re-observe task intent and audit a saved operation graph in a NEW directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config, semantic
from video2op.intent_hierarchy import validate_intents
from video2op.llm import VLMClient
from video2op.pipeline import build_learning_graph
from video2op.stages import s02a_intent, s03_sync


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Saved result.json")
    parser.add_argument("output", type=Path, help="New output directory")
    parser.add_argument("--description", default="", help="Task context, never observed success")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new directory; preserve existing evidence")
    source = args.source.resolve()
    source_bytes = source.read_bytes()
    bundle = json.loads(source_bytes)
    video = Path(bundle["meta"]["path"])
    if not video.is_file():
        parser.error("original video is unavailable")
    args.output.mkdir(parents=True)
    out = args.output.resolve()

    def save(name, data):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    config.WORK_DIR = out / "work"
    config.VIDEO_TIMEOUT = args.timeout
    config.TEXT_TIMEOUT = args.timeout
    client = VLMClient(out / "cache")
    ctx = deepcopy(bundle)
    ctx["video"] = video
    ctx["video_id"] = hashlib.sha256(video.read_bytes()).hexdigest()
    ctx["task_nodes"] = deepcopy(bundle.get("task_nodes_source") or bundle["task_nodes"])
    if args.description:
        ctx["text_description"] = {"text": args.description, "provenance": "text_description"}
    try:
        save("progress.json", {"stage": "s02a_intent", "status": "running"})
        ctx["intents"] = s02a_intent.run(client, ctx)
        validate_intents(ctx["intents"], require_hierarchy=True)
        save("s02a_intent.json", ctx["intents"])
        save("progress.json", {"stage": "s03_sync", "status": "running"})
        ctx["sync"] = s03_sync.run(client, ctx)
        save("s03_sync.json", ctx["sync"])
        bundle["intents"] = ctx["intents"]
        bundle["sync"] = ctx["sync"]
        # Preserve old condition/rule scope, replace only the source synchronization audit.
        if "source_analysis" in bundle:
            bundle["source_analysis"]["sync"] = deepcopy(ctx["sync"])
        bundle["semantic_revision"] = {
            "schema_version": "intent_hierarchy_review.v1", "source": str(source),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "intent_video_reobserved": True, "operations_reobserved": False,
            "scope": "new_intent_hierarchy_and_causal_review_of_saved_operations",
            "description": args.description,
            "reviewed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        }
        build_learning_graph(bundle)
        if bundle["intent_alignment"]["issues"]:
            raise ValueError(bundle["intent_alignment"]["issues"])
        bundle["validation"] = semantic.validate(bundle)
        save("result.json", bundle)
        save("task_skill_graph.json", bundle["semantic_graph"])
        save("intent_hierarchy.json", bundle["semantic_graph"]["x-meta"]["intent_hierarchy"])
        semantic.render(bundle, out)
        save("progress.json", {"stage": "complete", "status": "complete",
                               "validation_passed": bundle["validation"]["passed"]})
        print(json.dumps({"output": str(out), "validation_passed": bundle["validation"]["passed"],
                          "tasks": bundle["semantic_graph"]["x-meta"]["intent_hierarchy"]["tasks"]},
                         ensure_ascii=False), flush=True)
    finally:
        save("model_metrics.json", client.stats)
        client.session.close()


if __name__ == "__main__":
    main()

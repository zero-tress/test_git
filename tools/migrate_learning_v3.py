"""Rebuild saved evidence as semantic learning output in a NEW directory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import semantic
from video2op.pipeline import build_learning_graph


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if args.output.exists():
        p.error("output must be a new directory; preserve all existing results")
    b = json.loads(args.source.read_text(encoding="utf-8"))
    b["semantic_revision"] = {"source": str(args.source.resolve()), "video_reobserved": False,
        "scope": "saved_observations_only"}
    # Old reports may include object-qualified names. Only known exact suffixes
    # are removed; compound or unknown actions require fresh task extraction.
    for n in b.get("task_nodes", {}).get("task_nodes", []):
        name = n["name"]
        for suffix in ("目标", "手臂"):
            if name.endswith(suffix):
                try:
                    semantic.canonical(name[:-len(suffix)])
                except ValueError:
                    continue
                n["name_evidence"] = name
                n["name"] = name[:-len(suffix)]
    build_learning_graph(b)
    b["validation"] = semantic.validate(b)
    args.output.mkdir(parents=True)
    (args.output / "result.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
    semantic.export(b, args.output)
    semantic.render(b, args.output)
    print(json.dumps({"output": str(args.output), "validation": b["validation"], "nodes": [
        (k, v["name"]) for k, v in b["semantic_graph"]["nodes"].items()]}, ensure_ascii=False))
if __name__ == "__main__":
    main()

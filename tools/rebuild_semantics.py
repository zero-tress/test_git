"""Rebuild operation semantics from saved observations without overwriting a case.

Run on the study server. --refresh-task calls the configured model only for the
task-node stage; it does not claim to have re-observed the source video.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import graph, media, semantic
from video2op.llm import VLMClient
from video2op.pipeline import build_operation_graph
from video2op.stages import s02b_atomic, s02b_merge, s02c_task, s06_validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing result.json")
    parser.add_argument("output", type=Path, help="Separate review directory")
    parser.add_argument("--refresh-task", action="store_true")
    parser.add_argument("--reobserve-video", type=Path,
                        help="Re-extract visible actions and world states; also refresh task nodes")
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.output.resolve()
    if source.parent == out:
        parser.error("Use a separate output directory to preserve observations")
    out.mkdir(parents=True, exist_ok=True)
    bundle = json.loads(source.read_text(encoding="utf-8"))
    if args.refresh_task or args.reobserve_video:
        client = VLMClient(out / "cache")
        if args.reobserve_video:
            video = args.reobserve_video.resolve()
            ctx = dict(bundle, video=video, meta=media.probe(video),
                       profile=media.motion_profile(video), video_id=media.file_sha1(video)[:16])
            windows = s02b_atomic.run(client, ctx)
            bundle["meta"] = ctx["meta"]
            bundle["atomic"] = s02b_merge.run(windows["windows"], ctx["meta"]["duration"])
            bundle["relations"] = bundle["atomic"]["temporal_relations"]
            (out / "observations.json").write_text(json.dumps(windows, ensure_ascii=False, indent=2), encoding="utf-8")
        bundle["task_nodes"] = s02c_task.run(client, bundle)
        # These stages refer to previous nodes; do not present them as current validation.
        bundle["previous_analysis"] = {k: bundle.pop(k, {}) for k in
                                       ("sync", "conditions", "rules", "link")}
    bundle["semantic_revision"] = {
        "version": "2.0", "source": str(source),
        "task_nodes_refreshed": bool(args.refresh_task or args.reobserve_video or
                                     bundle.get("semantic_revision", {}).get("task_nodes_refreshed")),
        "video_reobserved": bool(args.reobserve_video or
                                  bundle.get("semantic_revision", {}).get("video_reobserved")),
        "scope": "operation_contract_and_evidence_audit",
    }
    build_operation_graph(bundle)
    bundle["validation"] = s06_validate.run(bundle)
    bundle["graph"] = graph.build(bundle["atomic"].get("atomic_actions", []),
                                   bundle.get("relations") or [])
    (out / "result.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    semantic.export(bundle, out)
    semantic.render(bundle, out)
    print(json.dumps({"output": str(out), "operations": bundle["operations"]["stats"],
                      "reasoning": bundle["reasoning"]["stats"],
                      "validation": bundle["validation"]["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

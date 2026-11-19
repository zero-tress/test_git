"""Learn contrastive conditions, semantic rules, branch/function merges via 8032."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config
from video2op.llm import VLMClient, require_deployed_model
from video2op.contracts.learning_contracts import source_fingerprint, policy_prompt
from video2op.cross_video.skill_sample_pool import GROUP_SYSTEM, REVIEW_SYSTEM
from video2op.cross_video.semantic_selection import SELECTION_SYSTEM
from video2op.cross_video.cross_video_tuples import TUPLE_SYSTEM
from video2op.cross_video.semantic_aggregation import (
    CONDITION_SYSTEM,
    GRAPH_SYSTEM,
    RULE_SYSTEM,
    digest,
    export,
    learn,
    load_cases,
    save,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-8032", action="store_true", help="Authorize existing loopback model service")
    parser.add_argument("--resume", action="store_true", help="Reuse only matching interrupted request caches")
    parser.add_argument("--refresh-prompts", action="store_true",
                        help="允许提示词指纹变化后续跑；各阶段缓存仍按内容寻址校验")
    parser.add_argument("--refresh-sources", action="store_true",
                        help="同一批视频重新学习后允许续跑；源路径与视频hash必须不变，只接受结果hash更新")
    parser.add_argument("--graph-requirements", type=Path,
                        help="显式任务图政策JSON；允许入口/分支语义重排")
    args = parser.parse_args(argv)
    if not args.allow_8032:
        parser.error("--allow-8032 required: all semantic learning uses the deployed model")
    require_deployed_model(config.BASE_URL, config.MODEL)
    requirements = json.loads(args.graph_requirements.read_text(encoding="utf-8")) if args.graph_requirements else None
    if requirements is not None and not isinstance(requirements, dict):
        parser.error("graph requirements must be a JSON object")
    cases = load_cases(args.inputs)
    out = args.out.resolve()
    manifest = {"schema_version": "semantic_learning_run.v1", "model": config.MODEL, "base_url": config.BASE_URL,
                "sources": [{"source": case["source"], "sha256": case["source_sha256"], "video_uid": case["video_uid"]} for case in cases],
                "prompt_fingerprint": digest([CONDITION_SYSTEM, RULE_SYSTEM, GRAPH_SYSTEM, GROUP_SYSTEM,
                                              REVIEW_SYSTEM, SELECTION_SYSTEM, TUPLE_SYSTEM,
                                              policy_prompt(requirements), source_fingerprint()]),
                "code_sha256": source_fingerprint(),
                "graph_requirements": requirements,
                "graph_requirements_sha256": digest(requirements) if requirements is not None else None}
    if out.exists() and any(out.iterdir()):
        if not args.resume:
            parser.error("output is nonempty; choose a new directory or explicitly --resume unchanged inputs")
        saved = out / "run_manifest.json"
        if not saved.is_file():
            parser.error("resume refused: run manifest missing")
        previous = json.loads(saved.read_text())
        for key in ("model", "base_url"):
            if previous.get(key) != manifest[key]:
                parser.error(f"resume refused: {key} changed; choose a new directory")
        if previous.get("graph_requirements_sha256") != manifest["graph_requirements_sha256"]:
            if not args.refresh_sources:
                parser.error("resume refused: task policy changed; pass --refresh-sources after refreshing the cases")
        if previous.get("sources") != manifest["sources"]:
            before = [(row.get("source"), row.get("video_uid")) for row in previous.get("sources") or []]
            now = [(row.get("source"), row.get("video_uid")) for row in manifest["sources"]]
            if before != now:
                parser.error("resume refused: source files or videos changed; choose a new directory")
            if not args.refresh_sources:
                parser.error("resume refused: source result hashes changed; pass --refresh-sources "
                             "after re-learning the same videos in this batch")
            manifest["previous_sources"] = previous["sources"]
            manifest["source_refresh"] = "same videos re-learned; result hashes updated"
        if previous.get("prompt_fingerprint") != manifest["prompt_fingerprint"]:
            if not args.refresh_prompts:
                parser.error("resume refused: prompt fingerprint changed; pass --refresh-prompts "
                             "to rerun the affected stages (content-addressed caches still validate every hit)")
            manifest["previous_prompt_fingerprint"] = previous["prompt_fingerprint"]
    elif args.resume:
        parser.error("resume requires an existing interrupted output with a run manifest")
    out.mkdir(parents=True, exist_ok=True)
    save(out / "run_manifest.json", manifest)
    client = VLMClient(out / "cache")
    try:
        save(out / "progress.json", {"status": "running", "stages": [
            "contrastive_conditions", "semantic_rules", "cross_semantic", "skill_tuples"]})
        graph = learn(client, cases, requirements)
        validation = export(graph, cases, out)
        save(out / "progress.json", {"status": "complete", "validation": validation})
        print(json.dumps({"output": str(out), "validation": validation}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        save(out / "progress.json", {"status": "failed", "error": str(exc), "fallback": False})
        raise
    finally:
        save(out / "model_metrics.json", client.stats)
        client.session.close()


if __name__ == "__main__":
    raise SystemExit(main())

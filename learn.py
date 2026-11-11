"""Build reviewable goal/effect knowledge from independent saved cases (study environment)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from video2op import semantic
from video2op.knowledge import aggregate, extract, render, video_identity
from video2op.llm import VLMClient
from video2op.pipeline import build_learning_graph
from video2op.stages import s08_scope


def load_reviewed(path: Path | None, cases: list[dict]) -> list[dict]:
    if path is None:
        return []
    from video2op.stages.s08_scope import _evidence
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("reviewed observations must be a list")
    instances = {i["instance_id"]: i for c in cases for i in c["instances"]}
    for r in rows:
        item = instances.get(r.get("instance_id"))
        if item is None or r.get("video_uid") != item["video_uid"] or not r.get("reviewer"):
            raise ValueError("reviewed observation must name a loaded instance, video and reviewer")
        if r.get("goal_key") != item["goal_key"]:
            raise ValueError("reviewed observation goal does not match its instance")
        actions = {a["id"]: a for a in item["observed_process"]}
        for e in [*r.get("evidence", []), *r.get("outcome_evidence", [])]:
            _evidence(e, actions)
        if r.get("truth") in {"T", "F"}:
            if not r.get("evidence"):
                raise ValueError("condition truth requires evidence")
            start = min(a["start"] for a in actions.values())
            end = max(a["end"] for a in actions.values())
            for e in r["evidence"]:
                a = actions[e["atomic_ref"]]
                t = a["start"] if "before" in e["field"] else a["end"]
                if (r.get("at", "pre") == "pre" and t > start) or (r.get("at") == "post" and t < end):
                    raise ValueError("reviewed condition is not at its annotated boundary")
        r["provenance"] = "reviewed_observation"
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按局部目的/目标效果跨视频归纳，保留对象与实现方式")
    ap.add_argument("--inputs", nargs="+", required=True, help="result.json或其所在案例目录")
    ap.add_argument("--out", type=Path, required=True, help="新的输出目录，不覆盖原案例")
    ap.add_argument("--refresh-scope", action="store_true", help="访问已配置模型重新识别子任务范围")
    ap.add_argument("--reviewed-observations", type=Path, help="带审阅者和真实证据的条件对照样本JSON")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("输出目录已有文件，请指定新目录")
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for index, name in enumerate(args.inputs):
        source = Path(name).resolve()
        source = source / "result.json" if source.is_dir() else source
        b = json.loads(source.read_text(encoding="utf-8"))
        destination = out / "cases" / f"{index + 1:02d}_{source.parent.name}"
        destination.mkdir(parents=True)
        from video2op.media_quality import annotate, audit
        media_path = Path(b.get("meta", {}).get("path") or "")
        if media_path.is_file() and not b.get("meta", {}).get("media_quality"):
            b["meta"]["media_quality"] = audit(media_path)
        annotate(b)
        if args.refresh_scope:
            ctx = {**b, "task_nodes": b.get("task_nodes_source") or b.get("task_nodes")}
            b["semantic_scope"] = s08_scope.run(VLMClient(destination / "cache"), ctx)
        if not b.get("semantic_scope"):
            b["semantic_scope"] = {"subtasks": [], "unresolved": [
                "Saved case has no goal-scoped annotations; only explicit leaf skills can be grouped."]}
        if b.get("semantic_scope", {}).get("subtasks"):
            s08_scope.expand_evidence(b["semantic_scope"], b)
        b["source_video_sha256"], _ = video_identity(b)
        build_learning_graph(b)
        b["validation"] = semantic.validate(b)
        (destination / "result.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
        semantic.export(b, destination)
        semantic.render(b, destination)
        cases.append(extract(b, str(source)))
        print(f"{source.parent.name}: {len(cases[-1]['instances'])}个技能/子任务实例；{b['validation']['summary']}", flush=True)
    reviewed = load_reviewed(args.reviewed_observations, cases)
    knowledge = aggregate(cases, reviewed)
    (out / "knowledge.json").write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "review.html").write_text(render(knowledge), encoding="utf-8")
    print(f"视频{len(knowledge['sources'])}；语义技能{len(knowledge['skills'])}；"
          f"对象任务族{len(knowledge['task_families'])}；实例{len(knowledge['instances'])}", flush=True)
    return 0 if knowledge["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

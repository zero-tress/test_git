"""Attach model-review evidence without altering frozen learned memberships or labels."""
import argparse
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.cross_video_delivery import save
from video2op.skill_clips import sha256


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery", required=True, type=Path)
    ap.add_argument("--clips", required=True, type=Path)
    ap.add_argument("--reviews", required=True, nargs="+", type=Path)
    args = ap.parse_args(argv)
    root = args.delivery.resolve()
    frozen_path = root/"knowledge_development/knowledge.json"
    frozen = sha256(frozen_path)
    manifest = json.loads(args.clips.read_text())
    by_case = {r["case_id"]: r["source_sha256"] for r in manifest["videos"]}
    all_attempts, completed, stats = [], {}, []
    for p in args.reviews:
        run = json.loads(p.read_text())
        stats.append({"source": str(p.resolve()), "sha256": sha256(p), "stats": run["model_stats"]})
        for review in run["results"]:
            all_attempts.append({"name": review["name"], "status": review["status"], "source": str(p.resolve()),
                                 "errors": review.get("errors", [])})
            if review["status"] == "completed":
                review = dict(review)
                review["result_source"] = str(p.resolve())
                review["frame_sha256"] = {f["path"]: sha256(f["path"]) for f in review["frames"]}
                completed[review["name"]] = review
    proposals = {}
    for name, r in completed.items():
        for b in r["response"].get("suggested_boundaries", []):
            proposals.setdefault(b["case_id"], []).append({"review": name, **b})
    conflicts = [{"case_id": case, "reason": "model_boundary_proposals_disagree", "proposals": values,
                  "resolution": "preserve_all_candidates_do_not_overwrite_original_clip"}
                 for case, values in proposals.items() if len({(v["start"], v["end"]) for v in values}) > 1]
    result = {"completed_reviews": list(completed.values()), "attempts": all_attempts,
              "runs": stats, "conflicts": conflicts,
              "policy": "Model review is supplementary candidate evidence, not human verification or controlled causality.",
              "updates_applied_to_learned_membership": False, "updates_applied_to_clip_boundaries": False}
    save(root/"model_reviews.json", result)
    save(root/"review_conflicts.json", conflicts)
    for group in ["knowledge_development", "knowledge_all_16", "holdout_observations"]:
        p = root/group/"evidence_index.json"
        index = json.loads(p.read_text())
        for row in index:
            row["supplementary_model_reviews"] = [
                {"name": name, "provenance": "additional_model_review_candidate", "human_verified": False,
                 "review_file": "../model_reviews.json"}
                for name, review in completed.items() if row["video_uid"] in {by_case[c] for c in review["cases"]}]
        save(p, index)
    rows = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>三组模型复核证据</title>',
            '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto}img{width:310px;max-width:100%}pre{white-space:pre-wrap;background:#f8fafc;padding:16px}section{border-top:1px solid #ccc;padding:20px}</style>',
            '<h1>三组模型复核证据</h1><p>模型意见独立保存。边界建议有冲突，未自动改写切片；现有知识成员、真值和未知状态保持原样。</p>',
            '<h2>边界意见冲突</h2><pre>'+html.escape(json.dumps(conflicts,ensure_ascii=False,indent=2))+'</pre>']
    for name, r in completed.items():
        rows.append("<section><h2>"+html.escape(name)+"</h2><pre>"+html.escape(json.dumps(r["response"],ensure_ascii=False,indent=2))+"</pre>")
        for f in r["frames"]:
            url = quote(os.path.relpath(f["path"], root), safe="/")
            rows.append(f'<figure style="display:inline-block"><img loading="lazy" src="{url}" alt="{html.escape(f["frame_id"],quote=True)}"><figcaption>{html.escape(f["frame_id"])} · {f["timestamp"]}s</figcaption></figure>')
        rows.append("</section>")
    rows.append('<h2>调用与失败记录</h2><pre>'+html.escape(json.dumps(all_attempts,ensure_ascii=False,indent=2))+'</pre></html>')
    (root/"model_review.html").write_text("\n".join(rows))
    p = root/"verification_summary.json"
    summary = json.loads(p.read_text())
    summary["model_review"] = {"completed_examples": len(completed),
                               "total_attempts": sum(r["stats"]["calls"] for r in stats),
                               "failed_attempts": sum(a["status"] != "completed" for a in all_attempts),
                               "boundary_conflicts": len(conflicts), "automatic_promotions": 0,
                               "human_verified": False}
    summary["offline_generalization_network_used"] = False
    summary["supplementary_model_review_network_used"] = True
    summary["network_used"] = True
    save(p, summary)
    p = root/"index.html"
    body = p.read_text()
    link = '<li><a href="model_review.html">三组真实模型复核与边界冲突</a></li>'
    if link not in body:
        p.write_text(body.replace("</ul>",link+"</ul>"))
    body = p.read_text()
    marker = '<pre style="white-space:pre-wrap">'
    if marker in body:
        before, remainder = body.split(marker, 1)
        _, after = remainder.split("</pre>", 1)
        p.write_text(before + marker + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>" + after)
    (root/"实施结果.md").write_text("# 跨视频归纳实施结果\n\n"
        +"技能切片、路径保留检查、模型复核和人工确认分别记录。模型建议未自动回写边界、标签或技能成员。\n\n"
        +"~~~json\n"+json.dumps(summary,ensure_ascii=False,indent=2)+"\n~~~\n\n"
        +"三组复核共5次接口请求（3次成功、2次HTTP400）；减少比较输入帧后重试成功。\n"
        +"同一抓取实例存在边界建议冲突，已保留原片段和两份建议。\n"
        +"语义同义对齐、分支适用条件、局部效果和因果证据仍待审阅，参见evidence_gaps.json、review_conflicts.json和acceptance_ledger.json。\n")
    if frozen != sha256(frozen_path):
        raise ValueError("Frozen knowledge changed while attaching reviews")
    print(json.dumps(summary["model_review"],ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise existing video/semantic stages on saved ambiguous examples, without reference labels."""
from pathlib import Path
import json
import sys
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config, media
from video2op.llm import VLMClient
from video2op.stages import s02a_intent, s03_sync, s05_rules
from video2op.learning_alignment import apply_intent_updates

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/semantic_learning_20261111/model_validation"

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config.WORK_DIR = OUT / "work"
    config.VIDEO_TIMEOUT = 180
    config.TEXT_TIMEOUT = 120
    config.MAX_ATTEMPTS = 2
    choices = [("ambiguous_03", ROOT / "output/semantic_16_20261107/cases/video_03_semantic_v3/result.json"),
               ("ambiguous_11", ROOT / "output/semantic_16_20261107/cases/video_11_semantic_v3/result.json"),
               ("historical_grasp", ROOT / "output/抓取2_semantic_v3/result.json")]
    rows = []
    for name, path in choices:
        dest = OUT / name
        dest.mkdir(exist_ok=True)
        b = json.loads(path.read_text())
        video = Path(b["meta"]["path"])
        ctx = deepcopy(b)
        ctx.update(video=video, video_id=media.file_sha1(video)[:16])
        if name == "ambiguous_03":
            ctx["text_description"] = {"text": "观察桌面上盒子与手的交互，意图不确定时保留不同合理解释。", "provenance": "text_description"}
        client = VLMClient(dest / "cache")
        row = {"example": name, "source": str(path), "reference_labels_used": False}
        try:
            ctx["intents"] = s02a_intent.run(client, ctx)
            (dest / "s02a_intent.json").write_text(json.dumps(ctx["intents"], ensure_ascii=False, indent=2))
            row["candidates_before"] = [{"id": i["id"], "confidence": i["confidence"]} for i in ctx["intents"]["intents"]]
            ctx["sync"] = s03_sync.run(client, ctx)
            apply_intent_updates(ctx)
            row["candidates_after"] = [{"id": i["id"], "confidence": i["confidence"]} for i in ctx["intents"]["intents"]]
            row["reordered"] = [i["id"] for i in row["candidates_before"]] != [i["id"] for i in row["candidates_after"]]
            (dest / "s03_sync.json").write_text(json.dumps(ctx["sync"], ensure_ascii=False, indent=2))
            rules = s05_rules.run(client, ctx)
            (dest / "s05_rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2))
            row["pattern_types"] = sorted({p["pattern"] for p in rules["temporal_structures"]})
            row["status"] = "completed"
        except Exception as e:
            row.update(status="needs_review", error=type(e).__name__ + ": " + str(e)[:800])
        row["model_stats"] = client.stats
        rows.append(row)
        (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0 if all(r["status"] == "completed" for r in rows) else 1

if __name__ == "__main__":
    raise SystemExit(main())

"""Generate via the configured model, then validate and render its graph without semantic fallbacks."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.merged_workbench import analyze_then_export, export

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--analyze", action="store_true", help="Ask the configured deployed model for the successful-process graph"
    )
    parser.add_argument("--allow-model-service", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--graph-requirements", type=Path, help="Explicit user graph policy JSON; applies to this output only"
    )
    args = parser.parse_args()
    if args.graph_requirements:
        from video2op.skill_clips import save

        requirements = json.loads(args.graph_requirements.read_text())
        if not isinstance(requirements, dict):
            raise ValueError("Graph requirements must be a JSON object")
        save(args.out / "graph_requirements.json", requirements)
    result = (
        analyze_then_export(args.out, allow_model_service=args.allow_model_service, force=args.force)
        if args.analyze
        else export(args.out)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

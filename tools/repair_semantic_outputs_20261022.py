"""Refresh existing semantic v3 artifacts from saved observations, preserving originals."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video2op import semantic
from video2op.pipeline import build_learning_graph

for source in sorted((ROOT / "output").glob("*semantic_v3*/result.json")):
    case = source.parent
    bundle = json.loads(source.read_text(encoding="utf-8"))
    # Compute first; on an incompatible observation do not change existing files.
    build_learning_graph(bundle)
    bundle["validation"] = semantic.validate(bundle)
    backup = ROOT / "backups/semantic_view_correction_20261022" / case.relative_to(ROOT)
    backup.mkdir(parents=True, exist_ok=True)
    for name in ("result.json", "semantic_graph.yaml", "action_catalog.json",
                 "operations.svg", "workbench.html", "report.html"):
        src, dst = case / name, backup / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    source.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    semantic.export(bundle, case)
    semantic.render(bundle, case)
    print(json.dumps({"case": case.name, "backup": str(backup),
          "actors": [n["skill"]["X"] for k, n in bundle["semantic_graph"]["nodes"].items()
                     if k not in ("START", "END")],
          "operations": len(bundle["operations"]["nodes"])}, ensure_ascii=False))

"""Refresh only the two requested results using their saved video evidence."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video2op import semantic
from video2op.pipeline import build_learning_graph

backup = ROOT / "backups" / ("release_gate_outputs_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
for name in ("抓取1_semantic_v3", "抓取2_semantic_v3"):
    case = ROOT / "output" / name
    source = case / "result.json"
    bundle = json.loads(source.read_text())
    original = deepcopy(bundle["atomic"])
    build_learning_graph(bundle)
    assert bundle["atomic"] == original, "Saved atomic observations must not change"
    bundle["validation"] = semantic.validate(bundle)
    print(name, "validation:", json.dumps(bundle["validation"], ensure_ascii=False))
    tasks = bundle["task_nodes"]["task_nodes"]
    layers = {nid: i for i, col in enumerate(bundle["operations"]["semantic_columns"]) for nid in col}
    for release in (n for n in tasks if n["name"] == "释放"):
        for approach in (n for n in tasks if n["name"] == "靠近"):
            assert layers[release["id"]] != layers[approach["id"]]
    dest = backup / "output" / name
    dest.mkdir(parents=True)
    for file in ("result.json", "semantic_graph.yaml", "action_catalog.json",
                 "operations.svg", "workbench.html", "report.html"):
        if (case / file).exists():
            shutil.copy2(case / file, dest / file)
    source.write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
    semantic.export(bundle, case)
    semantic.render(bundle, case)
    print(name, "columns:", [[next(n["name"] for n in tasks if n["id"] == nid) for nid in col]
                             for col in bundle["operations"]["semantic_columns"]])
print("Backup:", backup)

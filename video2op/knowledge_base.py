"""Immutable content-addressed versions of canonical semantic skills."""
import hashlib
import json
from pathlib import Path

def ingest(tuples, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "index.json"
    index = json.loads(path.read_text()) if path.exists() else {"schema_version": "semantic_kb.v1", "skills": {}}
    for skill in tuples["skills"]:
        data = json.dumps({"skill": skill, "predicates": tuples["predicates"]}, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        version = hashlib.sha256(data.encode()).hexdigest()
        target = root / "versions" / skill["skill_id"] / (version + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text() != data:
            raise ValueError("immutable knowledge version differs")
        if not target.exists():
            target.write_text(data)
        entry = {"version": version, "path": str(target.relative_to(root)),
                 "status": skill["verification_status"],
                 "source_sha256": sorted({p["video_sha256"] for p in skill["provenance"]})}
        versions = index["skills"].setdefault(skill["skill_id"], [])
        if not any(v["version"] == version for v in versions):
            versions.append(entry)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    return index

def query(root, skill_id, version=None):
    root = Path(root)
    index = json.loads((root / "index.json").read_text())
    choices = index["skills"].get(skill_id, [])
    if not choices:
        raise KeyError(skill_id)
    entry = choices[-1] if version is None else next((c for c in choices if c["version"] == version), None)
    if entry is None:
        raise KeyError(version)
    return json.loads((root / entry["path"]).read_text())

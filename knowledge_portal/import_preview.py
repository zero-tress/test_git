"""Copy existing evidence into an isolated, provisional PostgreSQL schema."""
from pathlib import Path
import hashlib, json, sys
from db import ROOT, execute, json_sql, sql_text
def main():
    source = ROOT / "output/current"
    cases = sorted((source / "knowledge_all_16/cases").glob("*/result.json"))
    if len(cases) != 16:
        raise RuntimeError("Expected 16 current cases")
    if execute("SELECT to_regclass('preview.imports') IS NOT NULL;") == "t":
        raise RuntimeError("Preview already imported; preserving existing preview")
    rows = ["""BEGIN;
    CREATE SCHEMA preview;
    CREATE TABLE preview.imports(id text PRIMARY KEY, imported_at timestamptz NOT NULL DEFAULT now(), source text NOT NULL, note text NOT NULL);
    CREATE TABLE preview.videos(id text PRIMARY KEY, sha256 text UNIQUE NOT NULL, title text NOT NULL, metadata jsonb NOT NULL);
    CREATE TABLE preview.cases(id text PRIMARY KEY, video_id text NOT NULL REFERENCES preview.videos(id), title text NOT NULL, outcome text NOT NULL, node_count integer NOT NULL, graph jsonb NOT NULL, result jsonb NOT NULL);
    CREATE TABLE preview.skill_versions(skill_id text NOT NULL, version text NOT NULL, name text NOT NULL, verification_status text NOT NULL, payload jsonb NOT NULL, PRIMARY KEY(skill_id,version));
    CREATE TABLE preview.artifacts(id text PRIMARY KEY, case_id text NOT NULL REFERENCES preview.cases(id), filename text NOT NULL, mime_type text NOT NULL, sha256 text NOT NULL, byte_size bigint NOT NULL, content bytea NOT NULL, UNIQUE(case_id,filename));
    CREATE INDEX ON preview.cases(video_id);
    CREATE INDEX ON preview.skill_versions(name);
    CREATE INDEX ON preview.cases USING gin(graph);
    """]
    annotations = json.loads((ROOT / "data/16段视频_命名标注/标注数据.json").read_text())["视频标注"]
    annotations = {x["编号"]: x for x in annotations}
    artifacts = 0
    for p in cases:
        b = json.loads(p.read_text())
        cid = p.parent.name[:2]
        ann = annotations[cid]
        vid = b["source_video_sha256"]
        graph = b["semantic_graph"]
        title = ann["新文件名"].removesuffix(".mp4")
        outcome = b.get("task_observation", {}).get("outcome", "unknown")
        args = [sql_text(cid), sql_text(vid), sql_text(title), json_sql(ann)]
        rows.append("INSERT INTO preview.videos VALUES(" + ",".join(args) + ");")
        args = [sql_text(cid), sql_text(cid), sql_text(title), sql_text(outcome), str(len(b["task_nodes"]["task_nodes"])), json_sql(graph), json_sql(b)]
        rows.append("INSERT INTO preview.cases VALUES(" + ",".join(args) + ");")
        for f in sorted(p.parent.iterdir()):
            if not f.is_file(): continue
            raw = f.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            aid = hashlib.sha256((cid + "/" + f.name).encode()).hexdigest()[:24]
            mime = {".html":"text/html", ".svg":"image/svg+xml", ".json":"application/json", ".yaml":"text/yaml"}.get(f.suffix, "application/octet-stream")
            args = [sql_text(aid), sql_text(cid), sql_text(f.name), sql_text(mime), sql_text(sha), str(len(raw)), "decode('" + raw.hex() + "','hex')"]
            rows.append("INSERT INTO preview.artifacts VALUES(" + ",".join(args) + ");")
            artifacts += 1
    index = json.loads((ROOT / "knowledge_base/index.json").read_text())
    versions = 0
    for sid, entries in index["skills"].items():
        for entry in entries:
            p = ROOT / "knowledge_base" / entry["path"]
            raw = p.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["version"]:
                raise RuntimeError("Version hash mismatch")
            payload = json.loads(raw)
            skill = payload["skill"]
            args = [sql_text(sid),sql_text(entry["version"]),sql_text(skill["name"]),sql_text(skill["verification_status"]),json_sql(payload)]
            rows.append("INSERT INTO preview.skill_versions VALUES(" + ",".join(args) + ");")
            versions += 1
    rows.append("INSERT INTO preview.imports(id,source,note) VALUES('initial'," + sql_text(str(source)) + "," + sql_text("仅供表结构审阅的独立副本，正式模型待用户确认；原始知识与文件未修改") + ");")
    rows.append("COMMIT;")
    execute("\n".join(rows))
    print(json.dumps({"cases":len(cases),"skill_versions":versions,"artifacts":artifacts},ensure_ascii=False))
if __name__ == "__main__": main()

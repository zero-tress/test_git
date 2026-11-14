"""Approved video-side schema migration; skill storage, learning and UI remain frozen."""
from pathlib import Path
import hashlib,json,subprocess,tempfile,uuid
from db import ROOT,RUNTIME,PGBIN,execute,query,sql_text,json_sql,connection_env
MIGRATION="video_media_20261112"
WORK=RUNTIME/"migrations"/MIGRATION
REVIEW=ROOT/"knowledge_portal/reviews/知识库表结构审阅意见_20261112.json"
def sha(raw):return hashlib.sha256(raw).hexdigest()
def uid(kind,key):return str(uuid.uuid5(uuid.NAMESPACE_URL,"videostudy/"+kind+"/"+key))
def freeze():
    app=(ROOT/"knowledge_portal/web/app.js").read_text()
    return {"skill_rows":query("SELECT json_agg(t ORDER BY skill_id,version) FROM preview.skill_versions t;"),
      "skill_columns":query("SELECT json_agg(t ORDER BY ordinal_position) FROM (SELECT column_name,data_type,is_nullable,ordinal_position FROM information_schema.columns WHERE table_schema='preview' AND table_name='skill_versions') t;"),
      "skill_ui":sha(app[app.index("async function skillPage()"):app.index("async function proposal()")].encode()),
      "learning_files":{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [ROOT/"learn.py",*(ROOT/"video2op").rglob("*.py"),*(ROOT/"knowledge_base").rglob("*.json")]}}
def main():
    if WORK.exists():raise RuntimeError("Migration workspace already exists; inspect existing outcome before retry")
    review=json.loads(REVIEW.read_text())
    assert len(review["tables"])==8 and all(x.strip()=="保留" for x in review["notes"].values())
    WORK.mkdir(parents=True,mode=0o700)
    before=freeze();(WORK/"before.json").write_text(json.dumps(before,ensure_ascii=False))
    # Authenticated project account performs backup and all data writes.
    subprocess.run([str(PGBIN/"pg_dump"),"-Fc","--no-owner","--no-privileges","-f",str(WORK/"before.dump")],env=connection_env(readonly=True),check=True,capture_output=True)
    cases=query("SELECT json_agg(q ORDER BY id) FROM (SELECT c.*,v.sha256 video_sha,v.metadata video_meta FROM preview.cases c JOIN preview.videos v ON c.video_id=v.id) q;")
    prepared=[]
    for c in cases:
        original=ROOT/"data/16段视频_命名标注"/c["video_meta"]["视频相对路径"]
        assert original.resolve().is_relative_to(ROOT/"data")
        raw=original.read_bytes()
        assert sha(raw)==c["video_sha"]
        playback=WORK/(c["id"]+"_h264.mp4")
        subprocess.run(["ffmpeg","-nostdin","-v","error","-i",str(original),"-map","0:v:0","-map","0:a?","-c:v","libx264","-threads","1","-preset","fast","-crf","20","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(playback)],check=True,capture_output=True,timeout=90)
        play=playback.read_bytes()
        probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(playback)],text=True))
        assert next(x for x in probe["streams"] if x["codec_type"]=="video")["codec_name"]=="h264"
        prepared.append((c,original,raw,play,probe))
    # Explicitly authorized schema maintenance; no DML to skill tables.
    execute("""BEGIN;
    ALTER TABLE preview.videos ADD COLUMN source_uri text, ADD COLUMN split text,
      ADD COLUMN original_filename text, ADD COLUMN mime_type text NOT NULL DEFAULT 'video/mp4',
      ADD COLUMN content bytea, ADD COLUMN byte_size bigint, ADD COLUMN playback_content bytea,
      ADD COLUMN playback_sha256 text, ADD COLUMN playback_bytes bigint, ADD COLUMN playback_metadata jsonb;
    CREATE TABLE preview.analysis_runs(
      id uuid PRIMARY KEY, video_id text NOT NULL REFERENCES preview.videos(id),
      source_case_id text UNIQUE NOT NULL REFERENCES preview.cases(id),
      code_version text, model text, prompt_version text, config jsonb NOT NULL,
      status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE preview.operation_graph_versions(
      id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES preview.analysis_runs(id),
      parent_version_id uuid REFERENCES preview.operation_graph_versions(id),
      graph jsonb NOT NULL, semantic_hash text NOT NULL,
      verification_status text NOT NULL CHECK(verification_status IN ('verified','unverified','unverifiable')));
    ALTER TABLE preview.cases ADD COLUMN graph_version_id uuid REFERENCES preview.operation_graph_versions(id);
    ALTER TABLE preview.artifacts ADD COLUMN graph_version_id uuid REFERENCES preview.operation_graph_versions(id),
      ADD COLUMN renderer_version text, ADD COLUMN dependencies jsonb NOT NULL DEFAULT '[]';
    CREATE TABLE preview.reviews(id uuid PRIMARY KEY, subject_type text NOT NULL,
      subject_id text NOT NULL, reviewer text NOT NULL, decision text NOT NULL,
      comment text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    ALTER TABLE preview.analysis_runs OWNER TO videostudy_owner;
    ALTER TABLE preview.operation_graph_versions OWNER TO videostudy_owner;
    ALTER TABLE preview.reviews OWNER TO videostudy_owner;
    GRANT SELECT,INSERT,UPDATE,DELETE ON preview.analysis_runs,preview.operation_graph_versions,preview.reviews TO videostudy_app;
    CREATE INDEX ON preview.analysis_runs(video_id);
    CREATE INDEX ON preview.operation_graph_versions(run_id);
    CREATE INDEX ON preview.artifacts(graph_version_id);
    COMMIT;""",admin=True)
    statements=["BEGIN;"]
    for c,original,raw,play,probe in prepared:
        cid=sql_text(c["id"]);runid=uid("run",c["id"]);graphid=uid("graph",c["id"])
        # Provenance identifies this as an import of existing results, not a new model run.
        b=c["result"];pipeline=b.get("pipeline",{})
        split="holdout" if c["id"] in {"02","06","14"} else "development"
        statements.append("UPDATE preview.videos SET "+",".join([
          "source_uri="+sql_text(str(original.relative_to(ROOT))),
          "split="+sql_text(split),"original_filename="+sql_text(original.name),
          "content=decode('"+raw.hex()+"','hex')","byte_size="+str(len(raw)),
          "playback_content=decode('"+play.hex()+"','hex')","playback_sha256="+sql_text(sha(play)),
          "playback_bytes="+str(len(play)),"playback_metadata="+json_sql({"codec":"h264","container":"mp4","origin":"browser_playback_derivative","original_sha256":sha(raw),"probe":probe})
        ])+" WHERE id="+sql_text(c["video_id"])+";")
        config={"origin":"import_existing_analysis","source_case_id":c["id"],"original_pipeline":pipeline,
                "source_code_version":b.get("code_version"),"prompt_version_status":"not_recorded_in_saved_case",
                "created_at_meaning":"database_import_time"}
        args=[sql_text(runid)+"::uuid",sql_text(c["video_id"]),cid,sql_text(str(pipeline.get("code_version") or b.get("code_version") or "")),sql_text(pipeline.get("model") or ""),"NULL",json_sql(config),"'imported'"]
        statements.append("INSERT INTO preview.analysis_runs(id,video_id,source_case_id,code_version,model,prompt_version,config,status) VALUES("+",".join(args)+");")
        canonical=json.dumps(c["graph"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        args=[sql_text(graphid)+"::uuid",sql_text(runid)+"::uuid",json_sql(c["graph"]),sql_text(sha(canonical)),"'unverified'"]
        statements.append("INSERT INTO preview.operation_graph_versions(id,run_id,graph,semantic_hash,verification_status) VALUES("+",".join(args)+");")
        statements.append("UPDATE preview.cases SET graph_version_id="+sql_text(graphid)+"::uuid WHERE id="+cid+";")
        # Existing render provenance is unknown; do not invent a renderer version.
        statements.append("UPDATE preview.artifacts SET graph_version_id="+sql_text(graphid)+"::uuid WHERE case_id="+cid+";")
    review_hash=sha(REVIEW.read_bytes())
    for table in review["tables"]:
        tid=table["id"]
        comment={"origin":"user_provided_review_json","source":str(REVIEW.relative_to(ROOT)),"source_sha256":review_hash,
                 "note":review["notes"][tid].strip(),"implementation":"deferred_skill_freeze" if tid in {"skills","skill_versions","skill_evidence"} else "implemented_video_scope",
                 "identity_note":"Reviewer personal name was not supplied."}
        args=[sql_text(uid("schema-review",review_hash+"/"+tid))+"::uuid","'schema_plan'",sql_text(tid),"'project_user_review'","'retain'",json_sql(comment)+"::text"]
        statements.append("INSERT INTO preview.reviews(id,subject_type,subject_id,reviewer,decision,comment) VALUES("+",".join(args)+");")
    statements.append("INSERT INTO preview.imports(id,source,note) VALUES("+sql_text(MIGRATION)+","+sql_text(str(REVIEW.relative_to(ROOT)))+","+sql_text("用户保留8项设计；先落实视频与图侧，技能数据库与前端冻结。原视频和H264播放副本均存入BYTEA。")+");")
    statements.append("COMMIT;")
    execute("\n".join(statements))
    execute("""BEGIN;
      ALTER TABLE preview.videos ALTER COLUMN content SET NOT NULL,ALTER COLUMN byte_size SET NOT NULL,
        ALTER COLUMN original_filename SET NOT NULL,ALTER COLUMN playback_content SET NOT NULL,
        ALTER COLUMN playback_sha256 SET NOT NULL,ALTER COLUMN playback_bytes SET NOT NULL;
      ALTER TABLE preview.videos ADD CONSTRAINT videos_content_size CHECK(octet_length(content)=byte_size),
        ADD CONSTRAINT videos_playback_size CHECK(octet_length(playback_content)=playback_bytes);
      ALTER TABLE preview.cases ALTER COLUMN graph_version_id SET NOT NULL;
      ALTER TABLE preview.artifacts ALTER COLUMN graph_version_id SET NOT NULL;
    COMMIT;""",admin=True)
    # Keep existing text identifiers in compatibility tables; UUIDs are used for all new entities.
    after=freeze()
    assert before==after,"Frozen skill storage or learning/UI changed"
    report={"migration":MIGRATION,"original_videos":len(prepared),"original_bytes":sum(len(x[2]) for x in prepared),"playback_bytes":sum(len(x[3]) for x in prepared),
      "analysis_runs":len(prepared),"graph_versions":len(prepared),"reviews":8,"skills_unchanged":True,
      "compatibility":"Existing videos/artifacts text PKs retained to preserve current references; new run/graph/review IDs are UUID.",
      "schema_review_sha256":review_hash,"backup":str(WORK/"before.dump")}
    (WORK/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    # Playback is now in PostgreSQL. Remove only the temporary transcodes created here.
    for p in WORK.glob("*_h264.mp4"):p.unlink()
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()

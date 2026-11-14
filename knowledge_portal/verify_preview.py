"""Read-only integration checks of the real PostgreSQL preview and source bytes."""
import hashlib, json, os, urllib.request, urllib.error
from pathlib import Path
from db import ROOT, RUNTIME, query
BASE="http://127.0.0.1:18773"
import http.cookiejar
BROWSER=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def get(path):
    with BROWSER.open(BASE+path,timeout=30) as response:
        return response.read()
def obj(path):return json.loads(get(path))
def main():
    from verify_accounts import service_password
    request=urllib.request.Request(BASE+"/api/login",data=json.dumps({"username":"videostudy_app","password":service_password()}).encode(),headers={"Content-Type":"application/json"})
    with BROWSER.open(request,timeout=20) as response: assert json.loads(response.read())["ok"]
    health=obj("/api/health")
    assert health["role"]=="videostudy_app" and health["read_only"] is True,health
    overview=obj("/api/overview")
    assert (overview["cases"],overview["skills"],overview["versions"],overview["artifacts"])==(16,6,18,160)
    schema=obj("/api/schema")
    assert {x["table_name"] for x in schema}=={"imports","videos","cases","skill_versions","artifacts","analysis_runs","operation_graph_versions","reviews"}
    count=0;cases=obj("/api/cases")
    for c in cases:
        data=obj("/api/cases/"+c["id"])
        source=next((ROOT/"output/current/knowledge_all_16/cases").glob(c["id"]+"*/result.json")).parent
        for a in data["artifacts"]:
            raw=get("/case-assets/"+c["id"]+"/"+a["filename"])
            assert hashlib.sha256(raw).hexdigest()==a["sha256"]
            assert raw==(source/a["filename"]).read_bytes()
            count+=1
    knowledge=0
    for skill in obj("/api/skills"):
        for v in skill["history"]:
            payload=obj("/api/skills/"+skill["skill_id"]+"?version="+v["version"])
            source=ROOT/"knowledge_base/versions"/skill["skill_id"]/(v["version"]+".json")
            assert payload==json.loads(source.read_text())
            knowledge+=1
    for table in ["imports","videos","cases","skill_versions","artifacts","analysis_runs","operation_graph_versions","reviews"]:
        data=obj("/api/tables/"+table)
        assert data
        if table=="cases":assert len(data)==16
    for path,expected in [("/api/tables/pg_authid",404),("/api/skills/skill_grasp_object?version=invalid",400),("/case-assets/01/pg_hba.conf",404)]:
        try:get(path);raise AssertionError(path)
        except urllib.error.HTTPError as e:assert e.code==expected
    privileges=query("""SELECT json_build_object(
    'select',has_table_privilege(current_user,'preview.cases','SELECT'),
    'insert',has_table_privilege(current_user,'preview.cases','INSERT'),
    'update',has_table_privilege(current_user,'preview.cases','UPDATE'),
    'delete',has_table_privilege(current_user,'preview.cases','DELETE'));""")
    assert privileges=={"select":True,"insert":True,"update":True,"delete":True}
    snapshot=ROOT/"archive/maintenance/cleanup_20261112.json"
    preserved=0
    if snapshot.exists():
        for row in json.loads(snapshot.read_text())["retained_evidence"]:
            assert hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest()==row["sha256"],row["path"]
            preserved+=1
    report={"health":health,"artifacts_roundtrip_verified":count,"knowledge_versions_verified":knowledge,"source_evidence_hashes_verified":preserved,"project_account_privileges":privileges,"proposed_tables":len(obj("/schema-proposal.json")),"visual_qa":"Not completed: built-in browser control timed out twice. HTTP, database and source-byte verification passed."}
    (RUNTIME/"verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()

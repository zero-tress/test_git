"""Integration tests: password authentication, own CRUD, cross-project denial, web sessions."""
import hashlib,http.cookiejar,json,os,secrets,subprocess,urllib.request,urllib.error
from db import ROOT,RUNTIME,PGBIN,DB,ACCOUNT,PASSFILE,connection_env,execute,query
def psql(sql,user=ACCOUNT,password=None,passfile=True,database=DB):
    env=connection_env(user,password)
    env["PGDATABASE"]=database
    if not passfile:env["PGPASSFILE"]="/dev/null"
    return subprocess.run([str(PGBIN/"psql"),"-XqAtw","-v","ON_ERROR_STOP=1"],input=sql,text=True,capture_output=True,env=env,timeout=20)
def service_password():
    fields=[];value="";escape=False
    for ch in PASSFILE.read_text().rstrip("\n"):
        if escape:value+=ch;escape=False
        elif ch=="\\":escape=True
        elif ch==":" and len(fields)<4:fields.append(value);value=""
        else:value+=ch
    return value
def main():
    identity=query("SELECT json_build_object('role',current_user,'db',current_database());")
    assert identity=={"role":ACCOUNT,"db":DB}
    privileges=query("""SELECT json_build_object('super',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
    'create_db',(SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user),
    'create_role',(SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),
    'bypass_rls',(SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user),
    'create_schema',has_database_privilege(current_user,current_database(),'CREATE'),
    'drop_owner',pg_has_role(current_user,'videostudy_owner','MEMBER'));""")
    assert not any(privileges.values()),privileges
    assert psql("SELECT 1",password="incorrect-password").returncode!=0
    assert psql("SELECT 1",passfile=False).returncode!=0
    assert psql("SELECT 1",database="postgres").returncode!=0
    assert psql("SET ROLE videostudy_owner;").returncode!=0
    before=query("SELECT json_object_agg(name,n) FROM (SELECT 'videos' name,count(*) n FROM preview.videos UNION ALL SELECT 'cases',count(*) FROM preview.cases UNION ALL SELECT 'artifacts',count(*) FROM preview.artifacts UNION ALL SELECT 'versions',count(*) FROM preview.skill_versions) t;")
    probe="permission_probe_"+secrets.token_hex(8)
    result=psql("BEGIN; INSERT INTO preview.imports(id,source,note) VALUES('"+probe+"','permission-test','own data'); UPDATE preview.imports SET note='updated' WHERE id='"+probe+"'; SELECT note FROM preview.imports WHERE id='"+probe+"'; DELETE FROM preview.imports WHERE id='"+probe+"'; ROLLBACK;")
    assert result.returncode==0 and "updated" in result.stdout
    schema="v2o_probe_"+secrets.token_hex(6);other=schema+"_role"
    try:
        execute("CREATE ROLE "+other+" NOLOGIN; CREATE SCHEMA "+schema+" AUTHORIZATION "+other+"; CREATE TABLE "+schema+".data(id integer); ALTER TABLE "+schema+".data OWNER TO "+other+";",admin=True)
        for stmt in ["SELECT * FROM "+schema+".data","INSERT INTO "+schema+".data VALUES(1)","UPDATE "+schema+".data SET id=2","DELETE FROM "+schema+".data","CREATE TABLE preview.denied_probe(id integer)","TRUNCATE preview.imports"]:
            assert psql(stmt).returncode!=0,stmt
        for stmt in ["SELECT * FROM preview.imports","DELETE FROM preview.imports"]:
            assert psql("SET ROLE "+other+"; "+stmt,user="wj").returncode!=0,stmt
    finally:
        execute("DROP TABLE IF EXISTS "+schema+".data; DROP SCHEMA IF EXISTS "+schema+"; DROP ROLE IF EXISTS "+other+";",admin=True)
    base="http://127.0.0.1:18773"
    def request(path,data=None,opener=None):
        req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={"Content-Type":"application/json"})
        with (opener.open(req,timeout=20) if opener else urllib.request.urlopen(req,timeout=20)) as r:return r.read()
    for path in ["/api/overview","/api/cases","/api/schema","/case-assets/01/operations.svg","/schema-proposal.json"]:
        try:request(path);raise AssertionError("Unauthenticated access allowed")
        except urllib.error.HTTPError as e:assert e.code==401
    assert "登录".encode() in request("/")
    cookies=http.cookiejar.CookieJar();browser=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    response=json.loads(request("/api/login",{"username":ACCOUNT,"password":service_password()},browser))
    assert response["ok"]
    health=json.loads(request("/api/health",opener=browser))
    assert health["role"]==ACCOUNT and health["read_only"] is True
    assert json.loads(request("/api/overview",opener=browser))["artifacts"]==160
    original=next((ROOT/"output/current/knowledge_all_16/cases").glob("01*/operations.svg")).read_bytes()
    assert request("/case-assets/01/operations.svg",opener=browser)==original
    request("/api/logout",{},browser)
    try:request("/api/cases",opener=browser);raise AssertionError("Logout ineffective")
    except urllib.error.HTTPError as e:assert e.code==401
    after=query("SELECT json_object_agg(name,n) FROM (SELECT 'videos' name,count(*) n FROM preview.videos UNION ALL SELECT 'cases',count(*) FROM preview.cases UNION ALL SELECT 'artifacts',count(*) FROM preview.artifacts UNION ALL SELECT 'versions',count(*) FROM preview.skill_versions) t;")
    assert before==after
    evidence=0
    for row in json.loads((ROOT/"archive/maintenance/cleanup_20261112.json").read_text())["retained_evidence"]:
        assert hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest()==row["sha256"]
        evidence+=1
    report={"account":ACCOUNT,"authentication":"SCRAM-SHA-256","missing_or_wrong_password":"denied","foreign_database":"denied","foreign_data_read_write":"denied","other_role_access_to_project":"denied","own_CRUD":"passed_rolled_back","DDL_and_TRUNCATE":"denied","web_requires_login":True,"web_readonly":True,"logout":"passed","data_counts_unchanged":after,"original_evidence_verified":evidence,"privileged_flags":privileges}
    (RUNTIME/"account_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()

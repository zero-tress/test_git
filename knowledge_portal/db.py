"""Project-only PostgreSQL adapter. Daily access never defaults to an administrator."""
from pathlib import Path
import contextvars, json, os, subprocess
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "knowledge_portal"
PGBIN = Path("/usr/lib/postgresql/18/bin")
DB = "videostudy_preview"
ACCOUNT = "videostudy_app"
PASSFILE = RUNTIME / "project.pgpass"
_credentials = contextvars.ContextVar("project_credentials", default=None)
_readonly = contextvars.ContextVar("project_readonly", default=False)
def sql_text(value):
    return "convert_from(decode('" + str(value).encode().hex() + "','hex'),'UTF8')"
def json_sql(value):
    return sql_text(json.dumps(value, ensure_ascii=False)) + "::jsonb"
def connection_env(user=ACCOUNT, password=None, readonly=False, database=DB):
    if database != DB: raise ValueError("Only this project's database is allowed")
    if user not in {ACCOUNT,"wj"}: raise ValueError("Unknown project role")
    env={key:value for key,value in os.environ.items() if not key.startswith("PG")}
    env.update(PGHOST=str(RUNTIME/"socket"),PGPORT="55432",PGUSER=user,PGDATABASE=DB,PGCONNECT_TIMEOUT="5",
             PGOPTIONS="-c statement_timeout=20000 -c search_path=preview,pg_catalog" + (" -c default_transaction_read_only=on" if readonly else ""))
    env.pop("PGPASSWORD",None)
    env["PGPASSFILE"]=str(PASSFILE)
    if password is not None: env["PGPASSWORD"]=password
    return env
def execute(sql, *, admin=False):
    credentials=_credentials.get()
    user,password=("wj",None) if admin else (credentials if credentials else (ACCOUNT,None))
    proc=subprocess.run([str(PGBIN/"psql"),"-X","-q","-A","-t","-w","-v","ON_ERROR_STOP=1"],input=sql,text=True,capture_output=True,
                        env=connection_env(user,password,_readonly.get() and not admin),timeout=40)
    if proc.returncode: raise RuntimeError("PostgreSQL operation refused or unavailable")
    return proc.stdout.strip()
def query(sql, *, admin=False):
    value=execute(sql,admin=admin)
    return json.loads(value) if value else None

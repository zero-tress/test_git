"""Provision project-only access. Never output database passwords."""
from pathlib import Path
import base64, hashlib, hmac, json, os, secrets, subprocess, tempfile
from db import ROOT,RUNTIME,PGBIN,DB,ACCOUNT,PASSFILE,execute,sql_text
OWNER="videostudy_owner"
def verifier(password):
    salt=secrets.token_bytes(16);salted=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,4096)
    client=hmac.new(salted,b"Client Key","sha256").digest()
    stored=hashlib.sha256(client).digest();server=hmac.new(salted,b"Server Key","sha256").digest()
    b64=lambda x:base64.b64encode(x).decode()
    return "SCRAM-SHA-256$4096:"+b64(salt)+"$"+b64(stored)+":"+b64(server)
def private_write(path,data):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".secret-")
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
def save_password(password):
    # PostgreSQL receives only a SCRAM verifier, never plaintext in SQL/logs.
    scram=verifier(password)
    execute("ALTER ROLE videostudy_app PASSWORD '"+scram+"';",admin=True)
    escape=lambda x:x.replace("\\","\\\\").replace(":","\\:")
    private_write(PASSFILE,":".join(map(escape,[str(RUNTIME/"socket"),"55432",DB,ACCOUNT,password]))+"\n")
def provision():
    RUNTIME.mkdir(parents=True,exist_ok=True);RUNTIME.chmod(0o700)
    identity=execute("SELECT current_database() || ':' || current_user;",admin=True)
    if identity != DB+":wj":raise RuntimeError("Not the expected isolated database")
    roles=json.loads(execute("SELECT coalesce(json_agg(rolname),'[]') FROM pg_roles WHERE rolname NOT LIKE 'pg_%';",admin=True))
    if set(roles)-{"wj","preview_reader",OWNER,ACCOUNT}:
        raise RuntimeError("Unexpected roles; refusing automatic privilege changes")
    execute("""BEGIN;
    DO $$ BEGIN
      IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='videostudy_owner') THEN CREATE ROLE videostudy_owner NOLOGIN; END IF;
      IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='videostudy_app') THEN CREATE ROLE videostudy_app LOGIN; END IF;
    END $$;
    ALTER ROLE videostudy_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8;
    ALTER ROLE preview_reader NOLOGIN;
    REVOKE ALL ON DATABASE videostudy_preview FROM PUBLIC,preview_reader;
    GRANT CONNECT ON DATABASE videostudy_preview TO videostudy_app;
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    ALTER SCHEMA preview OWNER TO videostudy_owner;
    REVOKE ALL ON SCHEMA preview FROM PUBLIC,preview_reader;
    GRANT USAGE ON SCHEMA preview TO videostudy_app;
    DO $$ DECLARE t record; BEGIN FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='preview'
      LOOP EXECUTE format('ALTER TABLE preview.%I OWNER TO videostudy_owner',t.tablename); END LOOP; END $$;
    REVOKE ALL ON ALL TABLES IN SCHEMA preview FROM PUBLIC,preview_reader;
    GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA preview TO videostudy_app;
    GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA preview TO videostudy_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE videostudy_owner IN SCHEMA preview REVOKE ALL ON TABLES FROM PUBLIC;
    ALTER DEFAULT PRIVILEGES FOR ROLE videostudy_owner IN SCHEMA preview GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO videostudy_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE wj IN SCHEMA preview GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO videostudy_app;
    ALTER ROLE videostudy_app IN DATABASE videostudy_preview SET search_path=preview,pg_catalog;
    COMMIT;""",admin=True)
    if not PASSFILE.exists():save_password(secrets.token_urlsafe(36))
    hba=RUNTIME/"pgdata/pg_hba.conf"
    backup=RUNTIME/"pg_hba.before_accounts.conf"
    if not backup.exists():private_write(backup,hba.read_text())
    private_write(hba,"""# Only this isolated project cluster. No passwordless application login.
local all wj peer
local videostudy_preview videostudy_app scram-sha-256
local all all reject
host all all 0.0.0.0/0 reject
host all all ::0/0 reject
""")
    execute("SELECT pg_reload_conf();",admin=True)
    error=execute("SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;",admin=True)
    if error!="0":raise RuntimeError("Invalid project HBA rules")
    setup=RUNTIME/"setup.json"
    if not setup.exists():
        token=secrets.token_urlsafe(32)
        private_write(setup,json.dumps({"token_hash":hashlib.sha256(token.encode()).hexdigest(),"used":False}))
        private_write(RUNTIME/"setup-link.txt","http://192.168.137.102:18773/setup#"+token+"\n")
    print(json.dumps({"account":ACCOUNT,"database":DB,"schema":"preview","authentication":"SCRAM-SHA-256","password":"not displayed","setup_link_file":str(RUNTIME/"setup-link.txt")}))
if __name__=="__main__":provision()

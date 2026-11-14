"""Manage only the isolated knowledge preview, without sudo or system service changes."""
from pathlib import Path
import argparse, json, os, signal, socket, subprocess, sys, time
from db import ROOT, RUNTIME, PGBIN, DB, execute
def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv],check=True,**kwargs)
def start():
    RUNTIME.mkdir(parents=True,exist_ok=True);RUNTIME.chmod(0o700)
    sock=RUNTIME/"socket";sock.mkdir(exist_ok=True);sock.chmod(0o700)
    data=RUNTIME/"pgdata"
    if not (data/"PG_VERSION").exists():
        run([PGBIN/"initdb","-D",data,"-U","wj","--encoding=UTF8","--locale=C.UTF-8","--auth-local=trust","--auth-host=reject","--wal-segsize=1"],stdout=subprocess.DEVNULL)
        with (data/"postgresql.conf").open("a") as f:
            f.write("\n# Isolated knowledge preview; no TCP database listener.\nlisten_addresses = ''\nport = 55432\nunix_socket_directories = '"+str(sock)+"'\nunix_socket_permissions = 0700\nshared_buffers = 32MB\nmax_connections = 12\nmax_wal_size = 128MB\nmin_wal_size = 16MB\n")
    status=subprocess.run([str(PGBIN/"pg_ctl"),"-D",str(data),"status"],capture_output=True)
    if status.returncode:
        run([PGBIN/"pg_ctl","-D",data,"-l",RUNTIME/"postgres.log","-w","start"],stdout=subprocess.DEVNULL)
    env=dict(os.environ,PGHOST=str(sock),PGPORT="55432",PGUSER="wj",PGDATABASE="postgres")
    found=subprocess.check_output([str(PGBIN/"psql"),"-XAt","-c","SELECT 1 FROM pg_database WHERE datname='videostudy_preview'"],env=env,text=True).strip()
    if not found:run([PGBIN/"createdb",DB],env=env)
    if execute("SELECT to_regclass('preview.imports') IS NOT NULL;",admin=True) != "t":
        raise RuntimeError("Preview tables absent; explicit authorized schema maintenance is required")
    # Account provisioning is an explicit maintenance operation, never re-grant the old reader.
    if not (RUNTIME/"project.pgpass").exists():
        raise RuntimeError("Run account.py to provision project authentication")
    pidfile=RUNTIME/"web.pid"
    if pidfile.exists():
        pid=int(pidfile.read_text())
        try:
            cmd=Path(f"/proc/{pid}/cmdline").read_bytes()
            if str(Path(__file__).parent/"server.py").encode() in cmd:
                print(json.dumps({"status":"already_running","url":"http://192.168.137.102:18773"},ensure_ascii=False));return
        except FileNotFoundError:pass
    test=socket.socket()
    test.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:test.bind(("0.0.0.0",18773))
    finally:test.close()
    log=(RUNTIME/"web.log").open("ab",buffering=0)
    proc=subprocess.Popen([sys.executable,"-B",str(Path(__file__).parent/"server.py")],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,cwd=ROOT,env=dict(os.environ))
    pidfile.write_text(str(proc.pid))
    print(json.dumps({"status":"started","url":"http://192.168.137.102:18773","database":DB,"schema":"preview","web_pid":proc.pid},ensure_ascii=False))
def status():
    execute("SELECT 1;")
    print(json.dumps({"database":"ready","web_pid":(RUNTIME/"web.pid").read_text().strip()},ensure_ascii=False))
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("action",choices=["start","status","restart-web"])
    args=ap.parse_args()
    if args.action=="restart-web":
        pidfile=RUNTIME/"web.pid"
        if pidfile.exists():
            pid=int(pidfile.read_text())
            cmd=Path(f"/proc/{pid}/cmdline").read_bytes()
            if str(Path(__file__).parent/"server.py").encode() not in cmd:
                raise RuntimeError("PID does not belong to this preview")
            os.kill(pid,signal.SIGTERM)
            for _ in range(30):
                if not Path(f"/proc/{pid}").exists():break
                try:
                    if Path(f"/proc/{pid}/stat").read_text().split()[2]=="Z":break
                except FileNotFoundError:break
                time.sleep(.1)
            pidfile.unlink()
        start()
    else:
        start() if args.action=="start" else status()

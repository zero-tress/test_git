"""Read-only LAN preview of provisional PostgreSQL knowledge records."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
import json, re, ipaddress
from db import ROOT, query, sql_text, _credentials, _readonly
import auth
import video_http
WEB = Path(__file__).parent / "web"
TABLES = {"imports","videos","cases","skill_versions","artifacts","analysis_runs","operation_graph_versions","reviews"}
def rows(sql):
    return query("SELECT coalesce(json_agg(q),'[]'::json) FROM (" + sql + ") q;")
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, value, mime="application/json; charset=utf-8", status=200, raw=False, headers=None):
        data = value if raw else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        if mime.startswith("text/html") and self.path.startswith("/case-assets/"):
            self.send_header("Content-Security-Policy","sandbox allow-scripts; default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'")
        for key,value in (headers or {}).items(): self.send_header(key,value)
        self.end_headers()
        if not getattr(self,"_head_only",False): self.wfile.write(data)
    def do_POST(self):
        try:
            if not (ipaddress.ip_address(self.client_address[0]).is_loopback or ipaddress.ip_address(self.client_address[0]) in ipaddress.ip_network("192.168.137.0/24")):
                return self.send({"error":"请从指定局域网或VS Code端口转发登录"},status=403)
            return auth.handle_post(self,urlsplit(self.path).path)
        except Exception:
            return self.send({"error":"账号验证暂时不可用"},status=400)
    def do_HEAD(self):
        self._head_only=True
        if re.fullmatch(r"/api/cases/\d{2}/video/(original|playback)",urlsplit(self.path).path):
            return self.do_GET()
        self.send_response(405);self.end_headers()
    def do_GET(self):
        try:
            addr=ipaddress.ip_address(self.client_address[0])
            if not (addr.is_loopback or addr in ipaddress.ip_network("192.168.137.0/24")):
                return self.send({"error":"仅供本机和指定局域网访问"},status=403)
            parsed=urlsplit(self.path);path=unquote(parsed.path);args=parse_qs(parsed.query)
            if path=="/auth.js":
                return self.send((WEB/"auth.js").read_bytes(),"application/javascript; charset=utf-8",raw=True)
            if path=="/setup":
                return self.send(auth.page(auth.setup_available()),"text/html; charset=utf-8",raw=True)
            if path=="/login":
                return self.send(auth.page(),"text/html; charset=utf-8",raw=True)
            credentials=auth.session(self)
            if not credentials:
                if path=="/":
                    return self.send(auth.page(),"text/html; charset=utf-8",raw=True)
                return self.send({"error":"请先验证项目账号","login_required":True},status=401)
            _credentials.set(credentials)
            _readonly.set(True)
            if path=="/api/session":
                return self.send({"account":credentials[0],"scope":"videostudy_preview.preview"})

            if path in {"/","/app.js","/style.css","/schema-proposal.json","/schema-review.json"}:
                file=WEB/({"/":"index.html"}.get(path,path[1:]))
                mime={".html":"text/html; charset=utf-8",".js":"application/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".json":"application/json; charset=utf-8"}[file.suffix]
                return self.send(file.read_bytes(),mime,raw=True)
            if path=="/api/health":
                return self.send(query("SELECT json_build_object('database',current_database(),'postgres_version',current_setting('server_version'),'status','ok','read_only',current_setting('transaction_read_only')::boolean,'role',current_user,'schema','preview');"))
            if path=="/api/overview":
                return self.send(query("""SELECT json_build_object(
                'videos',(SELECT count(*) FROM preview.videos),
                'cases',(SELECT count(*) FROM preview.cases),
                'skills',(SELECT count(DISTINCT skill_id) FROM preview.skill_versions),
                'versions',(SELECT count(*) FROM preview.skill_versions),
                'artifacts',(SELECT count(*) FROM preview.artifacts),
                'stored_bytes',(SELECT sum(byte_size) FROM preview.artifacts),
                'original_videos',(SELECT count(*) FROM preview.videos WHERE content IS NOT NULL),
                'video_bytes',(SELECT sum(byte_size) FROM preview.videos),
                'playback_bytes',(SELECT sum(playback_bytes) FROM preview.videos),
                'analysis_runs',(SELECT count(*) FROM preview.analysis_runs),
                'graph_versions',(SELECT count(*) FROM preview.operation_graph_versions),
                'schema_review_records',(SELECT count(*) FROM preview.reviews),
                'outcomes',(SELECT json_object_agg(outcome,n) FROM (SELECT outcome,count(*) n FROM preview.cases GROUP BY outcome) o),
                'postgres_version',current_setting('server_version'),
                'import',(SELECT row_to_json(i) FROM preview.imports i LIMIT 1));"""))
            if path=="/api/cases":
                return self.send(rows("SELECT c.id,c.title,c.outcome,c.node_count,v.metadata->>'方法' method,v.metadata->>'物体' object FROM preview.cases c JOIN preview.videos v ON c.video_id=v.id ORDER BY c.id"))
            video_match=re.fullmatch(r"/api/cases/(\d{2})/video/(original|playback)",path)
            if video_match:
                return video_http.serve(self,video_match[1],video_match[2],head=getattr(self,"_head_only",False),download=args.get("download",["0"])[0]=="1")
            if re.fullmatch(r"/api/cases/\d{2}",path):
                cid=sql_text(path.rsplit("/",1)[1])
                result=query("SELECT row_to_json(q) FROM (SELECT c.*,v.metadata FROM preview.cases c JOIN preview.videos v ON c.video_id=v.id WHERE c.id="+cid+") q;")
                if not result:return self.send({"error":"未找到案例"},status=404)
                result["video"]=query("SELECT json_build_object('filename',v.original_filename,'mime_type',v.mime_type,'bytes',v.byte_size,'sha256',v.sha256,'playback_bytes',v.playback_bytes,'playback_sha256',v.playback_sha256,'playback_codec',v.playback_metadata->>'codec','source_uri',v.source_uri,'split',v.split) FROM preview.videos v WHERE v.id="+sql_text(result["video_id"])+";")
                result["artifacts"]=rows("SELECT id,filename,mime_type,sha256,byte_size FROM preview.artifacts WHERE case_id="+cid+" ORDER BY filename")
                return self.send(result)
            if path=="/api/skills":
                return self.send(rows("""SELECT skill_id,max(name) name,count(*) versions,
                json_agg(json_build_object('version',version,'status',verification_status,'instances',jsonb_array_length(payload->'skill'->'provenance'),'realizations',jsonb_array_length(payload->'skill'->'R')) ORDER BY version) history
                FROM preview.skill_versions GROUP BY skill_id ORDER BY name"""))
            if path.startswith("/api/skills/"):
                sid=sql_text(path.rsplit("/",1)[1]);version=args.get("version",[""])[0]
                if not re.fullmatch("[a-f0-9]{64}",version):return self.send({"error":"请选择明确版本"},status=400)
                result=query("SELECT payload FROM preview.skill_versions WHERE skill_id="+sid+" AND version="+sql_text(version)+";")
                return self.send(result or {"error":"版本不存在"},status=200 if result else 404)
            if path=="/api/schema":
                return self.send(rows("""SELECT table_name,column_name,data_type,is_nullable,ordinal_position
                FROM information_schema.columns WHERE table_schema='preview' ORDER BY table_name,ordinal_position"""))
            if path.startswith("/api/tables/"):
                table=path.rsplit("/",1)[1]
                if table not in TABLES:return self.send({"error":"未知预览表"},status=404)
                selects={
                 "imports":"SELECT * FROM preview.imports",
                 "videos":"SELECT id,sha256,title,source_uri,split,original_filename,mime_type,byte_size,playback_bytes,metadata FROM preview.videos ORDER BY id",
                 "cases":"SELECT id,video_id,title,outcome,node_count,jsonb_typeof(graph) graph_type FROM preview.cases ORDER BY id",
                 "skill_versions":"SELECT skill_id,version,name,verification_status FROM preview.skill_versions ORDER BY skill_id,version",
                 "artifacts":"SELECT id,case_id,graph_version_id,filename,mime_type,sha256,byte_size,renderer_version,dependencies FROM preview.artifacts ORDER BY case_id,filename",
                 "analysis_runs":"SELECT id,video_id,source_case_id,code_version,model,prompt_version,status,created_at FROM preview.analysis_runs ORDER BY source_case_id",
                 "operation_graph_versions":"SELECT id,run_id,parent_version_id,semantic_hash,verification_status FROM preview.operation_graph_versions ORDER BY id",
                 "reviews":"SELECT * FROM preview.reviews ORDER BY subject_id"}
                return self.send(rows(selects[table]+" LIMIT 100"))
            if path.startswith("/case-assets/"):
                parts=path.split("/")
                if len(parts)!=4 or not re.fullmatch(r"\d{2}",parts[2]):return self.send({"error":"未知资源"},status=404)
                result=query("SELECT json_build_object('mime',mime_type,'hex',encode(content,'hex')) FROM preview.artifacts WHERE case_id="+sql_text(parts[2])+" AND filename="+sql_text(parts[3])+";")
                if not result:return self.send({"error":"资源不存在"},status=404)
                return self.send(bytes.fromhex(result["hex"]),result["mime"],raw=True)
            return self.send({"error":"未找到页面"},status=404)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception:
            return self.send({"error":"数据库读取失败，请检查服务日志"},status=500)
if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("--host",default="0.0.0.0");ap.add_argument("--port",type=int,default=18773)
    args=ap.parse_args()
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()

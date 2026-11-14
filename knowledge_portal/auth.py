"""Project password login verified by PostgreSQL; sessions stay in memory."""
import hashlib,hmac,json,secrets,threading,time
from http.cookies import SimpleCookie
from db import ACCOUNT,RUNTIME,query,_credentials
LOCK=threading.Lock();SESSIONS={};FAILURES={}
TTL=8*3600
def setup_available():
    p=RUNTIME/"setup.json"
    return p.exists() and not json.loads(p.read_text()).get("used",True)
def session(handler):
    try:
        cookie=SimpleCookie();cookie.load(handler.headers.get("Cookie",""))
        token=cookie["v2o_session"].value
        with LOCK:
            key=hashlib.sha256(token.encode()).hexdigest();value=SESSIONS.get(key)
            if value and value[2]>time.time():return value[:2]
            SESSIONS.pop(key,None)
    except (KeyError,ValueError):pass
    return None
def issue(handler,password):
    token=secrets.token_urlsafe(32)
    with LOCK:
        now=time.time()
        for key,value in list(SESSIONS.items()):
            if value[2]<=now:SESSIONS.pop(key,None)
        SESSIONS[hashlib.sha256(token.encode()).hexdigest()]=(ACCOUNT,password,now+TTL)
    handler.send({"ok":True,"account":ACCOUNT},headers={"Set-Cookie":"v2o_session="+token+"; HttpOnly; SameSite=Strict; Path=/; Max-Age="+str(TTL)})
def handle_post(handler,path):
    origin=handler.headers.get("Origin")
    if origin and origin != "http://"+handler.headers.get("Host",""):
        return handler.send({"error":"请求来源不匹配"},status=403)
    length=int(handler.headers.get("Content-Length","0"))
    if not 0<length<=4096:return handler.send({"error":"请求格式错误"},status=400)
    data=json.loads(handler.rfile.read(length))
    if path=="/api/logout":
        cookie=SimpleCookie();cookie.load(handler.headers.get("Cookie",""))
        if "v2o_session" in cookie:
            with LOCK:SESSIONS.pop(hashlib.sha256(cookie["v2o_session"].value.encode()).hexdigest(),None)
        return handler.send({"ok":True},headers={"Set-Cookie":"v2o_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
    if path not in {"/api/login","/api/setup"}:return handler.send({"error":"未提供写入接口"},status=404)
    now=time.time();ip=handler.client_address[0]
    with LOCK:
        failures=[t for t in FAILURES.get(ip,[]) if t>now-300];FAILURES[ip]=failures
        if len(failures)>=10:return handler.send({"error":"尝试次数过多，请5分钟后重试"},status=429)
    user=data.get("username","");password=data.get("password","")
    if user!=ACCOUNT or not isinstance(password,str) or len(password)>128:
        return handler.send({"error":"账号或密码不正确"},status=401)
    if path=="/api/setup":
        if not (len(password)>=16 and password.isascii() and password.isprintable()):
            return handler.send({"error":"请使用至少16位ASCII字符的密码，可含大小写字母、数字和符号"},status=400)
        from account import private_write,save_password
        with LOCK:
            if not setup_available():return handler.send({"error":"一次性设置入口已失效"},status=403)
            entry=json.loads((RUNTIME/"setup.json").read_text())
            token=str(data.get("token",""))
            if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),entry["token_hash"]):
                FAILURES.setdefault(ip,[]).append(now)
                return handler.send({"error":"一次性设置凭证无效"},status=403)
            save_password(password)
            SESSIONS.clear()
            private_write(RUNTIME/"setup.json",json.dumps({"used":True,"used_at":now}))
            (RUNTIME/"setup-link.txt").unlink(missing_ok=True)
    ctx=_credentials.set((user,password))
    try:
        identity=query("SELECT json_build_object('role',current_user);")
        if identity["role"]!=ACCOUNT:raise RuntimeError()
    except Exception:
        with LOCK:FAILURES.setdefault(ip,[]).append(now)
        return handler.send({"error":"账号或密码不正确"},status=401)
    finally:_credentials.reset(ctx)
    return issue(handler,password)
def page(setup=False):
    mode="setup" if setup else "login"
    title="设置视频学习账号密码" if setup else "登录视频知识工作台"
    info="一次性设置入口。密码由你设置，不会在聊天或日志中显示。" if setup else "使用项目专属 PostgreSQL 账号。通过验证后才能查看知识和操作图。"
    return ("""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>"""+title+"""</title><style>
    *{box-sizing:border-box}body{margin:0;background:#13283b;color:#1b3246;font:14px/1.7 system-ui,"Microsoft YaHei",sans-serif;display:grid;place-items:center;min-height:100vh;padding:24px}main{background:#fff;border-radius:16px;padding:38px;max-width:480px;width:100%;box-shadow:0 24px 80px #0004}small{letter-spacing:2px;color:#6788a7;font-size:10px}h1{font-size:24px;margin:12px 0}p{color:#6e8092;font-size:13px}label{display:block;margin:20px 0 7px;font-size:12px}input,button{width:100%;padding:12px;border:1px solid #dce4ed;border-radius:7px;font:inherit}input[readonly]{background:#f1f5f9}button{background:#28649c;color:#fff;border:0;margin-top:25px;cursor:pointer}#message{color:#b65449;font-size:12px;min-height:20px}.foot{font-size:11px;margin-top:24px;border-top:1px solid #e8edf3;padding-top:18px}
    </style><main><small>VIDEO KNOWLEDGE · PROJECT ACCESS</small><h1>"""+title+"""</h1><p>"""+info+"""</p><form id="auth-form" data-mode="""+'"'+mode+'"'+"""><label for="username">项目账号</label><input id="username" value="videostudy_app" readonly autocomplete="username"><label for="password">密码"""+("（至少16位）" if setup else "")+"""</label><input id="password" type="password" required maxlength="128" autocomplete="""+('"new-password"' if setup else '"current-password"')+"""><button id="submit">"""+("设置密码并登录" if setup else "验证账号并登录")+"""</button><p id="message" role="alert"></p></form><p class="foot">仅访问视频学习项目的数据。可通过 VS Code 端口转发连接；网页不会提供删库或删表操作。</p></main><script src="/auth.js"></script></html>""").encode()

"""Authenticated PostgreSQL-backed MP4 delivery, including byte-range requests."""
import re
from urllib.parse import quote
from db import query,sql_text
def byte_range(header,size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r"bytes=(\d*)-(\d*)",header.strip())
    if not match or not any(match.groups()):raise ValueError("Invalid range")
    start,end=match.groups()
    if start:
        start=int(start);end=min(int(end),size-1) if end else size-1
    else:
        length=int(end)
        if length<=0:raise ValueError("Invalid suffix")
        start=max(size-length,0);end=size-1
    if start>=size or start>end:raise ValueError("Unsatisfiable range")
    return start,end,True
def serve(handler,cid,variant,head=False,download=False):
    if variant not in {"original","playback"}:
        return handler.send({"error":"未知视频格式"},status=404)
    column="content" if variant=="original" else "playback_content"
    sizefield="byte_size" if variant=="original" else "playback_bytes"
    hashfield="sha256" if variant=="original" else "playback_sha256"
    condition=" FROM preview.videos v JOIN preview.cases c ON c.video_id=v.id WHERE c.id="+sql_text(cid)
    meta=query("SELECT json_build_object('size',v."+sizefield+",'sha256',v."+hashfield+",'filename',v.original_filename)"+condition+";")
    if not meta or meta["size"] is None:return handler.send({"error":"视频尚未存入数据库"},status=404)
    size=meta["size"]
    try:start,end,partial=byte_range(handler.headers.get("Range"),size)
    except ValueError:return handler.send(b"","video/mp4",status=416,raw=True,headers={"Content-Range":"bytes */"+str(size),"Accept-Ranges":"bytes"})
    # If-Range only permits the stored, exact strong ETag. Otherwise send the entire version.
    etag='"'+meta["sha256"]+'"'
    if partial and handler.headers.get("If-Range") not in {None,etag}:
        start,end,partial=0,size-1,False
    headers={"Accept-Ranges":"bytes","ETag":etag}
    if partial:headers["Content-Range"]=f"bytes {start}-{end}/{size}"
    if download:
        filename=meta["filename"] if variant=="original" else "playback_"+meta["filename"]
        headers["Content-Disposition"]="attachment; filename=video_"+cid+".mp4; filename*=UTF-8''"+quote(filename)
    if head:
        handler.send_response(206 if partial else 200)
        for key,value in {"Content-Type":"video/mp4","Content-Length":str(end-start+1),"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",**headers}.items():handler.send_header(key,value)
        handler.end_headers();return
    data=query("SELECT json_build_object('hex',encode(substring(v."+column+" FROM "+str(start+1)+" FOR "+str(end-start+1)+"),'hex'))"+condition+";")
    return handler.send(bytes.fromhex(data["hex"]),"video/mp4",status=206 if partial else 200,raw=True,headers=headers)

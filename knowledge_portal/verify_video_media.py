"""Verify authenticated MP4 bytes, Range/HEAD support, approval and frozen skills."""
import hashlib,http.cookiejar,json,subprocess,tempfile,urllib.request,urllib.error
from pathlib import Path
from db import ROOT,RUNTIME,query
from migrate_video_media import WORK,freeze
from verify_accounts import service_password
BASE="http://127.0.0.1:18773"
def main():
    anonymous=urllib.request.build_opener()
    jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def call(path,headers=None,method=None,data=None,browser=client):
        req=urllib.request.Request(BASE+path,headers=headers or {},method=method,data=json.dumps(data).encode() if data is not None else None)
        with browser.open(req,timeout=30) as response:return response.status,dict(response.headers),response.read()
    for method in ["GET","HEAD"]:
        try:call("/api/cases/01/video/original",method=method,browser=anonymous);raise AssertionError("Authentication missing")
        except urllib.error.HTTPError as e:assert e.code==401
    call("/api/login",headers={"Content-Type":"application/json"},data={"username":"videostudy_app","password":service_password()})
    cases=json.loads(call("/api/cases")[2])
    original_count=playback_count=0
    with tempfile.TemporaryDirectory(prefix="verify_mp4_",dir=RUNTIME) as tmp:
        for c in cases:
            cid=c["id"];case=json.loads(call("/api/cases/"+cid)[2]);v=case["video"]
            source=ROOT/v["source_uri"];raw=source.read_bytes()
            status,headers,body=call("/api/cases/"+cid+"/video/original")
            assert status==200 and body==raw and hashlib.sha256(body).hexdigest()==v["sha256"]
            assert headers["Content-Type"]=="video/mp4" and headers["Accept-Ranges"]=="bytes"
            original_count+=1
            status,headers,playback=call("/api/cases/"+cid+"/video/playback")
            assert status==200 and hashlib.sha256(playback).hexdigest()==v["playback_sha256"]
            f=Path(tmp)/(cid+".mp4");f.write_bytes(playback)
            probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(f)],text=True))
            video=next(s for s in probe["streams"] if s["codec_type"]=="video")
            assert video["codec_name"]=="h264" and video["pix_fmt"]=="yuv420p"
            subprocess.run(["ffmpeg","-nostdin","-v","error","-threads","1","-i",str(f),"-map","0:v:0","-f","null","-"],check=True,capture_output=True,timeout=20)
            expected=case["result"]["meta"]["duration"]
            assert abs(float(probe["format"]["duration"])-expected)<0.25
            playback_count+=1
        uri="/api/cases/01/video/playback";whole=call(uri)[2];size=len(whole)
        requests=[("bytes=0-99",0,99),("bytes=100-199",100,199),("bytes=-128",size-128,size-1),("bytes=100-",100,size-1),("bytes=0-999999999",0,size-1)]
        for value,start,end in requests:
            status,headers,chunk=call(uri,{"Range":value})
            assert status==206 and chunk==whole[start:end+1]
            assert headers["Content-Range"]==f"bytes {start}-{end}/{size}"
        status,headers,body=call(uri,method="HEAD")
        assert status==200 and body==b"" and int(headers["Content-Length"])==size
        status,headers,body=call(uri,{"Range":"bytes=20-29"},method="HEAD")
        assert status==206 and body==b"" and headers["Content-Length"]=="10"
        status,headers,body=call(uri,{"Range":"bytes=0-9","If-Range":'"old-version"'})
        assert status==200 and body==whole
        for value in ["bytes=-0","bytes=999999999-","bytes=10-1","bytes=0-1,3-4"]:
            try:call(uri,{"Range":value});raise AssertionError(value)
            except urllib.error.HTTPError as e:assert e.code==416 and e.headers["Content-Range"]=="bytes */"+str(size)
        status,headers,body=call("/api/cases/01/video/original?download=1")
        assert "attachment;" in headers["Content-Disposition"] and "filename*=UTF-8''" in headers["Content-Disposition"]
    for table,count in [("analysis_runs",16),("operation_graph_versions",16),("reviews",8)]:
        assert len(json.loads(call("/api/tables/"+table)[2]))==count
    review=json.loads(call("/schema-review.json")[2])
    assert len(review["notes"])==8 and all(n.strip()=="保留" for n in review["notes"].values())
    assert freeze()==json.loads((WORK/"before.json").read_text())
    privileges=query("""SELECT json_agg(q) FROM (SELECT table_name,has_table_privilege(current_user,'preview.'||table_name,'SELECT') can_read,has_table_privilege(current_user,'preview.'||table_name,'INSERT,UPDATE,DELETE') can_write FROM information_schema.tables WHERE table_schema='preview') q;""")
    assert all(p["can_read"] and p["can_write"] for p in privileges)
    result={"original_mp4_roundtrips":original_count,"playback_mp4_decoded":playback_count,"byte_range_tests":len(requests)+7,"authenticated_GET_HEAD":True,"original_download":True,"user_review_imported":8,"skill_database_learning_frontend_unchanged":True,"existing_artifacts":160}
    (RUNTIME/"video_media_verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()

"""Install the reviewed media integration; preserve existing entry points."""
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
backup = ROOT / "backups" / ("state_frames_integration_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
files = ["video2op/config.py", "video2op/llm.py", "video2op/media.py", "video2op/pipeline.py",
         "video2op/stages/s01_viewpoint.py", "video2op/stages/s02b_atomic.py"]
for name in files:
    dest = backup / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, dest)

def edit(name, old, new):
    p = ROOT / name
    s = p.read_text()
    assert old in s, (name, old[:70])
    p.write_text(s.replace(old, new, 1))

p = ROOT / "video2op/config.py"
p.write_text(p.read_text() + '''
# ---- 视频整体理解 + 关键状态帧 + 局部复查 ----
KEYFRAMES_ENABLED = os.environ.get("V2O_KEYFRAMES", "1") != "0"
KEYFRAME_CANDIDATE_FPS = 8.0
KEYFRAME_MAX_PER_WINDOW = 10
LOCAL_REVIEW_ENABLED = os.environ.get("V2O_LOCAL_REVIEW", "1") != "0"
LOCAL_REVIEW_MAX_WINDOWS = 3
LOCAL_REVIEW_MAX_SECONDS = 4.0
LOCAL_REVIEW_MAX_FRAMES = 10
LOCAL_REVIEW_FPS = 16
LOCAL_REVIEW_CONFIDENCE = 0.65
''')

edit("video2op/llm.py", '            video: Path | None = None, video_id: str = "",',
     '            video: Path | None = None, video_id: str = "",\n            images: list[dict] | None = None,')
edit("video2op/llm.py", '        has_video = video is not None',
     '        has_video = video is not None or bool(images)')
edit("video2op/llm.py",
'''        key = self._fingerprint(stage, system, user_text, vid_id, temperature, budget)''',
'''        image_inputs = []
        for image in images or []:
            path = Path(image["path"])
            data = path.read_bytes()
            label = (f'源视频帧 {image["frame_id"]}；全局时间 {image["timestamp"]:.6f}s。'
                     '选帧阶段不证明接触或动作；请读取画面。')
            vid_id += "#" + hashlib.sha256(data + label.encode()).hexdigest()
            image_inputs.append((data, label, "image/png" if path.suffix.lower() == ".png" else "image/jpeg"))
        key = self._fingerprint(stage, system, user_text, vid_id, temperature, budget)''')
edit("video2op/llm.py", '        content_parts.append({"type": "text", "text": user_text})',
'''        for data, label, mime in image_inputs:
            content_parts.append({"type": "text", "text": label})
            content_parts.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64," + base64.b64encode(data).decode()}})
        content_parts.append({"type": "text", "text": user_text})''')

edit("video2op/media.py", 'def make_clip(src: Path, start: float, dur: float, tag: str = "") -> Path:',
     'def make_clip(src: Path, start: float, dur: float, tag: str = "", *, fps: float | None = None) -> Path:')
edit("video2op/media.py", '    config.WORK_DIR.mkdir(parents=True, exist_ok=True)',
     '    fps = config.CLIP_FPS if fps is None else fps\n    config.WORK_DIR.mkdir(parents=True, exist_ok=True)')
edit("video2op/media.py", '{config.CLIP_WIDTH}|{config.CLIP_FPS}|', '{config.CLIP_WIDTH}|{fps}|')
edit("video2op/media.py", 'str(config.CLIP_FPS)', 'str(fps)')

edit("video2op/pipeline.py", '    reasoning,\n    semantic,',
     '    reasoning,\n    sampling,\n    local_review,\n    semantic,')
edit("video2op/pipeline.py", '    stage("s01_viewpoint",',
'''    stage("s00_state_frames", lambda: sampling.prepare(ctx), "sampling", {})
    stage("s01_viewpoint",''')
edit("video2op/pipeline.py", '    semantic.normalize_observations(ctx)\n    from . import arm_hand, grasp_preparation',
'''    semantic.normalize_observations(ctx)
    _dump(stages_dir / "s02b_before_review.json", {"atomic": ctx["atomic"], "relations": ctx["relations"]})
    stage("s02r_local_review", lambda: local_review.run(client, ctx), "local_review", {})
    _dump(stages_dir / "s02b_after_review.json", {"atomic": ctx["atomic"], "relations": ctx["relations"]})
    from . import arm_hand, grasp_preparation''')
edit("video2op/pipeline.py", '        "atomic": ctx.get("atomic") or {},',
'''        "sampling": ctx.get("sampling") or {},
        "local_review": ctx.get("local_review") or {},
        "atomic": ctx.get("atomic") or {},''')

edit("video2op/stages/s01_viewpoint.py", 'from .. import media', 'from .. import media, sampling')
edit("video2op/stages/s01_viewpoint.py", '        video=video, video_id=ctx["video_id"], validator=_validate,',
'''        video=video, video_id=ctx["video_id"], validator=_validate,
        images=sampling.frames_for_window(ctx.get("sampling") or {}, 0, meta["duration"], maximum=4),''')

edit("video2op/stages/s02b_atomic.py", 'from .. import media', 'from .. import media, sampling')
edit("video2op/stages/s02b_atomic.py", '        def validate(payload: object) -> None:',
'''        frames = sampling.frames_for_window(ctx.get("sampling") or {}, start, dur)
        if frames:
            user += ("\\n附带关键状态帧：图片标记为源视频全局时间，视频和动作start/end为片段局部时间。"
                     "请对照动作前后手形与物体支撑状态；运动候选不是动作事实。"
                     "不可见请明确说明，不要按前置条件补造打开、抓握或释放。")
        def validate(payload: object) -> None:''')
edit("video2op/stages/s02b_atomic.py", '            validator=validate,',
     '            validator=validate, images=frames,')
edit("video2op/stages/s02b_atomic.py", '        payload["window"] =',
'''        payload["input_frame_ids"] = [f["frame_id"] for f in frames]
        # These were sent to the model; input availability is not proof of an action.
        for action in payload["atomic_actions"]:
            action["input_frame_ids"] = payload["input_frame_ids"]
        payload["window"] =''')
print("Integration source backup:", backup)

from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "video2op/workbench.py"
dest = ROOT / "backups/state_frames_integration_20261022_080025/video2op/workbench.py"
shutil.copy2(p, dest)
s = p.read_text()
old = '''    # 操作 id → 契约 id（A1/H1/...）'''
new = '''    # Expose only case-local evidence images as portable relative links.
    from copy import deepcopy
    atomic = deepcopy(atomic)
    for a in atomic.values():
        frames = list(a.get("visual_evidence") or [])
        frames += [f for item in a.get("visual_state_evidence") or [] for f in item["frames"]]
        for frame in frames:
            try:
                frame["display_path"] = Path(frame["path"]).resolve().relative_to(case_dir.resolve()).as_posix()
            except ValueError:
                frame["display_path"] = ""
    sampling_doc = bundle.get("sampling") or {}
    gallery = ""
    if sampling_doc.get("directory"):
        try:
            gallery = (Path(sampling_doc["directory"]).resolve() / "index.html").relative_to(case_dir.resolve()).as_posix()
        except ValueError:
            pass
    review = bundle.get("local_review") or {}
    media_review = {"gallery": gallery, "sampling_status": sampling_doc.get("status"),
                    "reviewed": sum(p.get("status") == "reviewed" for p in review.get("proposals") or []),
                    "unresolved": sum(p.get("status") in {"failed", "skipped_budget"}
                                      for p in review.get("proposals") or []),
                    "conflicts": sum(len(r["applied"]["conflicts"]) for r in review.get("results") or [])}
    # 操作 id → 契约 id（A1/H1/...）'''
assert old in s
s = s.replace(old, new, 1)
s = s.replace('''        "case": case_dir.name,''','''        "case": case_dir.name,
        "media_review": media_review,''',1)
old = '''    if node["observed_effects"]:'''
new = '''        visual = list(a.get("visual_evidence") or [])
        for item in a.get("visual_state_evidence") or []:
            out.append(f'<div class="pv">局部复查：{e(item["state"])}（{e(item["field"])}）</div>')
            visual.extend(item["frames"])
        seen = set()
        for frame in visual:
            src = frame.get("display_path")
            if not src or frame["frame_id"] in seen:
                continue
            seen.add(frame["frame_id"])
            out.append(f'<figure><a target="_blank" href="{e(src)}"><img loading="lazy" '
                       f'src="{e(src)}" style="max-width:100%" alt="复查证据帧"></a>'
                       f'<figcaption>{e(frame["frame_id"])} · 源视频 {e(frame["timestamp"])} s</figcaption></figure>')
    if node["observed_effects"]:'''
assert old in s
s = s.replace(old, new, 1)
s = s.replace('''    details = []
    for node in data["nodes"]:''','''    media_review = data.get("media_review") or {}
    media_html = ""
    if media_review.get("gallery"):
        media_html = (f'<div class="figcap"><a href="{e(media_review["gallery"])}" target="_blank">'
                      '查看关键状态帧</a> · '
                      f'局部复查 {e(media_review["reviewed"])} 次，'
                      f'未完成 {e(media_review["unresolved"])} 项，'
                      f'证据冲突 {e(media_review["conflicts"])} 项。'
                      '关键帧选择不等于动作已被证实。</div>')
    details = []
    for node in data["nodes"]:''',1)
s = s.replace('''{timeline_html(data)}
<details class="fold-sec"><summary>校验与待复核</summary>''','''{media_html}
{timeline_html(data)}
<details class="fold-sec"><summary>校验与待复核</summary>''',1)
p.write_text(s)

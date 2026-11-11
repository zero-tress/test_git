"""Apply the release boundary and gate size correction, preserving source files."""
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "backups" / ("release_gate_sequence_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
FILES = ["video2op/single_actor.py", "video2op/render.py", "tests/test_single_actor_v4.py"]
for name in FILES:
    dst = BACKUP / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, dst)

p = ROOT / "video2op/single_actor.py"
s = p.read_text()
anchor = "    # Remove redundant actor-order edges so the only bypass line is the\n"
assert anchor in s
s = s.replace(anchor, '''    # Release and approach are exclusive semantic stages across actor boundaries.
    # Preserve their cycle order even when the video intervals overlap. Opening
    # may still run alongside the next approach after the previous release.
    boundaries = sorted(
        [n for n in nodes if n["name"] in {"释放", "靠近"}],
        key=lambda n: (n["_semantic_order"], n["id"]))
    for i, left in enumerate(boundaries):
        for right in boundaries[i + 1:]:
            if left["name"] != right["name"]:
                dep(left, right)
''' + anchor, 1)
p.write_text(s)

p = ROOT / "video2op/render.py"
s = p.read_text()
assert "GS_GATE_HW, GS_GATE_HH = 110, 68" in s
s = s.replace("GS_GATE_HW, GS_GATE_HH = 110, 68", "GS_GATE_HW, GS_GATE_HH = 82.5, 51")
s = s.replace('opacity: float = 0, path_d: str | None = None) -> None:',
              'opacity: float = 0, path_d: str | None = None,\n             visual_to: str | None = None) -> None:', 1)
old = '+ (f\' opacity="{opacity}"\' if opacity else "") + "/>")'
new = '+ (f\' data-visual-to="{esc(visual_to)}"\' if visual_to else "")\n                   + (f\' opacity="{opacity}"\' if opacity else "") + "/>")'
assert old in s
s = s.replace(old, new, 1)
old = '''            ax, ay = pos[f]
            bx, by = pos[t]
            lane_y = max(y for _, y in pos.values()) + GS_NODE_R + 34
            path = (f"M {ax:.1f},{ay + GS_NODE_R:.1f} V {lane_y:.1f} "
                    f"H {bx:.1f} V {by + GS_NODE_R:.1f}")
            draw(f, t, "hold", path_d=path)'''
new = '''            # The visible grip boundary is the gate immediately before release.
            # Keep data-to bound to the release event for the relation inspector.
            target_gate = next((str(g["id"]) for g in gates
                                if t in [str(n) for n in g.get("to") or []]), None)
            if target_gate not in pos:
                continue
            ax, ay = pos[f]
            bx, by = pos[target_gate]
            lane_y = max(y for _, y in pos.values()) + GS_NODE_R + 34
            path = (f"M {ax:.1f},{ay + GS_NODE_R:.1f} V {lane_y:.1f} "
                    f"H {bx:.1f} V {by + GS_GATE_HH:.1f}")
            draw(f, t, "hold", path_d=path, visual_to=target_gate)'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
print(BACKUP)

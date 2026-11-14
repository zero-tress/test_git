"""Remove only visible timing and coordination annotations from operations.svg."""
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
backup = root / "backups/operations_svg_20261012"
backup.mkdir(exist_ok=True)
source = root / "video2op/render.py"
shutil.copy2(source, backup / "render.py")
s = source.read_text()
s = s.replace('    svg = gate_svg(bundle)\n    path = out_dir / "operations.svg"',
              '    svg = gate_svg(bundle, show_node_details=False)\n    path = out_dir / "operations.svg"', 1)
s = s.replace('def gate_svg(bundle: dict, wrap_width: float | None = None) -> str:',
              'def gate_svg(bundle: dict, wrap_width: float | None = None, *,\n             show_node_details: bool = True) -> str:', 1)
s = s.replace('                if coord and not hold:', '                if show_node_details and coord and not hold:', 1)
start = s.index('                svg.append(f\'<text x="{cx:.1f}" y="{cy + 54:.1f}"')
end = s.index('                svg.append("</g>")', start)
s = s[:start] + '                if show_node_details:\n' + ''.join('    ' + line for line in s[start:end].splitlines(keepends=True)) + s[end:]
old_note = "节点内小字：蓝＝本步主动执行器，橙＝同步保持的执行器（谁在动、谁在保持）；七元组与证据在悬停详情、报告与工作台里。"
new_note = "七元组与证据在悬停详情、报告与工作台里。"
anchor = '    note2 = "' + old_note + '"\n'
assert anchor in s
s = s.replace(anchor, anchor + '    if not show_node_details:\n        note2 = "' + new_note + '"\n', 1)
compile(s, str(source), "exec")
source.write_text(s)

# Edit existing exports in place: do not recompute old semantic graphs or other artifacts.
count = 0
for path in sorted((root / "output").glob("*/operations.svg")):
    original = path.read_text()
    removed = [0]
    def simplify_node(match):
        node = match.group(0)
        def drop_annotation(m):
            removed[0] += 1
            return ""
        return re.sub(r'<text\b[^>]*font-size="(?:12\.5|14)"[^>]*>.*?</text>', drop_annotation, node, flags=re.S)
    updated = re.sub(r'<g class="gs-node"\b.*?</g>', simplify_node, original, flags=re.S)
    # class attribute ends with a quote; match its following whitespace or angle bracket.
    if updated == original:
        updated = re.sub(r'<g class="gs-node"[^>]*>.*?</g>', simplify_node, original, flags=re.S)
    updated = updated.replace(old_note, new_note)
    ET.fromstring(updated)
    # Every geometric element and attribute must remain byte-equivalent after removing text.
    def geometry(svg):
        tree = ET.fromstring(svg)
        return [(e.tag, dict(e.attrib)) for e in tree.iter() if e.tag.rsplit("}",1)[-1] not in {"text","tspan","title"}]
    assert geometry(original) == geometry(updated), str(path)
    if updated != original:
        dest = backup / path.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        path.write_text(updated)
        count += 1
    print(path.relative_to(root), "removed visible annotations:", removed[0])
print("Updated SVG files:", count)

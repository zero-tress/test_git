"""Record verified benchmark delivery; no model calls or source behavior changes."""
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
review = ROOT / "output/_operation_v2_review"
rows = []
for name in ["从冰箱取出蔬菜", "燕麦杯"]:
    folder = ROOT / "output" / (name + "_operation_v2")
    b = json.loads((folder / "benchmark.json").read_text())
    old = b["baseline"]["llm_stats"]["seconds"]
    new = b["current"]["llm_stats"]["seconds"]
    rows.append({"video": name, "old_llm_seconds": old, "new_llm_seconds": new,
                 "reduction_percent": round((1 - new / old) * 100, 2),
                 "new_full_wall_seconds": b["current"]["wall_seconds"],
                 "calls": b["current"]["llm_stats"]["calls"], "cache_hits": 0,
                 "failures": 0, "validation": b["validation"]})
summary = {"date": "2026-10-12", "model": "qwen3.8-27b", "endpoint": "http://127.0.0.1:8032",
           "comparisons": rows, "tests": "210 passed in 0.61s; remote conda study",
           "limitations": ["历史负载未控制，不能保证其他视频获得相同加速。",
                          "两例主要为第一人称上肢操作，不能替代全身走路/蹲起视频实测。",
                          "结构校验通过不代表每条视觉证据已被人工确认。"]}
(review / "final_comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
cup_review = {"status": "partial_visual_review", "checked_frames_seconds": [1,4,8,11.5,13.5,15],
              "assessment": "抽查支持接近、抓握、搬运、放置释放、收回的总体顺序；不是逐帧时间边界验证。",
              "open_findings": [{"atomic_id": 7, "time_range": [11,14],
                  "claim": "右臂保持抬起（inferred=true）",
                  "assessment": "放杯期间可能含下降放置动作，固定姿态先验不能代替画面证据；需进一步复核。",
                  "proposed_next_step": "确认后优化手臂放置动作识别及保持先验，当前保留推断标记，不改写观测。"}]}
(ROOT / "output/燕麦杯_operation_v2/quality_review.json").write_text(json.dumps(cup_review, ensure_ascii=False, indent=2) + "\n")
table = "| 视频 | 历史模型耗时 | 新模型耗时 | 减少 | 新版完整总耗时 |\n|---|---:|---:|---:|---:|\n"
for r in rows:
    table += f'| {r["video"]} | {r["old_llm_seconds"]:.1f} 秒 | {r["new_llm_seconds"]:.1f} 秒 | {r["reduction_percent"]:.1f}% | {r["new_full_wall_seconds"]:.1f} 秒 |\n'
section = """## 最终实测与待复核事项（2026-10-12）

两例均使用 8032 上的 qwen3.8-27b；每例 8 次模型调用、无缓存命中、无失败或重试。保留完整分析阶段。

""" + table + """
上述百分比比较模型请求累计时间；旧版总耗时不包含渲染，不能和新版完整总耗时直接计算加速比。历史服务器负载未控制，结果不保证适用于所有视频。详细数据见 output/_operation_v2_review/final_comparison.json 及每例 benchmark.json。

最终回归：服务器 conda study 环境 210 项测试通过。两例各 17 项结构检查，通过 16、提醒 1、失败 0；提醒涉及条件/证据完整性。操作语义扫描没有腰、腿、膝、脚等禁用人体部位。两个视频主要为第一人称上肢操作，全身行走和蹲起仍需另有真实视频验证；已有规则和合成测试不能代替该验证。

人工抽查保留的疑点：
- 冰箱：模型声称 5.2–5.67 秒左手接触门框；5.2、5.6 秒抽查帧未证实。保留原输出，未宣称该动作已人工确认。
- 燕麦杯：抽查支持总体取放顺序，但 11–14 秒被先验补成“右臂保持抬起”，可能混入下降放置动作。该条仍标 inferred=true，需要更细复核。
- 以上分别记录于两个新结果目录的 quality_review.json。是否增加视觉证据复核阶段、细化手臂放置与保持先验，待用户确认后实施；额外模型复核会增加耗时。

cloud_wj 当前连接已加载 network 参数，无须再为本次连接重连；默认关闭，授权的模型访问可用 network=true。未修改或重启 8032 模型服务。
"""
doc = ROOT / "优化说明_20261011.md"
s = doc.read_text().replace("尚未获得本次真实模型的速度/质量对比结果，不宣称具体加速倍数。",
    "已完成两例真实模型对比，模型耗时分别减少约 21% 和 31%，细节与质量限制见末尾实测章节。")
s = s.replace("当前聊天已经加载的旧连接需重连才显示新参数；本次实测使用新版 MCP 协议连接。",
              "当前连接已加载新参数；实测通过新版 MCP 协议连接完成。")
doc.write_text(s + "\n" + section)
readme = ROOT / "README.md"
readme.write_text(readme.read_text().replace("已实现缓存与条件输出优化，真实模型加速幅度尚未实测。",
    "已完成两例实测：同模型无缓存请求耗时减少约 21% / 31%；210 项测试通过，视觉疑点见优化说明。"))
(review / "final_summary.md").write_text("# 最终交付记录\n\n" + section)
files = set((review / "changed_files.txt").read_text().splitlines())
files.update(["tools/configure_cloud_network.py", "tools/configure_cloud_wait.py", "tools/finalize_delivery_20261012.py"])
backup = ROOT / "backups/operation_20261011"
for old in backup.rglob("*"):
    if old.is_file() and "edit_scripts" not in old.parts:
        rel = old.relative_to(backup).as_posix()
        current = ROOT / rel
        if current.exists() and current.read_bytes() != old.read_bytes():
            files.add(rel)
diffs = []
for rel in sorted(files):
    current = ROOT / rel
    if not current.is_file():
        continue
    old = backup / rel
    before = old.read_text().splitlines(keepends=True) if old.exists() else []
    after = current.read_text().splitlines(keepends=True)
    diffs.extend(difflib.unified_diff(before, after, fromfile="before/" + rel if old.exists() else "/dev/null", tofile="after/" + rel))
(review / "source_changes.diff").write_text("".join(diffs))
(review / "changed_files.txt").write_text("\n".join(sorted(files)) + "\n")
print(json.dumps(summary, ensure_ascii=False, indent=2))

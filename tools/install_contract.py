#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 video2op 学出来的操作图安装到执行侧项目的约定目录。

执行侧是按"**操作名 = YAML 文件名**"加载图的（见 `semantic_graph/catalog.py`）：
语义图放 `semantic_graph/graphs/<操作名>.yaml`，同名策略放
`executable_graph/policies/<操作名>.yaml`。所以"我的图能不能给它用"这件事，
最直接的证明就是把文件放进那两个目录，然后用它自己的入口跑。

用法：
    python tools/install_contract.py 移动物体              # 安装（不覆盖已有文件）
    python tools/install_contract.py 移动物体 --force      # 覆盖同名文件
    python tools/install_contract.py --list                # 看看装了哪些
    python tools/install_contract.py 移动物体 --check-only # 只检查能不能装，不写文件

装完在对方目录里跑：
    cd 操作图同事的 && python main.py --graph 移动物体

**安装不等于可执行**：装进去只说明"结构接得上"，真要跑起来还需要执行侧补上
谓词检测器、参数绑定和真实动作实现（见 tools/verify_contract.py 的输出）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video2op import config

DEFAULT_PEER = ROOT / "操作图同事的"
GRAPH_SUBDIR = Path("robot_operation_graph/semantic_graph/graphs")
POLICY_SUBDIR = Path("robot_operation_graph/executable_graph/policies")
MARK = "由 video2op"              # 只认自己导出的图，不碰别人手写的文件


def _peer_dirs(peer: Path) -> tuple[Path, Path]:
    return peer / GRAPH_SUBDIR, peer / POLICY_SUBDIR


def _is_ours(path: Path) -> bool:
    """这个文件是不是 video2op 导出的（避免误判、误删别人手写的图）。"""
    try:
        head = path.read_text(encoding="utf-8")[:400]
    except OSError:
        return False
    return MARK in head


def install(case: str, peer: Path, force: bool = False, check_only: bool = False) -> int:
    # 案例名可以带目录（如 _regression/喝牛奶2），但安装名只用最后一段：
    # 执行侧是按“操作名 = 文件名”加载的，名字里不能带路径。
    name = Path(case).name
    out_dir = config.OUTPUT_DIR / case
    src_graph = out_dir / "semantic_graph.yaml"
    src_policy = out_dir / "execution_policy.yaml"
    if not src_graph.exists():
        print(f"[跳过] {case}：没有 {src_graph}（先跑 tools/render_case.py {case}）")
        return 1
    graph_dir, policy_dir = _peer_dirs(peer)
    if not graph_dir.is_dir() or not policy_dir.is_dir():
        print(f"[失败] 执行侧目录不存在：{graph_dir} / {policy_dir}")
        return 2

    dst_graph = graph_dir / f"{name}.yaml"
    dst_policy = policy_dir / f"{name}.yaml"
    plan = [(src_graph, dst_graph, "语义图"), (src_policy, dst_policy, "策略")]
    blocked = False
    for src, dst, label in plan:
        if not src.exists():
            print(f"[跳过] {label}：{src} 不存在")
            blocked = True
            continue
        if dst.exists():
            if _is_ours(dst):
                hint = "会被覆盖" if force else "跳过（加 --force 覆盖）"
            else:
                hint = "**同名文件不是本工具导出的，拒绝覆盖**"
                if not force:
                    blocked = True
            print(f"[{label}] {dst.relative_to(peer)} 已存在：{hint}")
            if not force or (not _is_ours(dst)):
                continue
        elif check_only:
            print(f"[{label}] 可安装 → {dst.relative_to(peer)}")
            continue
        if check_only:
            print(f"[{label}] 已是最新：{dst.relative_to(peer)}")
            continue
        shutil.copyfile(src, dst)
        print(f"[{label}] 已安装 → {dst.relative_to(peer)}")
    if check_only:
        print("（--check-only：没有写任何文件）")
        return 0
    if blocked:
        return 3
    print()
    print("跑一遍（在执行侧目录里）：")
    print(f"  cd {peer} && python main.py --graph {name}")
    return 0


def list_installed(peer: Path) -> int:
    graph_dir, policy_dir = _peer_dirs(peer)
    if not graph_dir.is_dir():
        print(f"[失败] 找不到 {graph_dir}")
        return 2
    rows = []
    for path in sorted(graph_dir.glob("*.yaml")):
        rows.append((path.stem, "video2op 导出" if _is_ours(path) else "手写",
                     (policy_dir / path.name).exists()))
    if not rows:
        print("目录里没有操作图。")
        return 0
    print(f"{peer.name} 的可用操作图：")
    for name, origin, has_policy in rows:
        print(f"  - {name}　（{origin}，策略文件{'有' if has_policy else '缺'}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把导出的操作图安装到执行侧项目")
    ap.add_argument("case", nargs="?", help="案例名（output/<案例>/）")
    ap.add_argument("--peer", default=str(DEFAULT_PEER), help="执行侧项目目录")
    ap.add_argument("--force", action="store_true", help="覆盖同名文件（只覆盖本工具导出的）")
    ap.add_argument("--check-only", action="store_true", help="只检查，不写文件")
    ap.add_argument("--list", action="store_true", help="列出执行侧目录里已有的操作图")
    args = ap.parse_args()
    peer = Path(args.peer)
    if args.list:
        return list_installed(peer)
    if not args.case:
        dirs = [d.name for d in config.OUTPUT_DIR.glob("*")
                if (d / "semantic_graph.yaml").exists()]
        print("可安装的案例：", "、".join(dirs) or "（还没有导出过契约）")
        print("用法：python tools/install_contract.py <案例名>")
        return 1
    return install(args.case, peer, force=args.force, check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())

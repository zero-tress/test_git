#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""粗略检查生成的 HTML 结构是否正常（标签平衡、无未转义异常）。"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"br", "img", "meta", "link", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


class Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"多余闭合标签 </{tag}>")
            return
        if self.stack[-1] != tag:
            self.errors.append(f"标签不匹配：期望 </{self.stack[-1]}>，实际 </{tag}>")
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
            return
        self.stack.pop()


def check(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    c = Checker()
    c.feed(text)
    print(f"— {path.name}: {len(text)} 字符, svg×{c.counts.get('svg', 0)}, "
          f"table×{c.counts.get('table', 0)}, div×{c.counts.get('div', 0)}")
    if c.errors:
        print("  错误：")
        for e in c.errors[:10]:
            print("   -", e)
    if c.stack:
        print("  未闭合：", c.stack[:10])
    if not c.errors and not c.stack:
        print("  结构 OK")


if __name__ == "__main__":
    targets = sys.argv[1:] or ["output/搬物体/report.html", "output/搬物体/timeline.html"]
    for t in targets:
        p = Path(t)
        if p.exists():
            check(p)
        else:
            print(f"— {t} 不存在")

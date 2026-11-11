#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时序逻辑表达（确定性）：把时序关系翻译成谓词式 / PLC 式文本。

同时给出两份表达：
  · predicates：谓词式（便于机器/规则引擎读取）
  · plc        ：PLC 式时序行（便于工程人员阅读）
"""

from __future__ import annotations


def _label(a: dict | None, fallback: int) -> str:
    if not a:
        return f"#{fallback}"
    executor = str(a.get("executor") or "")
    action = str(a.get("action") or "")
    # 动作文本往往已经以执行器开头（“右臂向前伸出”），再拼一次会印成“右臂右臂向前伸出”
    text = action if not executor or action.startswith(executor) else f"{executor}{action}"
    return f"#{a.get('id')} {text}"


def _parallel_groups(relations: list[dict], amap: dict) -> list[list[int]]:
    """把互相并行的动作聚成组，组内成员在时间上有公共交集。

    目的：把“#3∥#4、#3∥#5、#4∥#5…”这种两两重复写成一行。
    """
    edges = [(r.get("from"), r.get("to")) for r in relations
             if str(r.get("relation")) == "parallel"]
    edges = [(f, t) for f, t in edges if f in amap and t in amap]
    if not edges:
        return []

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for f, t in edges:
        union(f, t)
    comps: dict[int, list[int]] = {}
    for node in list(parent):
        comps.setdefault(find(node), []).append(node)

    groups: list[list[int]] = []
    for nodes in comps.values():
        ordered = sorted(set(nodes), key=lambda i: (amap[i].get("start", 0), amap[i].get("end", 0)))
        cur: list[int] = []
        for n in ordered:
            if not cur:
                cur = [n]
                continue
            probe = [*cur, n]
            lo = max(float(amap[i].get("start", 0)) for i in probe)
            hi = min(float(amap[i].get("end", 0)) for i in probe)
            if lo < hi - 0.05:      # 组内仍有公共交集
                cur.append(n)
            else:
                if len(cur) > 1:
                    groups.append(cur)
                cur = [n]
        if len(cur) > 1:
            groups.append(cur)
    return groups


def build(actions: list[dict], relations: list[dict]) -> dict:
    amap = {a.get("id"): a for a in actions}
    predicates: list[str] = []
    plc: list[str] = []
    groups = _parallel_groups(relations, amap)
    grouped_ids = {i for g in groups for i in g}

    for r in relations:
        rel = str(r.get("relation") or "").upper()
        a = amap.get(r.get("from"))
        b = amap.get(r.get("to"))
        la, lb = _label(a, r.get("from")), _label(b, r.get("to"))
        if rel == "SEQUENCE":
            predicates.append(f"SEQUENCE({la} ; {lb})")
            plc.append(f"[{la}]  --完成-->  [{lb}]")
        elif rel == "PARALLEL":
            if r.get("from") in grouped_ids and r.get("to") in grouped_ids:
                continue  # 已并入并行组，不重复输出
            predicates.append(f"PARALLEL({la} ∥ {lb})")
            plc.append(f"|-- {la}  与  {lb}  同时 --|")
        elif rel == "ALTERNATION":
            predicates.append(f"ALTERNATION({la} ⇄ {lb})")
            plc.append(f"[{la}]  <=交替=>  [{lb}]")
        elif rel == "MAINTAIN_UNTIL":
            until = b.get("until") if isinstance(b, dict) else None
            until_text = until.get("text") if isinstance(until, dict) else None
            end = until_text or fb_until(amap, b)
            predicates.append(f"MAINTAIN_UNTIL({la} ; {end or lb})")
            plc.append(f"[{la}]  ----保持---->  直到 {end or lb}")
        elif rel == "ENABLES":
            predicates.append(f"ENABLES({la} -> {lb})")
            plc.append(f"[{la}]  --使能-->  [{lb}]")

    # 并行组：同一时间段内多个部位同时进行 → 合并成一行
    for g in groups:
        labels = [_label(amap.get(i), i) for i in g]
        predicates.append("PARALLEL(" + " ∥ ".join(labels) + ")")
        plc.append("|-- " + "  ∥  ".join(labels) + "  同时 --|")
    return {"predicates": predicates, "plc": plc}


def fb_until(amap: dict, b: dict | None) -> str | None:
    """保持动作没有显式 until 时，用它的结束时刻动作兜底。"""
    if not b:
        return None
    for a in amap.values():
        if a.get("executor") == b.get("executor") and str(a.get("mode")) == "transition":
            if abs(float(a.get("start", 0)) - float(b.get("end", 0))) < 0.6:
                text = str(a.get("action") or "")
                if any(w in text for w in ("松开", "释放", "放下", "放开")):
                    return _label(a, a.get("id"))
    return None


STYLE = """
.logic{background:#0f172a;color:#e2e8f0;border-radius:8px;padding:12px 14px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.7;
 white-space:pre-wrap;overflow-x:auto}
.logic .cmt{color:#94a3b8}
"""


def render_html(logic: dict) -> str:
    preds = logic.get("predicates") or []
    plc = logic.get("plc") or []
    if not preds and not plc:
        return "<p class='muted'>（无）</p>"
    pred_text = "\n".join(preds)
    plc_text = "\n".join(plc)
    return (f"<h4>谓词式</h4><div class='logic'>{_esc(pred_text)}</div>"
            f"<h4>PLC 式时序</h4><div class='logic'>{_esc(plc_text)}</div>")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

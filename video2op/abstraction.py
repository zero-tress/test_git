"""Operation-level actor vocabulary. Never silently turn posture evidence into success."""
from __future__ import annotations

import re

ALLOWED_EXECUTORS = {"整体", "左臂", "右臂", "左手", "右手"}
# Match human anatomy, not object components such as 桌腿 / 椅脚.
ANATOMY = re.compile(r"腰(?:部|背)?|躯干|下肢|膝(?:关节|盖|部)?|(?<![桌椅凳柜床支架])腿(?:部)?|(?:左|右|双|两)脚|脚掌|足部")
LEGACY_EXECUTORS = {"躯干", "腰", "腰部", "腰背", "上身", "腿", "左腿", "右腿",
                    "双腿", "脚", "左脚", "右脚", "双脚", "膝关节", "膝盖", "下肢"}
EVIDENCE_KEYS = {"evidence", "inference_reason", "raw", "previous_analysis",
                 "viewpoint", "meta", "pipeline"}
PROMPT_POLICY = """
【统一操作抽象 v2，适用于所有操作语义字段】
执行器仅为：整体、左臂、右臂、左手、右手。左右臂与左右手分别保留。
人的连续走路抽象为整体“向目标移动”，目标填写可确认的物体或操作位置；不能把移动目标写成已抓取的物体。
同一目标、连续时段只写一个整体移动，不拆步态。目标不明时写“移动”，object=null并记录不确定性。
人的下蹲抽象为整体“下降”，起身抽象为整体“上升”。它们改变操作者的操作高度，不等于手臂抬起/放下物体。
整体只表示垂直上升/下降和水平方向移动（为轮臂式小车保留）；不得用整体表达姿态调整、静止、抓取或手臂抬物。仅前倾且高度变化不清时不生成整体动作，记录观察不确定性。
操作名称、条件、能力、状态、约束、评价和步骤中均不写腰部、躯干、腿、膝关节、脚或步态支撑。
不生成静止站立支撑、无任务目的的整体保持。操作所需的稳定性写作持续约束。
持续抓握与托举只写 C_const，不生成保持动作或保持类型。
节点是操作；执行器和目标是属性。名称精简，证据与推断分离；不虚构目标、到达、抓牢或成功。
输出紧凑 JSON，说明只写必要的一句话，不重复输入，不展开无关常识。
"""


def semantic_issues(value: object, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in EVIDENCE_KEYS:
                continue
            here = f"{path}.{key}" if path else key
            if key == "executor" and isinstance(item, str):
                aliases = {"身体": "整体", "全身": "整体", "操作者": "整体",
                           "左手臂": "左臂", "右手臂": "右臂"}
                if aliases.get(item, item) not in ALLOWED_EXECUTORS | {"头", "颈", "口"}:
                    issues.append(f"{here}: 必须只绑定一个明确执行器，不支持 {item}")
            if key == "executor" and item == "整体" and "action" in value:
                candidate = dict(value)
                normalize_overall_action(candidate)
                if candidate.get("action") not in {"上升", "下降", "向目标移动", "移动"}:
                    issues.append(f"{here}: 整体只允许垂直上升/下降及水平移动")
                if value.get("mode") != "motion":
                    issues.append(f"{here}: 整体仅记录位置变化，不补静止保持")
            if key in {"executor", "part"} and isinstance(item, str):
                # Existing head/mouth filtering is left to ignored_parts.
                if item in LEGACY_EXECUTORS:
                    issues.append(f"{here}: 旧版人体部位 {item}")
            issues.extend(semantic_issues(item, here))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            issues.extend(semantic_issues(item, f"{path}[{i}]"))
    elif isinstance(value, str) and (value in LEGACY_EXECUTORS or ANATOMY.search(value)):
        issues.append(f"{path}: 操作语义含人体部位细节 {value[:70]}")
    return issues


def validate_semantics(payload: object) -> None:
    issues = semantic_issues(payload)
    if issues:
        raise ValueError("请使用整体移动/上升/下降和左右臂手："
                         + "；".join(issues[:4]))


def validate_bundle(bundle: dict) -> None:
    # Historical lower-body outputs cannot safely be upgraded by deleting words.
    # Re-extraction must regenerate conditions and references together.
    for key in ("atomic", "task_nodes", "intents", "conditions", "rules"):
        issues = semantic_issues(bundle.get(key) or {})
        if issues:
            raise ValueError(
                "操作抽象版本不兼容，需要按新提示词重新分析视频；原结果应保留。"
                + "；".join(issues[:3]))


def normalize_overall_action(action: dict) -> None:
    """Normalize explicit movement wording without inferring successful effects."""
    if action.get("executor") != "整体":
        return
    original = str(action.get("action") or "").strip()
    name = original.removeprefix("整体").strip()
    if any(w in name for w in ("下降", "下移", "降低操作高度", "降低高度", "向下移动", "下蹲", "蹲下")):
        canonical = "下降"
    elif any(w in name for w in ("上升", "上移", "升高操作高度", "升高高度", "向上移动", "起身", "站起")):
        canonical = "上升"
    elif any(w in name for w in ("调整操作位置", "调整姿态", "前倾", "回正")):
        canonical = "调整操作位置"
    elif any(w in name for w in ("移动", "走向", "走到", "行走", "迈步", "接近", "靠近")):
        canonical = "向目标移动" if action.get("object") else "移动"
    else:
        return  # no supported equivalence: preserve wording instead of inventing a change
    if canonical != original:
        action.setdefault("action_detail", original)
        action["action"] = canonical

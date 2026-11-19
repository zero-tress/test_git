"""Learn portable skill tuples without changing a committed task topology."""
import json
from copy import deepcopy

FIELDS = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")
EVALUATORS = ("completion", "process_constraint", "implementation_applicability")
TUPLE_SYSTEM = """你是跨视频技能七元组归纳器。输入是已定稿的技能成员、每个成员的七元组、实现、条件和评价证据。只输出 JSON。
为每个现有 skill_id 输出一条通用七元组。总结功能角色与作用对象角色，不照抄某个视频的左右手、颜色、具体容器或坐标。
逐字段比较同技能的成功、失败、未执行和未知，提炼共有描述和适用范围。仅某种实现成立时写清适用范围。
C_pre 是进入前的状态，C_const 是过程约束，C_post 是期望效果。请把有来源的跨实例归纳条件写成可读的候选条件；
缺乏反例时仍可总结为候选前提或过程约束，注明证据范围，不变成已证实的必要条件，也不增加图的门控。
E 分别写可观察的完成判据、怎样评价过程、实现适用性。不要用 E1 等编号代替文字，不生成控制器或检测器。
R 已在输入的技能和实现列表中冻结，程序按原样继承。仅归纳其他六个字段，不输出 R 或 evidence.R。
每个非空字段必须给出所属技能内的来源 member_ref。
无数据时写空数组并在 evidence_gaps 写字段和原因。
只输出 {"skill_tuples":[{"skill_id":"输入id","X":{"role":"执行角色"},"O":{"target":"对象角色"},
"C_pre":["候选条件"],"C_const":["候选约束"],"E":{"completion":[],"process_constraint":[],"implementation_applicability":[]},
"C_post":["期望效果"],"evidence":{"X":[],"O":[],"C_pre":[],"C_const":[],"E":[],"C_post":[]},
"evidence_gaps":{"可为空字段":"无法归纳的原因"}}]}。证据冲突时保留范围和不确定性。"""


def validate_tuples(value, skills):
    skills_for = {skill["id"]: skill for skill in skills}
    rows = value.get("skill_tuples") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Seven-tuple stage needs skill_tuples")
    result = {}
    for row in rows:
        sid = row.get("skill_id")
        if sid not in skills_for or sid in result:
            raise ValueError(f"Unknown or repeated tuple skill id: {sid}")
        skill = skills_for[sid]
        allowed = set(skill["source_members"]) | set(skill.get("shared_members") or [])
        evidence, gaps = row.get("evidence"), row.get("evidence_gaps")
        if not isinstance(evidence, dict) or not isinstance(gaps, dict) or set(evidence) != set(FIELDS):
            raise ValueError(f"{sid}: give an evidence array for each of the seven tuple fields")
        if any(not isinstance(text, str) or not text.strip() for text in gaps.values()):
            raise ValueError(f"{sid}: each evidence gap must explain the missing evidence")
        for field in ("X", "O"):
            roles = row.get(field)
            if not isinstance(roles, dict) or not roles or not all(isinstance(v, str) and v.strip() for v in roles.values()):
                raise ValueError(f"{sid}: {field} requires role descriptions")
        evaluator = row.get("E")
        if not isinstance(evaluator, dict) or set(evaluator) != set(EVALUATORS):
            raise ValueError(f"{sid}: E needs completion, process_constraint and implementation_applicability")
        for key, values in {**evaluator, **{key: row.get(key) for key in ("C_pre", "C_const", "C_post", "R")}}.items():
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{sid}: {key} must be an array of nonempty statements or references")
            if not values and key not in gaps:
                raise ValueError(f"{sid}: empty {key} requires an evidence gap")
        if len(row["R"]) != len(set(row["R"])) or set(row["R"]) != set(skill["R"]):
            raise ValueError(f"{sid}: R must preserve the exact existing implementation IDs {skill['R']}")
        for field in FIELDS:
            refs = evidence[field]
            has_value = any(evaluator.values()) if field == "E" else bool(row[field])
            permitted = allowed | set(skill["R"]) if field == "R" else allowed
            if not isinstance(refs, list) or not set(refs) <= permitted or (has_value and not refs):
                raise ValueError(f"{sid}: {field} must cite only its source members: {sorted(allowed)}")
        result[sid] = row
    if set(result) != set(skills_for):
        raise ValueError(f"Missing skill tuples: {sorted(set(skills_for) - set(result))}")
    return result


def learn_tuples(client, graph, source_members, conditions, rules, reviews):
    if not graph["skills"]:
        return {"skill_tuples": []}
    inputs = {"skills": graph["skills"], "realizations": graph["realizations"],
              "source_members": source_members, "conditions": conditions, "rules": rules,
              "visual_reviews": reviews}
    skills = graph["skills"]
    def validate_response(value):
        return validate_tuples(inherit_realizations(value, skills), skills)

    value = client.ask(stage="s13_skill_tuples", system=TUPLE_SYSTEM,
                       user_text=json.dumps(inputs, ensure_ascii=False), max_tokens=9500, validator=validate_response)
    return inherit_realizations(value, skills)


def inherit_realizations(value, skills):
    """Copy the already validated R references; no semantic choices occur here."""
    saved = deepcopy(value)
    rows = saved.get("skill_tuples") if isinstance(saved, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Seven-tuple stage needs skill_tuples")
    refs = {s["id"]: list(s["R"]) for s in skills}
    for row in rows:
        sid = row.get("skill_id")
        if sid not in refs or not isinstance(row.get("evidence"), dict) or not isinstance(row.get("evidence_gaps"), dict):
            raise ValueError(f"Invalid tuple skill or evidence: {sid}")
        row["R"] = list(refs[sid])
        row["evidence"]["R"] = list(refs[sid])
        if not refs[sid]:
            row["evidence_gaps"]["R"] = "已合并技能尚无可引用的来源实现"
    return saved

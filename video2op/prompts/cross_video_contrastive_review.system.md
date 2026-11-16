你是部署模型中的局部技能正反例学习阶段。所有局部意图、范围、成败、条件对照和七元组由你分析；宿主只校验、裁剪和展示，不代替你补字段或标签。

输入是联合视频、源时间映射、真实源帧、上游模型提出的局部试次候选和整体任务观察。whole_task_model_observations仅提供整段任务背景；整体成功不覆盖较早的局部失败。主图的成功流程与本阶段局部技能成败分别判断。
逐个复核candidate_local_trials的每个candidate_ref，恰好输出一次。旧标签是候选，不能直接接受；不认可或证据不足则unknown并解释。额外发现的试次可追加，candidate_ref=null。同一试次不能被重复计数。

requested_skill_definition是用户指定技能意图，不能用整段任务或候选名称替代。本次范围是grasp_object，即对同一目标建立稳定握持。抬离原支撑不是抓取成功的必要条件；不能仅因未抬起就判失败。可用同一次试次后续的手物共同运动支持稳定握持，不能借用后一次试次。
每个样本skill_id必须使用requested_skill_definition.skill_id。scope_verdict必填：
- supported：证据支持属于该技能范围，再判断success/failure/unknown；
- ambiguous/rejected：范围不确定或不属于该技能，outcome必须unknown。
正反例只来自真实局部观察，不造反事实片段，也不把文件名、动作名、预期效果当成成功证据。

时间为各原视频全局秒数，区分core范围和context验证上下文。context须覆盖core；不能确定的边界用null，不猜测。
只引用allowed_evidence中的ID。每个技能定义保留X,O,C_pre,C_const,E,C_post,R；由你填实际内容。E必须是评价方法，包含metric、success_condition、failure_condition、unknown_condition，不等于动作名称或策略。证据不足的标准可为null并说明限制。

条件对比严格区分两种分组：
- positive_example_ids仅引用outcome=success的行为样本，negative_example_ids仅引用outcome=failure的行为样本；
- 条件有无使用condition_present_example_ids / condition_absent_example_ids，两者与行为正反例不是一回事。
不能把“没有障碍物但成功”的行为放进negative_example_ids。无法建立可靠条件对照时，condition_comparisons直接输出空数组，或将相应行为分组留空并标记candidate/unknown。不强求条件结论，更不能编造必要充分条件。

只输出严格JSON，不要Markdown围栏。所有示例字段均必填，数组可空；不要照抄占位值：
{
 "schema_version":"model_contrastive_review.v1",
 "skill_definitions":[{
   "skill_id":"grasp_object","label":"你归纳的技能名称",
   "seven_tuple":{
     "X":{},"O":{},"C_pre":[],"C_const":[],
     "E":{"metric":null,"success_condition":null,"failure_condition":null,"unknown_condition":null},
     "C_post":[],"R":[]
   },"limitations":[]
 }],
 "examples":[{
   "id":"唯一样本ID","candidate_ref":"对应输入候选ID或null",
   "case_id":"来源ID","skill_id":"grasp_object",
   "scope_verdict":"supported/ambiguous/rejected",
   "outcome":"success/failure/unknown",
   "core_start_sec":null,"core_end_sec":null,
   "context_start_sec":null,"context_end_sec":null,
   "evidence_refs":[],"reason":"技能范围、可观察结果及判定依据"
 }],
 "condition_comparisons":[{
   "condition":"条件候选",
   "positive_example_ids":[],"negative_example_ids":[],
   "condition_present_example_ids":[],"condition_absent_example_ids":[],
   "status":"candidate/unknown","reason":"对照依据和证据缺口"
 }],
 "limitations":[],"human_verified":false
}
输出前自查每个候选一次、每个样本scope_verdict必填、E的四字段齐全、引用样本ID存在且正反引用与其outcome一致；条件存在/不存在不能替代行为成功/失败。

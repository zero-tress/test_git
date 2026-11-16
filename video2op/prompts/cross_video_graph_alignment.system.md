你是部署模型的“同目标跨视频语义支路合并”阶段。本次不重新观看视频，只使用输入中部署模型已经完成的逐来源实例分析和先前成功图候选。不能声称看到新画面，不能新增源时间/成败事实。所有合并和七元组抽象由你完成，宿主不推断动作类别、不合并业务节点。

关键纠正：要区分“跨视频实例差异”和“同一路径内的状态变化”。
- 铁盒/桌面/笔筒等支撑位置差异、目标颜色、玻璃瓶/杯的区别，放进sources参数与R；这些不是把所有靠近和抓取各画三套的理由。
- 同一目标任务中的“靠近目标”可在相同流程位置跨视频共享节点，实例条件通过sources与后续门控表达。
- 同一个来源在条件变化之前和准备之后的两次靠近，必须是不同occurrence节点，不能合并成循环。它们可以分别跨来源对齐为“靠近目标（初始）”与“靠近目标（准备后）”。
- 同一目标效果的成功抓取，应合并为共享语义抓取节点；七元组使用角色/目标参数，源物体实例保留sources。抓取之后直接结束，不能增加结束门控或验证。
- 对应抓取前条件门控也按流程位置合并；跨来源事实不一致时truth用U，不能把条件分支要求T/F误当成已证实事实。
- 所有靠近后必须有grasp_precondition门控；只有gate_outcome=T的边进入抓取，F进入准备支路，之后再次靠近、新门控再抓取。不同来源原有成功顺序不能为合并而丢失。
- 先前成功图候选可补充已明确识别的清障准备，尤其source_instance_graph.simplifications中声明keep的成功步骤不能只在说明里而不在路径里。判断来源、实例关系和抽象由你完成；不确定写limitations，不编造观测。

输出完整JSON，schema_version=model_success_graph.v3，保留输入根字段的完整协议及每个操作七元组。宿主将校验：
1. 以下根字段必须与source_instance_graph完全相等，不重写：source_decisions、contrastive_examples、simplifications、learning_policy、end_policy、execution_enabled、approach_policy。
2. 每个来源的approach_review.occurrences数必须与required_source_video_approach_counts一致，节点引用按新的paths同步，不得漏第一次靠近或合并两次出现。
3. 操作必须有action_role、成功结果、七元组X/O/C_pre/C_const/E/C_post/R，E包含metric/success_condition/failure_condition/unknown_condition。
4. approach_target节点有state_context，每次紧接grasp_precondition门控；门控predicate/truth/reason/sources/uses_removed_failure_as_runtime_precondition=false完整，T/F必须有证据，否则U。
5. 共享节点和边的source_case_ids必须精确等于各paths使用关系，源时间和证据保持来自输入模型分析，失败段不能重新进入成功操作。
6. 无循环，不得让某来源沿别人的边拼出新路径；共有来源共享抓取，允许不同时序位置的靠近及门控独立。
7. 原始observed失败仍在独立样本池；模型对必要性的candidate/unknown不升级为证明。

重点完成实际语义节点合并，而不是输出实例并列图后在merge_review中说“位置不同所以全部分开”。本轮共同目标和局部语义已在输入中确定，可以参数化；同一来源的重复出现次数由拓扑保留。merge_review说明合并映射和状态区分。只返回严格JSON，不要Markdown。


## 本批次用户入口要求，优先于旧图与实例观察的直接入口
当user_graph_requirements有entry_policy时，完整照抄到输出根entry_policy。
本次拿笔任务明确要求：开始只能有一条出边，且唯一后继是approach_target（靠近目标）。绝不保留开始→移动障碍物/清障/其他准备的边。准备必须位于第一次靠近后的抓取条件不成立分支；准备完成后再次靠近，再检查条件，成立才抓取。合并兼容的清障实例，避免入口另画一条清障路径。结束前仍无门控。

区分“用户要求的学习任务流程”与“视频逐帧事件回放”。不能因为旧模型记录某个视频先移物，就把START→移物放回学习图；也不能为满足新流程而伪造该视频已经观察到首次靠近。
原来的逐来源approach_review.occurrences只记录视频实际观察到的靠近，出现次数必须保持不变，节点引用可以映射到新的初始/准备后阶段。source_decisions等观测判断保持原样。
如果按用户入口规则需要在某来源路径增加未观测到的初始靠近，由你在图中保留该步骤并单独新增根rule_only_occurrences：
[{"case_id":"该来源ID","node_id":"初始靠近节点ID","grasp_gate_id":"紧随门控ID","basis":"user_requirement","observed":false,"evidence_refs":[]}]
同一node的sources里给该来源一项：
{"case_id":"来源ID","start_sec":null,"end_sec":null,"evidence_refs":[],"basis":"user_requirement","observed":false}
该来源path增加path_kind="policy_constrained_success_projection"。不要把它放入approach_review的观察次数中；不得给规则步骤捏造视频时间、帧或成功证据。共享靠近节点仍可由其他来源真实观测支持。
如旧来源观察到的靠近发生在移物之后，将那次真实观察映射到准备后的靠近节点；用户入口要求补充的初始靠近单独标注，不交换或改写原视频时间。T/F边是通行规则，门控证据不足仍U。
所有新增节点、边、路径、七元组与映射都由你决定并输出。宿主仅检查入口规则与来源标记，不会手动移动任何业务节点。

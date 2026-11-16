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

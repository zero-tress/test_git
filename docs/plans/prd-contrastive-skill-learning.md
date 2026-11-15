# 同目标任务图归纳与同类技能切片学习方案

日期：2026-11-15。依据本次讨论调整，以下是当前实施口径。

## 两条流程

1. 同目标任务图归纳：先分别分析完整视频的意图、对象、操作过程和目标效果。将为了完成同一语义目标的操作图放在一起，进行支路合并和功能合并。主验收样例为data/抓取1.mp4、抓取2.mp4、抓取3.mp4；用户指定共同目标为“拿起笔”，对应acquire_object。
2. 同类技能切片学习：依据局部意图和效果分类，将各视频中的抓取等子技能片段归入相同技能，独立判断成功、失败、未执行、未知，进行条件与结果对照。整体任务失败不覆盖局部抓取成功。

## 范围和证据

- “拿起笔”要求持有目标并脱离原支撑；“抓取”要求建立稳定握持。两种范围分别保存。
- 完整任务路径保留拿笔之前的可见事件。之前移瓶/移杯可以作为路径中的上下文；其是否为清障、是否必要，需要效果到前置条件的证据。
- 语义依赖与观察到的时间顺序分别标记。补充时序连接时只记录observed_order，不自动变成因果依赖。
- 抓取核心片段、准备过程上下文、后效验证上下文分别导出；同一实例的多个视图只算一个样本。
- 未观察的张开、释放等动作不伪造事件或视频。原视频解码覆盖不足的部分保持未知。

## 意图、状态和因果

- 用户给出的目标独立于模型分类。模型把“拿起笔”错分为“搬移”时保留目标，重新核验拿起的效果，不继承错误分类下的成功结论。
- 对象简称只在单视频内消歧；同义状态转为带角色、极性和阶段的谓词。普通握持、稳定握持、未观察、否定分别处理，原句和来源保留。
- 对任务图边检查前一步实际效果、后一步前置条件、对象角色、证据时间、相反事实和状态是否早已成立。
- 模型创造的节点/条件编号、未来帧、推断状态等意见隔离保存。声明的后置条件不能替代实际观察。
- 分支选择只使用决策前条件。选择对照与执行成败对照分别统计；足量独立视频才能产生候选规则，存在反例则降级，均不启用机器人执行。

## 七元组与统一大纲

继续使用X、O、C_pre、C_const、E、C_post、R。
同目标归纳的R保存该目标的不同实现图；局部抓取的学习证据帮助评估路径内的子技能。
模板统一维护于skill_library。两个学习视图分别保存证据与来源，并引用相同模板，不按视频复制全局定义。未充分证实的公共条件不填入通用C_pre。

## 交付

- 单视频：result.json、operations.svg、workbench.html、skill_instances.json、clip/sequence.json。
- 补充：task_learning_units.json、clip_classification.json、skill_episodes.json、task_causal_audit.json、learning_review.json。
- 两条流程：learning_tracks/same_goal_graphs/及learning_tracks/classified_skill_clips/。
- 切片目录按技能和局部结果分组，保留源视频、动作、序号、分析时间、时间区间及父任务引用。
- 保留历史16段数据的开发/留出划分，冻结开发知识后再验留出；不把事后标注当作独立验证。

## 验收

检查实际MP4解码、来源哈希、七字段、路径可重建、局部与整体成败隔离、前后阶段和未来证据、分支反例、页面链接及脚本语法。
工程机制和经验结论分别验收：缺抓取失败样本、缺清障条件对照时明确报告，不预填已经学会普遍因果规律。

## 服务器复现

~~~bash
conda run -n study python -B learn.py \
  --inputs output/runs/two_track_learning_20261115/pen_observations/抓取1_semantic_v3/result.json \
           output/抓取2_semantic_v3/result.json \
           output/runs/two_track_learning_20261115/pen_observations/抓取3_semantic_v3/result.json \
  --goal acquire_object --target-category pen \
  --local-reviews output/runs/two_track_learning_20261115/pen_reviews_bounded/results.json \
  --out output/runs/新的学习目录

conda run -n study python -B tools/verify_two_track_delivery.py --out output/runs/新的学习目录
~~~

以上复用保存的分析与复核，不再次调用模型。重新分析视频才需要访问已授权的现有本机8032服务。

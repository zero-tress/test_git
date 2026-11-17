# 第1—7步视频知识学习

本轮入口为 /home/wj/codex-workspace/videostudy_operation/output/意图拿笔2/index.html。
旧 output/抓取2_semantic_v3 和 output/意图拿笔 保留；新批次不替换已有别名。

## 运行
所有程序在服务器已有 conda study 环境，通过 cloud_wj 执行。模型服务是既有 http://127.0.0.1:8032 的 qwen3.8-27b；客户端拒绝其他模型/端口、环境代理及重定向。仅模型进行视频理解与语义归纳。宿主负责抽样、校验、引用、存储和绘图。

完整运行：
~~~bash
conda run -n study python -u -B tools/learn_video_knowledge.py \
  --videos data/抓取1.mp4 data/抓取2.mp4 data/抓取4.mp4 \
  --out output/新的批次 --allow-8032
~~~

--description 接收可选任务背景文本，背景不能作为已观察事实。
新批次输出必须为空；中断后可显式 --resume，仅复用源视频/结果hash、模型和背景一致的本批次。跨视频阶段还验证来源结果；提示词指纹变化时须显式 --refresh-prompts 才能续跑；已完成的实例重跑 s09 语义层用 --refresh-case-graph（同时自动加 --refresh-sources），不重跑抽样与意图阶段。各阶段缓存仍按内容寻址逐条校验。不把旧分析的文件名当作重复运行许可。

续跑已完成批次（不重复调用模型，只重导出各实例的 G_case 视图）：
~~~bash
conda run -n study python -u -B tools/learn_video_knowledge.py \
  --videos data/抓取1.mp4 data/抓取2.mp4 data/抓取4.mp4 \
  --out output/意图拿笔2 --description <原批次任务背景文件> \
  --resume --refresh-prompts --allow-8032
~~~

仅对已完成且含 G_case 的模型分析继续归纳：
~~~bash
conda run -n study python -B tools/learn_semantic_graph.py \
  --inputs output/新的批次/cases/抓取1_semantic_v3/result.json \
           output/新的批次/cases/抓取2_semantic_v3/result.json \
           output/新的批次/cases/抓取4_semantic_v3/result.json \
  --out output/另一新目录 --allow-8032
~~~

## 单视频
原有 operations.svg、workbench.html、result.json、skill_instances.json 和视频切片保留。
新增 G_case.json / G_case.svg，表示“语义技能实例 → 来源操作子图”。G_case.svg 沿用 operations.svg 的图形语言：横向推进的圆形技能节点、前置条件门控菱形、实线/虚线关系、悬停完整详情与底部图例；每个节点下方直接展开七元组面板 X · O · C_pre · C_const · E（完成/过程/适用）· C_post · R；图底部为每个 R 画出操作节点的实现子图，maintain_until 用绿色虚线“保持→”表示，parallel 用“∥”标注。条件真值未知时门控连线保持虚线。

时序契约：relations 支持 sequence/parallel/alternation/branch/synchronization/maintain_until，其中 maintain_until 表示前段效果保持到后段开始，不参与前置环检测。操作层的非 sequence 关系必须向上映射：跨技能时给出同类型技能关系；属于同一实现时在该技能实现子图保留；无法映射的逐条写入 unmapped_relations 并说明理由。被观察到却未进入任何 R 的操作必须列入 excluded_operations 并说明（already_satisfied 与 inferred 自动豁免）。

靠近与清障：手必须抵达目标附近才能抓取。靠近与抓取是可分辨的原子动作段时，必须把靠近建成独立技能并给出 observed_order 前置；有遮挡时清障先于靠近与抓取；没有靠近动作证据时不得虚构，写入 unresolved。
s02a意图与s02b原子操作并行；局部复核后冻结独立观察分支 observed_operation_graph，再生成操作节点并做s03同步校验。s02c不接收意图答案。
s09_case_graph由Qwen在原模型视频观察上学习语义实例、局部尝试、条件观察、实现引用和结果。它不固定补齐四个语义节点，也不把状态已满足当作已发生动作。
每个语义实例包含七字段X/O/C_pre/C_const/E/C_post/R，预期效果和实际结果分开，局部结果与任务整体结果分开。证据必须属于本技能的实现动作，推断或解码范围外动作不能证明实际效果。
控制器、检测器保持unbound；结构通过不意味着因果已证明或机器人已能执行。

## 跨视频
依次由同一个部署模型执行三个独立阶段：
- s10_contrastive_conditions：成功/失败/未执行/未知的条件对比与提升决策；
- s11_semantic_rules：过程约束、效果评价、实现适用性与时序规则；
- s12_cross_semantic：同任务支路合并、同目的同效果功能合并，输出语义技能与多个R。无法归入任何技能的实例必须显式列入 unassigned_members 并说明理由，对应的实现保留在 realizations 中并把 skill_id 写为 unassigned；同一动作若同时服务两个目的，用 shared_members + shared_reason 声明共享，主归属唯一且不产生额外 task_node；宿主校验要求每个来源实例与实现恰好有去处，不静默丢弃。跨视频规则允许引用归属其他技能的同动作实例，但必须与本技能成员有交集，覆盖率记录在 validation.json 的 evaluator_coverage。
中间响应保存在knowledge/learning_stages，新请求缓存保留模型、端口、请求指纹和原始响应，失败尝试另存cache/failures。模型失败时停止，不生成替代语义结论。

产物：
~~~text
新批次/
  index.html
  run_manifest.json
  cases/
    抓取1_semantic_v3/{operations.svg,workbench.html,G_case.json,G_case.svg,...}
    抓取2_semantic_v3/...
    抓取4_semantic_v3/...
  knowledge/
    workbench.html
    semantic_operation_graph.svg
    G_semantic.json
    skill_catalog.json
    realizations.json
    condition_decisions.json
    semantic_rules.json
    validation.json
    source_manifest.json
    learning_stages/
    cache/
~~~

G_semantic保存语义技能、任务图、实例映射、分支/功能合并理由和完整来源路径。realizations.json保留各R引用的来源操作子图。不得将来源路径的边并集当作任意可组合的已观察路径。
五类关系是sequence/parallel/alternation/branch/synchronization；观察到的先后、逻辑推断及可并行候选分别记录。
条件提升需要明确的可比范围和证据，F条件下成功可以反驳必要性；未执行不计执行失败。没有足够反例时，条件保留在R或标未决，不填假定的通用条件。

## 适用边界
当前输出是带证据的模型学习候选；尚未经过独立人工语义验收和机器人执行验证。三个视频可以验收流程及来源映射，不能据此证明普遍必要条件或未展示实现。
没有观察到的分支、控制器及技能不以模板补为已学会。后续可以在冻结来源的前提下增加独立样本、人工复核和控制绑定。

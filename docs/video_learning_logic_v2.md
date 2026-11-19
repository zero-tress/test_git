# 视频知识学习逻辑 v2

逻辑契约为 `video_learning.logic.v2`（2026-11-18）。图的样式、布局方式和交互沿用现有实现；修改的是节点依据、关系、条件真值、门控归属与实现来源。

`/home/wj/codex-workspace/videostudy_operation/output/意图拿笔2/` 是用户确认的图和来源路径基准。
`/home/wj/codex-workspace/videostudy_operation/output/runs/logic_refactor_20261118_064314/` 是前次试验结果，其中抓取 1 漏掉清障，跨视频主路径也不符合该基准。
下述规则由新版代码在未来的运行批次中执行。

## 运行

所有程序通过 cloud_wj 在云服务器现有 conda `study` 环境运行。模型为既有 8032 服务的 `qwen3.8-27b`。
模型负责视频理解与语义判断；宿主负责媒体处理、引用检查、保存和绘图。
连接模型需要已有的网络授权；下面的 `--allow-8032` 只表示允许使用已配置的模型端点。

```bash
# 在 /home/wj/codex-workspace/videostudy_operation 执行完整单视频及跨视频学习
conda run -n study python -u -B tools/learn_video_knowledge.py \
  --videos data/抓取1.mp4 data/抓取2.mp4 data/抓取4.mp4 \
  --out output/runs/新的批次 \
  --graph-requirements tasks/pick_pen_graph_requirements_v2.json --allow-8032

# 相同源码、政策及输入下续跑
conda run -n study python -u -B tools/learn_video_knowledge.py \
  --videos data/抓取1.mp4 data/抓取2.mp4 data/抓取4.mp4 \
  --out output/runs/新的批次 \
  --graph-requirements tasks/pick_pen_graph_requirements_v2.json --resume --allow-8032

# 离线验证完成批次，检查来源、版本、媒体、关系与页面链接
conda run -n study python -B tools/verify_video_knowledge.py \
  --out output/runs/新的批次 --report output/runs/新的批次/verification.json

# 离线回归
conda run -n study python -B -m pytest -q -p no:cacheprovider
```

`--description` 接收可选任务背景文本。`--graph-requirements` 是显式任务政策；省略时使用通用分析，不强制拿笔步骤，也不普遍禁止释放或放置。
任务政策与背景冻结到 `task_contract`，来源为用户声明，不能充当观察证据。
单视频也可用 `run.py <视频> --graph-requirements <政策JSON>`。完整跨视频流程通过上述入口运行到 s13。

新批次输出必须为空。续跑验证源视频、背景、模型以及已完成结果的 hash；源码或跨视频提示词变化需显式 `--refresh-prompts`。
单视频契约或任务政策改变还需 `--refresh-case-graph`；该选项保留旧版本到案例 `history/`，刷新 s09 并自动刷新跨视频来源，不重跑已完成案例的前置观察阶段。
阶段文件、最终 G_case 与 manifest 同步更新。缓存只有实际请求内容、视频/图片字节和模型一致且重新通过当前校验才能复用。
失败草稿单独保存；模型不能产生有效结果时停止，宿主不会补造语义结论。

## 单视频契约

s09 先复核操作与任务目标的关系，保存 `task_scope_review`。它结合整个视频、动作前后状态及同步意图，区分目标操作、辅助操作、独立操作和范围未决操作。
语义图构建阶段须保留已复核的目标及辅助操作。在没有足够证据确定作用时，保留该操作及未决理由。
复核认定的清障操作组须集中在一个完整 R 中，内部抓、移、放均可保留。是否有助于当前实例和是否存在普遍必要性分别判断。

每次局部尝试有独立 `attempt_id`；失败后成功仍是两次尝试。总任务结果不会覆盖局部结果。
`expected_effects`、`C_post` 保存预期，`actual_postconditions` 保存实际结果。
R 表示共同完成局部目的的一种完整实现，串行片段不会冒充多个替代方法。
每个 R 保存 `completeness`、`effect_evidence_refs` 和源操作/原子动作引用；成功需要完整观察实现及局部效果证据。
未执行、推断操作、已满足状态以及政策补充均不能计作成功观察。

通用分析保留实际偏序；拿笔政策仅约束本任务的单视频线性语义链。
清障的内部抓、移、放可以构成同一个完整 R；目标达成后的额外放置是否超范围由本次政策决定。
缺失的政策入口只能作为无证据的 `rule_only` 候选，不能虚构为已执行。
观察关系须覆盖两端本地证据并符合时间区间；已有先后、候选依赖和因果必要性分别表达。
未采用操作和无法提升的关系都需说明，观察层保留原件。

原有 `operations.svg`、`workbench.html`、`result.json`、`skill_instances.json` 和切片保留。
`G_case.json` 与 `G_case.svg` 保存七元组、来源映射、门控及实现子图。

## 跨视频对比与成功流程

1. 索引每个实例的原子动作核心区间、前后上下文、局部结果、结构化状态及原有切片引用。
2. 实际导出局部上下文视频和前/中/后画面，由模型按目的与效果分组，不按名称硬编码归类。
3. 每组分批构建对比视频，把视频字节与带样本/阶段标签的图片一起发给 Qwen；时间轴保存到源视频的映射，媒体保存 hash。
4. 模型复核每个实例，给出支持原结论、冲突或未知以及画面引用；覆盖全部样本，冲突不会静默改写来源结果。
5. 模型逐实例记录复核支持、仅作对比、未执行、未决等证据去向。完整任务流程以已落盘 G_case 的任务结果和局部结果为准。局部复核分歧保留在条件对比和待核记录中。
6. s10 学习条件，s11 学习规则，s12 合并现有任务支路和技能实现。所有来源实例必须映射或明确列为未分配。
7. s13 按已经合并的技能实例归纳通用七元组。它保留已有 R 引用，每个有内容的字段带来源实例。证据不足的字段给出待补理由。

条件的 T/F 需要该实例相应 pre/during/post 画面或结构化状态证据，不能用之后成功倒推之前条件成立。
分支的 `gate_outcome`（T/F 支路）与 `guard_truth`（证据 T/F/U）分开。
拿笔政策要求首次门控保护抓取；F 支路清障后再次靠近，并用新本地状态显式 `condition_check` 重查。
未提升为通用 C_pre 的条件仍能表达候选门控；结束前不加门控，未知不默认为真。

合并图不把所有视频边简单取并集。跨过被筛除实例的压缩关系须保留连续同视频路径，并标为推断投影。
显式允许的先后改支路仍须检查端点、正向守卫、未知真值和来源，不能绕过校验。
同视频多次出现保持独立；跨视频同类实例可共享语义技能。
每个来源 R 都保留，完整的局部成功依据源图记录，局部复核分歧可同时追溯。整体任务失败中的局部成功仍可支持相应技能方法。
通用七元组的 C_pre 和 C_const 可以归纳出有实例来源的候选内容。已验证的路由条件和候选描述分别存储，显示文字本身不会生成图上的门控。
预期后置效果的语义对齐与前置必要性使用不同判据：多个独立成功实例可支持相同局部效果，不要求为后置效果补造失败样本。

## 输出与边界

案例保存在 `cases/<视频名>_semantic_v3/`。
`knowledge/` 保存 `G_semantic.json`、`skill_catalog.json`、`skill_tuples.json`、`realizations.json`、`condition_decisions.json`、`semantic_rules.json`、`validation.json` 和工作台。
样本池、分组、视觉复核及筛选均保存独立 JSON；`sample_media/` 保存实际送入复核的媒体与时间轴，`learning_stages/` 和 `cache/` 保存各阶段及模型原始响应。

输出仍是带证据的模型候选。结构与回归通过不等于独立人工语义验收，也不证明普遍因果。
机器人检测器、控制器保持 `unbound`；本次三段验证不代表已用新流程重跑全部 16 段。

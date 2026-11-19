# 项目架构与阅读路线

项目按[原视频学习路线图](../task_picture/视频学习路线图.png)组织。完整入口 `tools/learn_video_knowledge.py` 的 `main()` 依次准备批次、调度单视频、调用跨视频学习、生成索引。只分析单段视频可从 `run.py` 进入同一个 `run_case()`。

|架构图节点|从哪里读|输入和输出|
|---|---|---|
|① 视频与任务输入|`single_video/pipeline.py` → `run_case()`|视频路径、可选背景／任务政策 → 媒体审计、视角和抽样帧|
|②a 意图、②b 动作并行|`pipeline.run_observation_branches()` → `single_video/stages/s02a_intent.py` 和 `single_video/stages/s02b_atomic.py`|同一视频上下文 → 意图假设和有时间戳的原子动作|
|③ 同步与单视频特例|`single_video/stages/s03_sync.py`、`case_scope_review.py`、`case_graph.learn()`|冻结的动作观察与意图 → 经同步、范围复核和校验的 `result.json`、`G_case.json`|
|④ 正反例条件|`cross_video/skill_sample_pool.py`、`semantic_selection.py`、`semantic_aggregation.learn()` 的 s10|多个 `G_case` 的局部实现 → 样本媒体、分相证据、正反例与条件结论|
|⑤ 语义规则|`semantic_aggregation.learn()` 的 s11|经校验的条件和证据 → 时序、约束与评价规则|
|⑥ 合并|`semantic_aggregation.learn()` 的 s12|来源路径与规则 → 语义任务节点、支路，以及每个技能的实现集合|
|⑦ 校验与导出、A 知识结果|`validate_graph()`、`cross_video_tuples.py` 的 s13、`export()`|合并图与来源引用 → `G_semantic.json`、技能七元组和验证记录|
|SVG 与工作台|`presentation/case_graph_render.py`、`semantic_skill_render.py`|已生成的语义图 → `G_case.svg`、跨视频 SVG 与工作台 HTML|

表中的源码相对于 `video2op/`。图中的 B（规划和使用）与 C（机器人反馈）是知识结果的下游。学习产物保留 `unbound` 执行接口。早期单视频阶段 `s04_conditions.py`、`s05_rules.py` 处理当前视频的分析上下文，跨视频对照发生在 s10 到 s13。

## 跨目录传递的数据

- **输入声明**由 `task_contract()` 保存为字典。`policy` 是可选任务政策对象，`description` 是可选文字背景，`origin` 标记用户声明，`sha256` 用于核对版本。
- **单视频**保存 `result.json`，其中 `atomic.atomic_actions` 是带 ID、起止时间和状态的原子动作列表，`operations` 是操作图，`case_graph` 与同目录 `G_case.json` 对应。`case_graph.nodes` 是局部技能列表，`relations` 记录技能关系，`task_outcome` 记录整段任务结果。局部 `outcome` 可为 `success`、`failure`、`not_executed` 或 `unknown`。
- **跨视频**以多个已保存的 `result.json` 为输入。`G_semantic.json` 中的 `skills` 是技能类别，`task_nodes` 是任务流程节点，`realizations` 是有来源的实现。`source_members` 形如 `C1:S1`，用案例 ID 和局部技能 ID 找回原证据。门控所走支路用 `gate_outcome`（T/F），现有证据能否证实条件用 `guard_truth`（T/F/U）。
- **技能七元组**包含角色 `X`、对象 `O`、前置条件 `C_pre`、过程约束 `C_const`、评价判据 `E`、期望后置状态 `C_post` 和实现 `R`。例如一次“抓取笔”的 `R` 通过 `operation_refs` 与 `atomic_refs` 关联原视频中的操作和动作。样例与证据边界见 [第 1 至 7 步说明](video_learning_stage1_7.md) 和 [v2 运行契约](video_learning_logic_v2.md)。

## 修改与排查

|要改什么|到哪里改|
|---|---|
|模型、抽样、超时、路径|`video2op/config.py`|
|意图或动作识别|`single_video/stages/` 的对应阶段与 `video2op/prompts/`|
|任务范围或通用证据规则|具体任务改 `tasks/*.json`，通用规则改 `contracts/learning_contracts.py` 或相应图校验函数|
|跨视频条件、规则与七元组|`cross_video/semantic_aggregation.py`、`cross_video/cross_video_tuples.py`|
|布局、节点标签或工作台页面|`presentation/`|

批次失败时先读批次 `run_manifest.json` 的 `status` 和 `error`，再沿对应视频目录的 `stages/` 查单视频阶段，或查 `knowledge/progress.json`、`knowledge/learning_stages/` 及 `knowledge/model_metrics.json`。改动后从项目根目录运行 [README 中的离线回归命令](../README.md)。

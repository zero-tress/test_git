# 任务意图层级与同步因果校验

2a 的 `intents` 保留多个总任务解释。每个总任务通过 `subtasks` 包含可以同时成立的子任务；同级子任务不是互斥候选，不按置信度排序，也不归一化评分。

- 总任务与子任务都有全局唯一 `id`、`statement`、独立 `confidence`。
- 子任务声明 `parent_intent_id`、`optional`、期望终态及证据。明确提供的任务分解必须作为待检验假设保留。
- 桌面取放可分为清障（可选）、抓取目标、搬运目标、放置目标。清障可以由靠近、抓取、搬运、释放多个操作实现；“先移瓶、后取笔”不证明清障是必要条件。
- 2a 不填尚未产生的操作id；3阶段建立子任务到已有操作的映射。

同步校验对每个总任务和子任务分别回答 `explains_graph`（意图能否解释操作图）、`achieves_intent`（操作图能否实现意图）、`state_consistency`（前后状态变化是否一致）。

`sync.intent_updates` 恰好覆盖总任务，`sync.subtask_updates` 恰好覆盖全部子任务。子任务更新包含源图 `node_refs`、`atomic_refs`、观察状态、独立评分、三项检查及理由。三问不能重复；引用必须有效且在本子任务范围内；肯定判定需要观察证据。错误或不完整的层级更新被隔离，不修改评分。

观察状态：
`observed` 表示已观察相关操作，并不保证意图完成；
`partially_observed` 表示部分观察；
`not_observed` 保留未观察子任务；
`not_applicable` 仅适用于可选且无需执行的子任务；
`unknown` 表示待确认。未观察和不适用子任务不得绑定已发生操作。

评分写回 `confidence`，同时保留 `confidence_before_sync`、`confidence_after_sync`、`sync_checks`、`sync_reason`。重复建图不覆盖初始分数。总任务评分由证据综合判断，不取子任务平均值；评分描述目的解释，不是完成概率或校准概率。

语义图 `x-meta.intent_hierarchy` 导出完整层级及评分，操作拆分/合并后，通过 `learning_alignment.source_to_final` 映射到最终图 `N*` 节点，同时保留原节点引用和原子动作证据。旧的平铺候选仍兼容；只有单一旧候选可应用旧的标量更新，层级意图禁止这种回退。

`operations.svg` 和交互 `workbench.html` 展示每个总任务、子任务及“初始 → 因果校验后”评分，子任务标明可选性、观察状态及对应操作。HTML可展开三问及证据。没有校验结果时显示“待校验”，不制造默认分数。

服务器现有 conda study 环境中的用法（模型访问需已获网络授权）：

```bash
conda run -n study python -B tools/review_intent_hierarchy.py \
  output/意图拿笔/抓取1_semantic_v3/result.json \
  output/runs/新的意图校验 \
  --description '桌面取放红色笔；子任务：清障（可选）、抓取目标、搬运目标、放置目标'
```

工具重新观看原视频推断意图，复用已保存操作及状态证据完成同步校验；不重复抽取动作，不改写原案例。输出目录必须是新的。保留模型缓存、阶段结果、指标及来源哈希；不向数据库写入、不修改共享技能库、不重启服务。

离线回归：
`conda run -n study python -B -m pytest -q -p no:cacheprovider`。

# 输出目录

从 [index.html](index.html) 进入当前结果。

|路径|角色|处理原则|
|---|---|---|
|current/|指向 semantic_learning_20261111_delivery/ 的稳定入口|浏览当前交付|
|semantic_learning_20261111_delivery/|当前交付原件；知识、16案例、留出报告、模型验证|保留原始字节|
|runs/|后续运行|每次独立目录；确认替代关系后再清理|
|semantic_16_20261107/|兼容链接 → ../archive/experiments/semantic_16_20261107|当前归纳读取的原始案例与独立审计|
|抓取2_semantic_v3/|兼容链接 → ../archive/fixtures/抓取2_semantic_v3|历史模型验证证据的来源路径|
|_baseline_20261111/|兼容链接 → ../archive/experiments/_baseline_20261111|冻结基线；验收比较使用|
|semantic_learning_20261111_final/|兼容链接 → ../archive/experiments/semantic_learning_20261111_final|旧知识版本的来源路径，保留可检索证据|

当前交付内部：
- knowledge_development/：13段开发集，review.html 为浏览页。
- knowledge_all_16/：16段事后展示，cases/ 下是单视频结果。
- holdout_observations/：02/06/14独立观察。
- model_validation/：3段样例的真实模型调用证据。
- verification_summary.json、holdout_evaluation.json、checklist_38.json、delivery_validation.json：验收材料。

本次移除了28项历史输出和临时工作目录。逐项摘要见 docs/reports/项目整理_20261112.md；逐文件SHA256清单在 archive/maintenance/cleanup_20261112.json。清理不会自动更新 current；新交付验收通过后再显式调整链接。

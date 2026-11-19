# 归档材料

|目录|内容|保留原因|
|---|---|---|
|experiments/semantic_16_20261107/|16段原始案例、模型独立审计、源码快照等|当前归纳和审计仍读取|
|experiments/_baseline_20261111/|冻结实验副本|验收比较，文件权限与内容保持原样|
|experiments/semantic_learning_20261111_final/|前一轮知识与案例|knowledge_base 中的旧版本仍引用|
|fixtures/抓取2_semantic_v3/|历史抓取样例|当前模型验证驱动仍使用|
|source_backups/|历史源码与少量结果快照|含历史验收所引用的证据|
|baselines/|2026-11-17 与 11-18 整改基线|保留源码指纹、差异与验证记录|
|logs/|此前运行日志|历史排查证据|
|tools/|16个旧版一次性源码修改脚本及实验驱动|仅供追溯；不是当前运行入口|
|maintenance/|清理前逐文件大小与SHA256、保留证据校验清单|核对本次整理|

云服务器上的 `source_backups/` 和 `baselines/` 是兼容链接。实体目录位于项目旁的 `/home/wj/codex-workspace/videostudy_operation_history_20261119/archive/`，原验收证据和历史报告可经旧路径访问。独立的搬移方式细分版本也保存在该外部目录的 `revisions/` 下，原路径继续可用。

experiments 的三个兼容链接及 fixtures 的抓取样例兼容链接保留在 output 下。归档实验及源码快照不批量重写路径、JSON或内容哈希。

archive/tools 中的历史脚本按原样保存，其相对目录计算仍对应原来的 tools 位置；不要直接从归档执行。需要重现旧版本时，先按历史版本建立隔离副本并核对依赖。当前工具留在项目 tools/。

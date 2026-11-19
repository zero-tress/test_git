# 工具索引

以下脚本在项目根目录使用云端 conda `study` 环境运行。完整流程从 `tools/learn_video_knowledge.py` 开始。

|用途|工具|
|---|---|
|单视频分析|`run.py <视频>`，保存单视频结果与特例图|
|完整学习|`tools/learn_video_knowledge.py`，先生成单视频特例图，再跨视频归纳|
|已有特例图归纳|`tools/learn_semantic_graph.py`，输入多个结果文件，运行 s10 到 s13|
|验证批次|`tools/verify_video_knowledge.py`，核对完成批次的来源、图和媒体|
|旧版跨视频归纳|`learn.py`，生成旧版知识或双流程学习结果|
|重建两套知识与留出解释|finish_semantic_learning.py；默认写 output/runs/ 下的新目录|
|验收新交付与账本|validate_semantic_delivery.py --out <新实验目录>；会更新 eval 和报告|
|导入独立任务观察与参考标注|import_task_observations.py；读取保留的16段实验，重写 eval 两个输入文件|
|真实模型候选/时序样例验证|run_model_validation.py --out <新目录>；需要网络，默认独立目录|
|技能七元组与版本检索|project_skill_tuple.py、kb_query.py|
|接口与谓词核验|verify_contract.py、check_bindings.py、check_prior.py|
|留出解释、聚类、模式验证|holdout_check.py、cluster_instances.py、verify_patterns.py|
|已有案例迁移与展示|migrate_learning_v3.py、render_case.py、export_workbench.py、rebuild_semantics.py|
|单案例/批量运行与复核|run_case_review.py、run_goal_review_batch.py|
|快速查看与汇总|show_case.py、show_detail.py、stats.py、summarize_cases.py、check_html.py|
|模型/性能排查|probe_vlm.py、benchmark_operation.py|
|旧契约部署辅助|install_contract.py；使用前核对目标路径|
|旧图与校验器自检|selftest.py，离线检查旧版时序逻辑、DAG 和 SVG|

旧模型探针 `probe_vlm2.py`、`show_probe.py` 和一次性基线生成器 `freeze_baseline.py` 的源码保存在云端历史目录 `/home/wj/codex-workspace/videostudy_operation_history_20261119/retired_tools/`，供追溯。

真实模型工具、配置修改工具和执行侧安装工具应按实际任务与服务器规则调用。本次整理未运行它们。

2026-10 的16个一次性补丁和专用实验脚本已移至 archive/tools/，只用于追溯，不作为当前操作入口。通用的 migrate_learning_v3.py 仍被 render_case.py 使用，因此保留。


## 跨视频归纳新增工具

- finish_cross_video_generalization.py：以已有开发/留出知识和技能切片构建新交付，不写共享知识库。
- review_cross_video_samples.py：授权后仅访问现有本机模型端点，独立保存3组样例及失败记录。
- attach_cross_video_reviews.py：附加模型意见、来源帧和冲突，不自动升级人工/因果状态。
- verify_cross_video_delivery.py：验证原数据、切片、路径重建、R引用、HTML/SVG/JavaScript及回归。
- 技能切片入口：python -B -m video2op.skill_clips；使用--help查看必需参数。


## 双流程学习工具

- analyze_pen_goal_samples.py：通过正常全流程分析拿笔样例，显式授权后仅访问现有8032。
- review_contrastive_skills.py：核验指定案例的局部技能与给定整体目标，保留原始失败及无效因果意见。
- verify_two_track_delivery.py：核对两条学习流程的来源、范围、七元组、切片解码与页面引用。
- learn.py新增--goal、--target-category、--local-reviews；两条流程写入输出目录的learning_tracks/。


## 16段全量重分析

- reanalyze_sixteen_8032.py：中性文件名、完整视频模型分析、独立任务审计和局部技能复核；支持分批与本轮断点续跑，限定现有8032。
- build_reanalysis_sixteen.py：从本轮新观察重建单视频切片、开发/留出/全量双流程视图，并在学习完成后对照旧标注。

# 工具索引

主入口是项目根目录 run.py（视频分析）与 learn.py（跨视频归纳）。以下脚本均在项目根目录通过服务器 conda study 运行。

|用途|工具|
|---|---|
|重建两套知识与留出解释|finish_semantic_learning.py；默认写 output/runs/ 下的新目录|
|验收新交付与账本|validate_semantic_delivery.py --out <新实验目录>；会更新 eval 和报告|
|导入独立任务观察与参考标注|import_task_observations.py；读取保留的16段实验，重写 eval 两个输入文件|
|真实模型候选/时序样例验证|run_model_validation.py --out <新目录>；需要网络，默认独立目录|
|技能七元组与版本检索|project_skill_tuple.py、kb_query.py|
|接口与谓词核验|verify_contract.py、check_bindings.py、check_prior.py|
|留出解释、聚类、模式验证|holdout_check.py、cluster_instances.py、verify_patterns.py|
|已有案例迁移与展示|migrate_learning_v3.py、render_case.py、export_workbench.py、rebuild_semantics.py|
|单案例/批量运行与复核|run_case_review.py、run_goal_review_batch.py|
|快速查看与汇总|show_case.py、show_detail.py、show_probe.py、stats.py、summarize_cases.py、check_html.py|
|模型/性能排查|probe_vlm.py、probe_vlm2.py、benchmark_operation.py|
|旧契约部署辅助|install_contract.py；使用前核对目标路径|
|一次性冻结基线|freeze_baseline.py；已有基线不需再次运行|
|历史自检与配置修改|selftest.py、configure_cloud_network.py、configure_cloud_wait.py；不属于当前主运行流程|

真实模型工具、配置修改工具和执行侧安装工具应按实际任务与服务器规则调用。本次整理未运行它们。

2026-10 的16个一次性补丁和专用实验脚本已移至 archive/tools/，只用于追溯，不作为当前操作入口。通用的 migrate_learning_v3.py 仍被 render_case.py 使用，因此保留。


## 跨视频归纳新增工具

- finish_cross_video_generalization.py：以已有开发/留出知识和技能切片构建新交付，不写共享知识库。
- review_cross_video_samples.py：授权后仅访问现有本机模型端点，独立保存3组样例及失败记录。
- attach_cross_video_reviews.py：附加模型意见、来源帧和冲突，不自动升级人工/因果状态。
- verify_cross_video_delivery.py：验证原数据、切片、路径重建、R引用、HTML/SVG/JavaScript及回归。
- 技能切片入口：python -B -m video2op.skill_clips；使用--help查看必需参数。

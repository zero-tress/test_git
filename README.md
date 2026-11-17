# video2op：视频语义学习

从人体操作视频提取带目标、条件、时序和证据的语义操作图，再跨视频归纳技能与实现方式。项目程序和测试均在云服务器 conda `study` 环境运行。

## PostgreSQL 可视化预览

访问 [视频知识工作台](http://192.168.137.102:18773)：浏览操作图、SVG/HTML原件、技能JSON和表结构草案。当前使用独立预览库，须用 videostudy_app 账号登录，可通过 VS Code 端口转发访问；正式表结构待确认。部署和验证见 [knowledge_portal/README.md](knowledge_portal/README.md)。

## 从哪里看结果

**统一入口：[output/index.html](output/index.html)**；稳定目录 `output/current/` 指向本轮单视频布局交付；旧交付保留在原目录。

- [13 段开发集知识](output/current/knowledge_development/review.html)：用于归纳。
- [全部 16 段展示](output/current/knowledge_all_16/review.html)：含参考标注的事后展示。
- [验收报告](docs/reports/按两张图完成任务验收报告.md)：能力、证据缺口和 38 项账本。
- [本次整理记录](docs/reports/项目整理_20261112.md)：清理范围、归档位置与验证结果。

已有交付的结构检查为 16/16 通过；最近一次离线回归为 607 项通过、1 项因本机缺少 Node `jsdom` 无法执行（`tests/test_single_actor_v4.py` 的点击交互测试）。结构通过不代表语义结论全部得到实证。局部效果、复杂时序、因果条件仍有待复核项；参数、检测器与执行器接口为 `unbound`，尚未验证机器人执行。

## 目录约定

|目录 / 文件|用途|
|---|---|
|`run.py`|单视频或批量视频分析入口|
|`learn.py`|读取已保存案例，跨视频归纳技能|
|`video2op/`|运行源码；stages 为分析阶段，prompts 为提示词，schemas 为契约|
|`tools/`|当前维护、归纳、检索与验证工具，见 [工具索引](tools/README.md)|
|`tests/`|离线回归测试；兼容旧接口的测试仍保留|
|`data/`|原始视频、16 段命名标注与标注数据|
|`eval/`|评估划分、独立模型观察、参考标注和验收账本|
|`knowledge_base/`|按技能与内容版本保存的知识；旧版本仍用于检索与溯源|
|`output/current/`|最新交付的稳定入口|
|`output/runs/`|后续运行的新结果，按运行时间分目录|
|`docs/`|当前报告、历史设计说明和维护提示词，见 [文档索引](docs/README.md)|
|`archive/`|仍需溯源的实验、基线、源码备份、旧日志与一次性脚本|

`output/` 中三个旧实验名及一个旧抓取样例名是兼容路径，实际材料在 `archive/`。评估和版本知识库仍引用它们，不要按旧日期删除。详见 [输出说明](output/README.md)。

## 常用命令

在服务器项目根目录 `/home/wj/codex-workspace/videostudy_operation` 运行：

```bash
# 离线回归，不调用模型
conda run -n study python -B -m pytest -q -p no:cacheprovider

# 查看命令参数
conda run -n study python -B run.py --help
conda run -n study python -B learn.py --help

# 单视频：默认另建 output/runs/<运行时间>/，不写入当前交付
conda run -n study python -B run.py data/抓取2.mp4

# 可选文字背景与显式输出目录
conda run -n study python -B run.py data/抓取2.mp4 --description 背景.txt --output-root output/runs/新实验

# 从保留的 16 段观察重新归纳；默认新建带时间的目录
conda run -n study python -B tools/finish_semantic_learning.py

# 验证新归纳结果；会写入指定实验及 eval 中的验收报告
conda run -n study python -B tools/validate_semantic_delivery.py --out output/runs/新实验

# 技能版本检索与单案例契约检查
conda run -n study python -B tools/kb_query.py skill_relocate_and_release
conda run -n study python -B tools/verify_contract.py output/current/knowledge_all_16/cases/01_video_01_semantic_v3
```

`run.py` 与真实模型验证需要连接已配置的模型服务；按服务器执行规则另行授权网络。本次整理只执行离线检查。背景文字只参与意图上下文，不当作已观察成功的证据。显式指定已有输出目录时，单视频缓存仍按原逻辑复用；新的归纳与模型验证要求空目录。

## 源码阅读路线

1. `pipeline.py` 调度视频抽样、关键帧、阶段分析和导出；`config.py` 集中配置。
2. `stages/` 分别处理视角、意图、原子动作、任务、关联、同步、条件、规则、校验和目的范围。
3. `semantic.py`、`single_actor.py`、`grasp_preparation.py`、`arm_hand.py` 构建单视频语义图。
4. `knowledge.py`、`condition_induction.py`、`temporal_learning.py` 归纳跨视频技能与候选条件。
5. `skill_tuple.py`、`semantic_interface.py`、`knowledge_base.py` 导出七元组、待绑定接口和版本知识。
6. `holdout.py`、`evidence.py`、`semantic_checks.py` 核验留出解释、证据和结构；`render.py`、`workbench.py` 生成展示。

完整旧设计保存在 [历史 README](docs/history/README_before_20261112.md)，其中版本数字与旧输出路径属于对应历史阶段。


## 技能切片与跨视频归纳（2026-11-14）

本轮结果入口：[跨视频归纳交付](output/runs/cross_video_20261114/delivery/index.html)；
[技能与动作片段](output/runs/cross_video_20261114/skill_clips/index.html)；
[实施报告](docs/reports/跨视频切片与归纳_实施报告_20261114.md)。
当前稳定交付未切换；切片边界、分支条件和模型复核状态分别保留。

服务器study环境常用命令：

~~~bash
# 直接复用已保存分析，导出技能/动作视频，不调用模型
conda run -n study python -B -m video2op.skill_clips --knowledge output/current/knowledge_all_16/knowledge.json --out output/runs/skill_clips_新实验

# 已导出切片在中断后可使用同一输入与参数显式 --resume；输入变化会拒绝复用
# 分析新视频并导出片段：运行模型前须已取得网络授权
conda run -n study python -B run.py data/抓取2.mp4 --export-clips

# 对保存案例归纳并关联切片；未使用 --refresh-scope 时不调用模型
conda run -n study python -B learn.py --inputs output/current/knowledge_development/cases/01_video_01_semantic_v3/result.json --out output/runs/learning_新实验 --clip-manifest output/runs/cross_video_20261114/skill_clips/manifest.json

# 对冻结知识构建支路/功能归纳新交付，不改写当前交付或共享版本库
conda run -n study python -B tools/finish_cross_video_generalization.py --clips output/runs/cross_video_20261114/skill_clips/manifest.json --out output/runs/generalization_新实验

# 完整离线验证：源文件、片段、路径、链接、测试与静态检查
conda run -n study python -B tools/verify_cross_video_delivery.py --delivery output/runs/cross_video_20261114/delivery --clips output/runs/cross_video_20261114/skill_clips/manifest.json
~~~

真实模型复核脚本为tools/review_cross_video_samples.py。必须先获得仅访问现有本机模型服务的网络授权，再使用--allow-local-model；仅处理3个代表样例，失败重试保留独立记录。tools/attach_cross_video_reviews.py只附加候选证据，保持冻结知识与原片段不变。新导出片段保留源分辨率和帧率；已有media.make_clip仍负责供模型使用的压缩窗口。


## 单视频布局与统一技能大纲（2026-11-15）

[当前案例总入口](output/current/index.html) · [8032重跑的抓取2](output/抓取2_semantic_v3/workbench.html) · [统一技能库索引](skill_library/index.json)

单视频目录保留result.json、operations.svg、workbench.html、skill_instances.json和clip/。
不再生成report.html、semantic_graph.yaml、action_catalog.json。
clip目录内的视频命名为“原视频名_动作_序号_分析时间.mp4”；sequence.json记录原动作时间、含上下文的片段时间、序号、先后/重叠关系和证据来源。分析时间按Asia/Shanghai记录。

技能定义只在skill_library中维护：action_catalog.json是项目动作与技能大纲，skill_templates.json是声明模板，learned_skill_catalog.json是开发集跨视频归纳结果。它们都保留X、O、C_pre、C_const、E、C_post、R七字段。单视频的skill_instances.json引用模板，并保存本视频的对象、条件与证据。two_table_skill_knowledge.json已作为只读参考快照保存在references/。

~~~bash
# 新视频分析默认导出自己的clip目录；需先取得模型网络授权
conda run -n study python -B run.py data/抓取2.mp4

# 只需要时间索引时可显式跳过MP4导出
conda run -n study python -B run.py data/抓取2.mp4 --no-clips

# 跨视频归纳自动读取各单视频的clip/sequence.json，输出skill_catalog.json
conda run -n study python -B learn.py --inputs output/current/knowledge_development/cases/01_video_01_semantic_v3/result.json --out output/runs/learning_新实验

# 验证本轮格式、七元组引用、切片文件与旧证据保留
conda run -n study python -B tools/verify_case_layout.py --out output/current --live-case output/抓取2_semantic_v3
~~~

本轮没有改动机器人执行绑定、知识工作台数据库表或8032服务。模型的预期条件和视频观察仍分别记录，统一模板不代表检测器已经绑定或因果关系已经证实。


## 同目标任务图与同类技能切片（2026-11-15）

[本轮入口](output/learning_tracks_current/index.html) · [实施报告](docs/reports/双流程学习_实施报告_20261115.md) · [当前方案](docs/plans/prd-contrastive-skill-learning.md) · [两条学习视图的统一索引](skill_library/learning_tracks/index.json)

同目标任务图以“拿起笔”为主样例，比较抓取1、抓取2、抓取3的完整路径，形成3个候选实现R。
同类技能切片依据局部意图和效果分类，分别记录成功、失败、未执行、未知，整体任务结果不会覆盖局部技能。
七元组X、O、C_pre、C_const、E、C_post、R继续保留。任务图因果校验、对象/同义状态对齐与分支条件均可追溯到源观察。

本轮导出21个局部技能视频视图；7个抓取实例中3个为模型成功候选、4个未知，没有真实抓取失败样本。
移瓶/移杯是否构成必要清障、分支适用条件及普遍因果仍未证实。抓取3的尾部解码警告单独保存。

~~~bash
# 对已保存案例进行两条流程的学习；不需要再次调用模型
conda run -n study python -B learn.py --inputs <多个result.json> \
  --goal acquire_object --target-category pen --local-reviews <results.json> --out output/runs/新的学习目录

# 验证来源、七元组、实际MP4、路径、链接与脚本
conda run -n study python -B tools/verify_two_track_delivery.py --out output/runs/新的学习目录
~~~

本轮474项回归通过。历史13段开发与3段留出另存，旧output/current保持原交付。


## 16段视频8032全量重分析（2026-11-15）

[最新结果](output/current/index.html) · [重分析报告](docs/reports/16段视频_8032重新分析_20261115.md) · [方法分歧](output/current/reference_comparison.json)

16段重新经过现有8032的完整分析，输出70个动作切片及双流程知识。任务结果为12成功、2失败（04/12）、2未执行（03/11）；09目标成功且过程掉落。16段结构检查与481项回归通过。
01/05/06/12/15的方法判断与既有标注存在分歧，保留为待复核项。局部技能、任务成败和过程异常分别存储，七元组保持不变。
本轮原件位于output/runs/reanalysis_16_8032_20261115/；原视频和历史结果均保留。

~~~bash
# 本轮批处理；需已取得仅访问现有本机8032的授权
conda run -n study python -B tools/reanalyze_sixteen_8032.py --out output/runs/新的16段实验 --ids 01 02 03 04 --workers 4 --allow-8032
# 中断后显式--resume，仅复用该新实验内已完成的阶段
# 模型阶段完成后离线重建；旧成败参考只用于汇总后的比较
conda run -n study python -B tools/build_reanalysis_sixteen.py --run output/runs/新的16段实验
~~~


## 模型生成的成功流程合并图（2026-11-16）

[意图拿笔工作台](output/意图拿笔/workbench.html) · [操作图SVG](output/意图拿笔/operations.svg) · [实现与运行说明](docs/reports/成功流程归纳与模型合并图_20261116.md)

本批次对抓取1、2、4进行成功流程筛选与语义支路合并，失败尝试保留为抓取反例。新增两阶段学习由现有8032部署模型给出节点、条件、七元组和正反例判断；宿主校验、裁剪、保存与绘图。结束前没有门控。模型不返回有效结果时停止，不以代理分析或固定动作图补全。

本批次补充：[靠近步骤与抓取前门控保留](docs/reports/靠近步骤与抓取前门控保留_20261116.md)。合并图按状态保留靠近的不同出现次数，抓取只能通过前置条件成立分支。

## 总任务与子任务意图

2a 支持总任务及多个共存子任务，3阶段分别完成三项因果校验并更新两层评分。SVG/HTML 展示初始与更新后的置信度、子任务操作映射和观察状态。见 [意图层级说明](docs/intent_hierarchy.md)。


## 第1—7步：特例知识与两层语义操作图（2026-11-17）

本轮入口：[意图拿笔2](output/意图拿笔2/index.html)。3 段视频得到 5 个语义技能、10 个实例、7 条语义关系，0 个未分配实例；验收记录在 `output/意图拿笔2/_verification/verify_20261117.json`。

单视频保留 operations.svg / workbench.html，新增 Qwen 生成的 G_case.json 与 G_case.svg。G_case.svg 沿用 operations.svg 的图形语言：圆形技能节点、前置条件门控菱形、实线/虚线关系、悬停详情与图例；每个节点下方直接展开 `X · O · C_pre · C_const · E · C_post · R` 七元组，E 拆为完成判据、过程约束与实现适用性，R 保留操作与原子动作引用；图底部为每个 R 画出操作节点的实现子图，`maintain_until` 以绿色虚线“保持→”标出。

时序不再降维成一条顺序链。本轮的机制约定：
- `relations` 新增 `maintain_until`（前段效果持续到后段开始），不参与前置环检测；
- 操作层的 `parallel`/`maintain_until`/`alternation`/`branch`/`synchronization` 必须向上映射：跨技能则给出同类型技能关系，属于同一实现则在该技能的实现子图保留，实在无法映射则逐条写入 `unmapped_relations` 并说明；
- 任何被模型观察到、却未进入任何 R 的操作必须列入 `excluded_operations` 并说明理由（状态已满足与推断操作自动豁免），避免“靠近”这类必要步骤从实现里消失。

因果次序也写进了提示词与校验：手必须抵达目标附近才能抓取。若靠近与抓取是两个可分辨的原子动作段，必须把“靠近”建成独立技能并给出 observed_order 前置；遮挡时清障必须先于靠近与抓取；没有靠近动作证据时不得虚构。

跨视频依次学习正反例条件、语义规则，再做支路和功能合并。s12 的宿主一致性校验本轮做了四处收敛修正：跨视频规则允许引用归属其他技能的同动作实例（要求成员有交集，并在 validation 记录覆盖率）；无法归类的实例必须显式列入 `unassigned_members` 并说明理由；同一动作同时服务两个目的时，用 `shared_members` + `shared_reason` 声明共享；契约清单前置到模型输入，并给出每条实例的名称、局部结果与实现引用。提示词更新后可用 `--resume --refresh-prompts` 续跑，已完成实例可用 `--refresh-case-graph` 只重跑 s09 语义层，不重跑抽样与意图阶段。

模型客户端固定到8032的qwen3.8-27b，失败不生成替代结论。运行及数据契约见 [视频学习第1—7步](docs/video_learning_stage1_7.md)。完整入口为 tools/learn_video_knowledge.py，旧结果及别名保留。

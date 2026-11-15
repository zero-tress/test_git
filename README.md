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

已有交付的结构检查为 16/16 通过；本轮回归为 474 项通过。结构通过不代表语义结论全部得到实证。局部效果、复杂时序、因果条件仍有待复核项；参数、检测器与执行器接口为 `unbound`，尚未验证机器人执行。

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

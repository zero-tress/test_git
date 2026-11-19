# 视频操作知识学习

从人体操作视频提取带证据的单视频特例图 `G_case`，再结合多个特例学习条件、时序规则、技能七元组和不同实现，生成 `G_semantic`。项目在云服务器 `wj@192.168.137.102` 的现有 conda `study` 环境运行。

## 从哪条命令开始

|要做的事|入口|主要产物|
|---|---|---|
|分析单段新视频|`run.py <视频>`|`result.json`、`G_case.json`、单视频工作台|
|分析一批视频并学习跨视频知识|`tools/learn_video_knowledge.py`|各视频的 `G_case`、跨视频 `G_semantic`、批次索引|
|用已有单视频结果重新归纳|`tools/learn_semantic_graph.py`|跨视频语义图、技能目录、七元组、验证记录|
|核对已完成的批次|`tools/verify_video_knowledge.py`|来源、媒体、关系和链接验证报告|
|复用旧版知识或双流程学习|`learn.py`|旧版知识和同目标／同类技能对照产物|

## 按架构找代码

```text
video2op/
├── single_video/        ① 视频输入 → ② 双分支学习 → ③ 同步 → G_case
│   ├── pipeline.py      串联输入、并行分支、同步、校验和导出
│   ├── stages/          按步骤编号定位意图、原子动作、同步和单例校验
│   ├── case_graph.py    s09 特例图生成、证据校验和导出
│   └── case_scope_review.py / case_outputs.py
├── cross_video/         ④ 正反例条件 → ⑤ 语义规则 → ⑥ 合并 → ⑦ 校验
│   ├── semantic_aggregation.py
│   ├── skill_sample_pool.py / semantic_selection.py
│   └── cross_video_tuples.py
├── contracts/           单视频和跨视频共用的任务、证据与版本契约
├── presentation/        特例图、跨视频图与工作台展示
├── config.py            路径、模型、超时、抽样与阈值
└── prompts/ · schemas/  提示词与数据契约
```

共享媒体、模型客户端、操作图工具和旧版学习模块仍可从 `video2op/` 中找到。根级旧导入和 `video2op/stages/` 下的兼容入口指向相同实现。按图找函数、字段和调试记录见 [项目架构与阅读路线](docs/project_architecture.md)。

## 在服务器上运行

在 `/home/wj/codex-workspace/videostudy_operation` 执行。日常使用已有 `study` 环境，其依赖包括 Python、NumPy、Requests、PyYAML、FFmpeg／FFprobe，开发测试使用 pytest。可用下面的离线命令检查环境和入口。模型分析使用项目已配置的 8032 服务。

```bash
conda run -n study python -B -m pytest -q -p no:cacheprovider
conda run -n study python -B tools/learn_video_knowledge.py --help
conda run -n study python -B tools/learn_semantic_graph.py --help

# 单视频
conda run -n study python -B run.py data/抓取2.mp4

# 完整批次，选择一个新输出目录
conda run -n study python -B tools/learn_video_knowledge.py \
  --videos data/抓取1.mp4 data/抓取2.mp4 data/抓取4.mp4 \
  --out output/runs/拿笔新批次 \
  --graph-requirements tasks/pick_pen_graph_requirements_v2.json --allow-8032

# 离线核对完成的批次
conda run -n study python -B tools/verify_video_knowledge.py \
  --out output/runs/拿笔新批次 --report output/runs/拿笔新批次/verification.json
```

一般任务可以省略 `--graph-requirements`。流程、输出及恢复选项见 [视频学习逻辑 v2](docs/video_learning_logic_v2.md)。源码指纹包含文件路径，本次目录调整后，用新版代码继续旧批次时须显式传 `--resume --refresh-prompts`，随后按原规则检查输入和阶段缓存。

## 查看结果与历史记录

- 新批次从运行目录下的 `index.html` 打开。已发布结果可从 [输出索引](output/index.html) 和 [稳定交付](output/current/index.html) 查看。
- 资料由 `data/`、`eval/`、`skill_library/`、`knowledge_base/` 和 `archive/` 管理。详见 [归档说明](archive/README.md) 和 [输出说明](output/README.md)。
- [视频知识工作台](http://192.168.137.102:18773) 提供已有结果的登录浏览，部署说明见 [knowledge_portal](knowledge_portal/README.md)。
- [工具索引](tools/README.md) · [文档与历史交付索引](docs/README.md) · [当前验收报告](docs/reports/按两张图完成任务验收报告.md)

## Python 文件整理记录

本次整理后，主项目目录中的 `.py` 实体文件从 774 个减到 276 个，统计时不跟随符号链接。481 个历史副本移至 `/home/wj/codex-workspace/videostudy_operation_history_20261119/`，下表中的旧路径仍可在云服务器上访问。

|项目内旧路径|保留用途|
|---|---|
|`archive/source_backups/`|保存历史源码和验收证据，验收脚本仍从这里读取燕麦杯样例|
|`archive/baselines/`|对照整改前后的源码、差异和验证记录|
|`revisions/relocation_methods_20261118/`|单独运行推、拉、搬运细分版本，保留自己的命令入口和补丁|

旧探针脚本 `probe_vlm2.py`、`show_probe.py` 和一次性基线生成脚本 `freeze_baseline.py` 已从当前工具目录退役，原件保存在同一历史目录的 `retired_tools/`。14 个阶段兼容文件已收拢到 `video2op/stages/__init__.py`，旧导入路径仍可使用。

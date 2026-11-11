# 当前交付：视频语义学习（2026-11-11）

当前项目目录：/home/wj/codex-workspace/videostudy_operation；程序与测试均在服务器 conda study 环境运行。

- 当前回归：394 项通过；16 段每段12项结构检查无失败，待复核项保留。
- 标准技能视图：skill_tuples.json；完整知识与审计：knowledge.json。
- constraints.json / evaluators.json / effective_conditions.json 保留判据、来源和候选状态；case_predicate_bindings.json 关联案例与跨视频谓词。
- 给定任务、模型推测意图、局部子任务分别保存。任务 outcome 支持 success / failure / not_executed / unknown；过程掉落单独记录，未标注异常保持 unknown。
- 语义层额外导出 execution_policy.yaml、program.json，均为 unbound。tools/verify_contract.py 对当前schema只检查结构与引用，不运行机器人。
- 两套知识用途分开：knowledge_development 只用13段；knowledge_all_16 是含参考标注的事后展示。02/06/14 的独立观察另存 holdout_observations。
- 最新交付目录：output/semantic_learning_20261111_delivery。完整入口和未完成实证见该目录及根目录《按两张图完成任务验收报告.md》。
- 支持视角分类和单机位视频；尚未覆盖多视角联合输入。行为子树、机器人执行和反馈闭环属于本轮范围外。

在项目根目录运行：

```bash
conda run -n study python -B -m pytest -q -p no:cacheprovider
conda run -n study python -B tools/import_task_observations.py
conda run -n study python -B tools/finish_semantic_learning.py --out output/<新的实验目录>
conda run -n study python -B tools/verify_contract.py output/<实验>/knowledge_all_16/cases/<案例>
conda run -n study python -B tools/kb_query.py skill_relocate_and_release
conda run -n study python -B run.py data/<视频>.mp4 --description <UTF-8背景文件> --output-root output/<新目录>
```

背景文字只影响意图上下文，不作为已观察成功的证据。无description时保留原请求内容。

以下保留各历史阶段说明；版本数字属于相应历史记录，当前行为以本节、代码和最新验收报告为准。

---

> **2026-11-02：按子任务目的与效果跨视频归纳。**
> 意图与动作观察独立并发，条件/评价规则按来源映射到最终图；增加对象任务族、实现分支、真实观察对照统计及视频解码审计。
> 新入口：`python learn.py --inputs <案例目录...> --out <新目录>`。运行、效果边界与四视频验证见 [语义学习升级_20261102.md](语义学习升级_20261102.md)。
> 最新四视频归纳：`output/goal_effect_knowledge_20261102_final/review.html`；规则与效果均保留候选/待复核状态。

> **2026-10-22：视频整体理解＋关键状态帧＋局部复查已接入。**
> 保留视频输入，补充运动补偿后的前后状态帧；开度、支撑或动作证据不明时执行有预算的局部复查。
> 输入帧、真实复查证据、推断和冲突分别记录；工作台可查看关键帧与复查证据。
> 使用原 run.py 入口即可。配置、产物、来源与验证范围见 [关键状态帧与局部复查_20261022.md](关键状态帧与局部复查_20261022.md)。

> **2026-10-22：单执行主体语义图 v4。** 一个操作节点只有一个主体，X.subject 与唯一的 X.parts 一致。
> 主图直接展示靠近、打开、抓取、移动、释放、撤回；靠近与打开并行，合取门控后抓取。
> 握持用跨节点关系延续到释放开始前，不新增保持节点。语义并行独立于底层资源互斥。
> 圆形节点文字居中，点击展开七元组，图面不显示时间。既有输出目录名称继续保留。
> 详见 [单主体语义图升级_20261022.md](单主体语义图升级_20261022.md)。以下早期说明与此冲突时以本条为准。

> **2026-10-22：修正显示与执行主体。** 操作图恢复修改前的形式，点击节点在侧栏查看七元组。
> X 保留操作者及原有整体/左右臂/左右手，不替换成机器人系统名称。
> “整体”仅用于垂直上升、下降和水平方向移动；持续状态仍为约束，无保持节点。
> 已离线修复本次燕麦杯结果，直接重新打开其 workbench.html 即可。

> **2026-10-21：语义学习 v3 已启用。** 新结果输出到 `output/<视频名>_semantic_v3/`。
> 动作使用受控词表；捡起/抬起/举起收敛为抓取；无保持动作类型，持续状态写入 C_const。
> 主交付为 `semantic_graph.yaml`；`operations.svg` 沿用原来的圆形操作节点、菱形门控与黑色连线，工作台点击节点才展开七元组。
> 当前已核验抓取/搬运/放置模板；其他操作缺模板时明确报缺口，不能默认映射移动。
> 运行、迁移、兼容和测试见 [语义学习升级_20261021.md](语义学习升级_20261021.md)。下文旧设计仅供历史参考。

<!-- operation-v2-current -->
> **当前版本 1.1.0（2026-10-11）**：执行器为整体、左臂、右臂、左手、右手。
> 走路抽象为向目标移动，下蹲/起身为下降/上升；不再生成下肢支撑节点。
> 新分析输出到 output/<视频名>_operation_v2/，保留旧结果。
> 已完成两例实测：同模型无缓存请求耗时减少约 21% / 31%；210 项测试通过，视觉疑点见优化说明。
> 运行与完整变更说明见 [优化说明_20261011.md](优化说明_20261011.md)。
> 下文旧版设计详解保留作历史参考；与本说明冲突处以新版说明和代码为准。

# video2op · 从人体操作视频提取"任务语义操作图"

把操作视频转成**以操作目标、条件和证据为核心的操作图**。任务意图直接参与操作节点生成；
人的部位与视频时间属于示范证据，目标执行器需另行绑定。`program.json` 是待绑定的语义契约，
并非已接入机器人的控制程序。

最新交付物是两份执行侧可接的契约：`semantic_graph.yaml`（语义图，条件写成谓词名）与
`execution_policy.yaml`（实现选择起点，参数留空待绑定）。验证它接得上：
`python tools/verify_contract.py <案例名>`；装进执行侧目录跑：
`python tools/install_contract.py <案例名>` 后 `cd 操作图同事的 && python main.py --graph <名>`。

操作图的**主视图就是门控状态机图**（`operations.svg`）：节点是操作、菱形是门控，
门控 T 时连线由虚线变实线（U = 未观察到，既不当 T 也不当 F）。条件是七元组里的
PRE / POST / CONST，判定只读已有证据（`gates.py`，见 4.10 节）。图面上只写动作
（操作对象与执行器放在七元组里），线色统一为黑，只有实线与虚线两种线型。

> 设计纪律贯穿全文：只做**定性**描述，不写角度、距离、速度、力值。这是语义层的知识，
> 不是控制器参数。校验器会扫描全部文本，出现 `45度`、`20厘米`、`5牛` 这类数值参数就判失败，
> 并自动发起一次改写净化。

---

## 0. 总览：三层数据流与全局设计纪律

### 三层数据流

1. **观察层**（VLM 看视频 + 客观运动证据）：`media.py` 探测与切窗、`s01` 视角、`s02a` 意图、
   `s02b_atomic` 原子动作。产出的是**证据**：谁（部位）在什么时间段做了什么、前后状态、
   可见世界状态。凡是模型推理补出来的，一律标 `inferred=true` 并写理由。
2. **语义学习层**（模型文本调用 + 确定性规则）：`s02b_merge` 合并、`s02c` 七元组任务节点、
   `s02d` 动作链归属、`s02e_prior` 先验补全、`s03` 三重检验、`s04` 正反例条件、`s05` 规则。
   产出的是**语义**：操作、条件、约束、评价器、时序结构。
3. **确定性构建与交付层**（零模型调用）：`operations.py` 操作图、`reasoning.py` 推理修正、
   `expand.py` 子操作、`predicates.py` 谓词化、`gates.py` 门控、`program.py` 执行器程序、
   `graph.py` / `logic.py` 追溯视图、`contract.py` 契约导出、`s06`/`s07` 校验净化、`render.py` 渲染。
   产出的是**交付**：图、程序、契约、报告。这一层全部是确定性代码，改规则立即见效
   （`tools/render_case.py` 可不调模型重跑整层）。

### 全局设计纪律

- **定性不量化**：语义层只写"哪个部位做什么、给什么性质的力"，数值参数归控制器。
- **证据与推断分离**：`inferred=true` + `inference_reason` 是补全动作的身份证；
  推测出的效果不能当作成功证据（见 `evidence.py`）。
- **只命名不改写**：谓词化给条件起稳定名字，条件原文永远保留；判真伪归证据侧。
- **降级不删节点**：推理发现问题时降的是依赖关系或标待复核，不删掉可能真实发生过的操作。
- **不编造参数**：导出层 `implementation` 只写能力类别，参数绑定与超时留空标 `unbound`。
- **节点是操作，执行器是属性**：换执行体只换能力映射，不重画图。
- **示范顺序 ≠ 执行约束**：仅观测到先后、没有条件衔接的顺序不固化成执行依赖
  （`basis=observed_order`）。

---

## 一、快速开始

```bash
cd /home/wj/codex-workspace/videostudy_operation

# 跑单个视频（结果落在 output/<视频名>/）
/home/wj/miniconda3/envs/study/bin/python run.py data/搬物体.mp4

# 跑 data/ 下全部视频
/home/wj/miniconda3/envs/study/bin/python run.py all

# 忽略模型缓存，从头分析
/home/wj/miniconda3/envs/study/bin/python run.py data/燕麦杯.mp4 --force
```

- 环境：conda `study`（`/home/wj/miniconda3/envs/study`），需要 `requests`、`opencv-python-headless`、`pytest`
- 模型：卡1 上的 vLLM 服务，默认 `http://127.0.0.1:8032`，模型名 `qwen3.8-27b`
  （可用环境变量 `V2O_BASE_URL` / `V2O_MODEL` 覆盖，见 `video2op/config.py`）
- 依赖外部命令：`ffmpeg` / `ffprobe`

单视频耗时约 10~15 分钟（15 秒视频约 6 次模型调用）；模型输出有磁盘缓存，
调 prompt 时只有受影响的阶段会重跑。

在云服务器 `study` 环境重建已有案例（不重新观看视频）：

```bash
/home/wj/miniconda3/envs/study/bin/python tools/rebuild_semantics.py \
  output/搬物体/result.json output/搬物体_语义修订 --refresh-task
```

- **机器看**：`output/<视频名>/result.json`（结构化操作图）
- **人看**：`output/<视频名>/report.html`（完整报告）、`timeline.html`（执行器时间轴）、`graph.svg`（执行器级动作依赖图）

---

## 二、任务书五步 → 代码映射

| 任务书 | 实现 | 说明 |
|---|---|---|
| 第一步 视角判别 | `stages/s01_viewpoint.py` | 第一人称 / 第三人称 / 其他，带置信度与画面依据 |
| 第二步 2a 意图+置信度+所需肢体 | `stages/s02a_intent.py` | 意图假设按置信度排序；`required_body_parts` 只写"哪些部位参与、承担什么功能"，作为 2b 的关注重点 |
| 第二步 2b 操作图提取 | `stages/s02b_atomic.py` → `s02b_merge.py` → `s02c_task.py` → `s02d_link.py` → `s02e_prior.py` | 执行器级原子动作（窗口化视频调用）→ 跨窗口合并与保持缝合 → 任务级七元组节点 → 动作链归属与缺失动作推理补全 → 先验补全（站立支撑 / 姿态保持 / 接触期手臂保持） |
| 第二步 双向修订 | `s02d_link.py` + `s03_sync.py` | 意图推理补全操作图缺失动作；操作图反过来修正意图（空间可达、支撑、保持约束） |
| 第三步 同步因果检验 | `stages/s03_sync.py` | 三重检验（意图解释操作图？操作图实现意图？状态变化是否一致？）→ 更新意图置信度 |
| 第四步 正反例条件学习 | `stages/s04_conditions.py` | 每条 C_pre / C_post 都配 正例 / 反例A（失败执行或执行后失败）/ 反例B（未执行或未达预期） |
| 第五步 语义层规则学习 | `stages/s05_rules.py` | 时序结构（Sequence / Parallel / Alternation）、语义约束、评价器 |
| 收尾 校验与净化 | `stages/s06_validate.py`、`s07_purify.py` | 确定性校验 + 参数净化改写 |

---

## 三、流水线各阶段设计详解

按 `pipeline.py` 的 `run_case` 编排顺序展开。每小节给三件事：**职责**（这一步解决什么问题）、
**设计逻辑**（为什么这么做）、**细节**（判定规则、阈值、字段）。

### 3.0 编排与基础设施：pipeline.py / llm.py / config.py

**pipeline.py（编排）**
- `run_case` 主流程 16 步：s00 探测（`media.probe` + `motion_profile`）→ s01 视角 → s02a 意图 →
  s02b_atomic（按窗口多次调用）→ s02b_merge（确定性）→ s02c（纯文本）→ s02d + `absorb_actions`
  （把补全动作并入动作表）→ s02e（确定性 6 规则）+ `absorb_actions` → 最终规范化
  （`fill_states` → `stitch_maintains` → `trim_maintain_overlaps`，写 `stages/s02f_normalized.json`）→
  s03 → s04 → s05 → 证据打包 + `logic.build` + `build_operation_graph` → s06 →
  （仅当 `param_discipline` 失败）s07 净化改写 → `set_by_path` 写回 → 重建 → 重校验 →
  `graph.build` + 渲染 + `contract.export`。
- **容错**：每个阶段用 `stage()` 包裹，错误收集进 `pipeline.errors` 不中断后续——一个阶段坏了
  不吞掉其它阶段的产出。
- **缓存**：`out_dir/cache/` 按"提示词 + 视频"内容做 sha1 指纹存模型响应；`--force` 清缓存重跑。
- `build_operation_graph` 幂等，且与 `tools/render_case.py` 共用同一入口——保证"跑视频"和
  "重跑确定性层"产出的操作图完全一致。

**llm.py（vLLM 客户端）**
- 响应处理链：`strip_thinking`（剥思考内容）→ `extract_json`（候选依次为围栏代码块 / 全文 /
  首 `{` 至尾 `}`）→ 解析失败再 `_repair_truncated`（补引号括号、尾部按 20 字符步进最多砍
  400 字符）修复解。
- **重试升温**：`temperature = 0.1 + attempt × 0.15`，`MAX_ATTEMPTS = 3`；validator 抛错、
  解析失败、HTTP 异常都进下一轮；全失败抛 `LLMError`（带 raw 响应与逐次错误）。
- **视频调用**：mp4 按 base64 内联 `data:video/mp4;base64` 作 `video_url` content part + 文本 part；
  文本调用 user content 直接字符串；`enable_thinking=False`。
- 超时与配额：视频 1800s / 文本 900s，`max_tokens=16840`；`stats()` 记录调用数 / 缓存命中 /
  失败 / 耗时。

**config.py（全部可调参数）**
- `TEMPERATURE=0.1`；切片 `CLIP_WIDTH=704`、`CLIP_FPS=8`、`CLIP_CRF=28`；
  切窗 `WINDOW_SECONDS=8`、`OVERLAP=0.6`、`SINGLE_SHOT_MAX_SECONDS=20`；
  置信度下限 `CONFIDENCE_FLOOR=0.35`。
- `FORBIDDEN_PARAM_PATTERNS` 4 条正则（角度 / 距离 / 速度 / 力值），是"定性不量化"纪律的机制载体。
- 环境变量 `V2O_BASE_URL` / `V2O_MODEL` 覆盖模型端点。

### 3.1 media.py：客观证据（探测、切窗、运动分析）

**职责**：给 VLM 之外补一份**客观**的视频运动证据，用作时间戳锚点与校准，避免纯粹依赖模型的
时间感觉。

- **探测**：ffprobe 取 `v:0` 流的 width/height/`r_frame_rate`/`nb_frames`/codec_name 与
  format 的 duration/size；fps 由分数解析；另算 `file_sha1` 供缓存指纹。
- **切窗**（`window_plan`）：≤20s 整段一窗（`SINGLE_SHOT_MAX_SECONDS`）；否则 8s 窗、
  步长 7.4s（重叠 0.6s 供边界缝合），末窗截尾到剩余时长。
- **切片**（`make_clip`）：按 `(src, start, dur, 704 宽, 8fps, tag)` 做 sha1 缓存到 `output/_work/`，
  低码率 x264、去音轨——体积小到能内联进模型请求。
- **帧差运动分析**（`motion_profile`）：每 2 帧取样，灰度 + 高斯 5×5 后相邻帧 `absdiff`，
  阈值 16 二值化，非零像素占比为运动能量，5 点滑窗平滑。
- **变化点**：前后各 4 采样均值差 |Δ|≥0.012 记"运动增强/减弱"，间隔 <0.8s 只留 |Δ| 更大者。
- **高活动段**：平滑能量 > 均值×1.35 的连续段（≥2 采样点）记 `start/end/peak`；
  `motion_hint_text` 把窗口内变化点 / 热段转成给 VLM 的时间锚点提示（±0.3s 容差）。

### 3.2 s01_viewpoint：视角判别

**职责**：判 `first_person` / `third_person` / `other` 并补中文 `label_cn`。视角决定后续
"哪些部位可见"的解释口径（第一人称看不到自己的腿）。

- **设计逻辑**：一次 VLM 调用（user 模板填 `DURATION`）；校验 `viewpoint`/`confidence` 必填，
  容容中文或 `first`/`third` 简写并映射标准枚举，非法即抛错触发 llm 重试。
- **prompt 要点**（`prompts/s01_viewpoint.system.txt`）：三视角严格定义（镜头即操作者眼睛 /
  旁观可见全身 / 固定机位监控）；只描述真实可见、不脑补，不确定给低置信度并写 `uncertainty`；
  严格 JSON，另出 `operator` / `scene` / `visible_objects` / `visible_parts_hint` / `camera_motion`。

### 3.3 s02a_intent：任务意图学习

**职责**：产出意图候选（`statement` + 置信度 + 证据）与 `required_body_parts` 部位功能先验。
意图候选供 2b 当**关注重点**，不当动作剧本。

- **设计逻辑**：意图写"目标"不写过程；置信度诚实分级（证据充分 ≥0.8、猜测 0.4–0.6）。
  `required_body_parts` 只写"部位 + 功能角色"，**禁写动作序列与先后顺序**——防止带着答案找证据。
- **细节**：prompt 填 `DURATION`/`VIEWPOINT`/`VISIBLE_PARTS`；校验 `intents` 非空且含
  `statement`/`confidence`；归一化补 id、置信度钳 [0,1]、复数部位展开（`MULTI_PART_MAP`）、
  按置信度降序。部位词表固定 11 项（腿含脚不单列脚），腿部功能限站立支撑 / 弯曲下蹲 / 迈步 / 蹬地。

### 3.4 s02b_atomic：执行器级原子动作提取

**职责**：窗口化看视频，逐部位提取**原子动作**（时间 / mode / 给力 / 前后状态 / 可见世界状态）
与时序关系。这是全链路唯一的"看视频提动作"环节。

- **设计逻辑**：一个动作 = 一个执行器（单一部位）在一段连续时间里做的事；双手同时做两件事
  必须拆成两条并行动作——执行器级唯一性是后面执行器时刻表与资源仲裁的前提。
  三条动作模式（`vocab.ACTIVITY_MODES`）：`transition` 建立/解除状态（瞬时：抓握、接触、释放）、
  `motion` 区间姿态/位置变化（抬起、伸出、迈步）、`maintain` 区间保持某状态（保持抓握、托举保持）。
- **细节**：`window_plan` 切窗并配 `motion_hint_text` 运动提示；意图只经 `part_hint_text`
  转成部位关注提示（自带纪律："提示不代表该部位一定有动作，画面没有的不要写"）。
  校验：执行器必须单一标准部位、mode 三态合法、`end≥start`、`world_before/after` 为字符串数组
  （不可见用 `[]` 不编造）。
- **归一化**：时间裁剪进窗口、id 补全、`enforce_active_force`（臂/手/腿非静息被动即强制
  `exerts_force=true`，默认力角色 托举/抓握/支撑）+ `normalize_force`（力角色受控词表，
  头/颈/口及视觉类词不记力）、只保留两端 id 都存在的时序关系。
- **prompt 纪律**：只写真实发生、定性描述严禁数值参数；"保持"必须显式 `mode=maintain`
  且前后状态连续；腿无空白区间（迈步或站立支撑）；`until` 必须用**事件**描述不用秒数；
  `world_before/after` 写可核验对象状态，常识补出的标 `inferred=true`。

### 3.5 s02b_merge：跨窗口合并（确定性规则，无模型）

**职责**：窗口化提取的逆操作——把局部时间转全局、去重、缝边界、重编号，输出一张自洽的动作表。

- **去重合并**：同部位且时间 IoU≥0.35 或包含比≥0.65，**且**文本/双字动词相似≥0.45 才并；
  合并取时间并集、文本长者、mode 取时长较长方、`state_before` 取首、`state_after` 取尾、
  `world_*` 归属区间真实端点（不是"较晚开始者"）。
- **边界缝合**：同一切片被窗口边界截断的两半（flatten 时按贴窗口边界 0.3s 打
  `_truncated_end`/`_truncated_start` 标记）、时间相接 ±0.4s、核心短语互含或相似≥0.45 才缝成一条；
  一方含"停止/结束"类词（`STOP_WORDS`）另一方不含则判**非**同一动作，防止把"抓握+松开"缝成一条。
- **状态补全**：同部位首动作用静息态 `REST_STATE`（臂自然下垂、手张开、腿站立支撑……）；
  缺 `state_before` 继承前一动作 `state_after`（否则用动作名），缺 `state_after` 反向继承下一动作
  `state_before`；maintain 前后同态。
- **保持缝合**（`stitch_maintains`）：maintain 与后继空档 0.4–6s、`state_after` 含持有型词
  （抓握/托举/支撑…）、且后继为解除型动作或其开始状态同源时，把保持延长到后继开始前——
  "手里还握着"不因画面静止而中断。
- **重叠截断**（`trim_maintain_overlaps`）：与同部位 motion 重叠的 maintain 截断到 motion 开始前
  （持物语义转由 motion 的 `force_role` 表达），避免同一执行器两条动作并行占用。
- **交替识别**：仅限成对下肢（左右腿/脚），IoU≥0.30 且相似≥0.38 → 把 parallel/sequence 提升为
  `alternation`（缺则新建）。上肢交替不自动判（语义歧义大），留给模型。
- **关系保守补全**（`add_boundary_relations`）：同部位间隔≤0.35s 补 sequence、异部位 IoU≥0.5
  补 parallel，不覆盖已有关系。
- **重编号**（`renumber`）：全局重编号并建 (窗口, 局部 id) → 全局 id 映射，`until.ref` 按映射重写，
  解析失败标 `ref_unresolved` 不丢弃。
- **冲突检测**（`detect_conflicts`）：同部位 IoU>0.55 或包含>0.8 且相似<0.3 的互斥动作报出
  （maintain 豁免），进待复核清单。

### 3.6 s02c_task：任务级节点聚合（七元组）

**职责**：纯文本调用（不再看视频），把原子表 + 意图 + 场景聚合成**任务节点**，每个节点是一个
可独立交付的操作，带七元组 `X / O / C_pre / C_const / E / C_post / R`（执行主体 / 操作对象 /
任务级前置条件 / 约束元 / 评价指标 / 任务级后置效果 / 候选方式集合，字段名见 `vocab.TUPLE_FIELDS`）。

- **设计逻辑**：节点粒度的判据是"能写 Before→操作→After 且造成可验证的状态变化"，
  不为凑数合并或拆分；节点名称与能力**不绑左右肢**（"抓握"不叫"右手抓握"），执行器在七元组的 X 里。
  条件衔接必须证据支持：时间先后≠必要依赖、靠近≠清障、接触≠抓牢，失败不得改写成成功。
- **细节**：`C_pre` 必须是可判定状态（非心理活动）；`E` 分过程判据与完成判据两级
  （`vocab.EVALUATOR_LEVELS`）；`R` 区分 observed（示范里做过的）与 alternative（备选方式）。
  校验：节点必含 id/name/tuple/intent_role/required_capabilities、七元组字段齐全、id 唯一、
  `atomic_refs` 必须引用真实动作 id；归一化把 `C_*` 转数组、`R` 转 `[{name,origin,steps}]`、
  `E` 转 `{process,completion}`、`X` 转 `{subject,parts}`、`O` 转数组。

### 3.7 s02d_link：动作链归属与缺失动作推理

**职责**：文本调用产出 `links`（动作→节点归属 + 链完整性评论）与 `missing_actions`
（`inferred=true`、带推理理由，经 `absorb_actions` 追加进原子表）。

- **设计逻辑**：每个节点的执行器动作链应成"接近→接触→建立关系→稳定保持→解除"的完整链条；
  缺必需环节（遮挡 / 漏检 / 过快）就补，且**只补必然环节**。重点查三类保持：抓握保持
  （建握→松开间）、托举保持（抬起→放下/前伸间，如抱箱行走全程）、站立支撑（腿不迈步时）。
  意图声明要用却全无动作记录的部位也列入 `missing_actions`——这是"意图→操作图"方向的修订。
- **细节**：`links` 只保留真实动作 id 并附 `chain_comment`；missing 动作顺序补 id、时间钳到
  [0,duration] 且 `end≥start`、mode 非法默认 maintain、强制 `inferred=True` 存 `inference_reason`，
  再过 `enforce_active_force`/`normalize_force`。

### 3.8 s02e_prior：先验补全（确定性规则，无模型）

**职责**：用部位功能先验（`vocab.PART_FUNCTIONS`）补"逻辑必然存在但画面/模型没给"的状态，
  让时序不留空白。补出条目一律 `inferred=true` 带理由；保持类只写部位姿态不带物体名。

六条规则（阈值：`MIN_STAND_GAP=1.2` / `MIN_HOLD_GAP=1.0` / `MIN_CONTACT_GAP=0.4` /
`PREOPEN_SPAN=1.0`，单位秒）：

1. **腿站立支撑**：腿无动作空档 >1.2s（含尾部）补 maintain"保持站立支撑"——腿要么迈步要么支撑，不许留白。
2. **姿态保持**：motion 建立托举/抬起/抓握等姿态（`HOLD_POSE_WORDS`）后至下一动作空档 ≥1s
   且未被 maintain 覆盖时补"保持X"。
3. **抓握保持**：与规则 2 同机制（抓握类词并入 `HOLD_POSE_WORDS`）。
4. **接触期手臂保持**：手的接触段（接触→抓握→保持合并）与同侧臂空档 >0.4s 重叠时补臂
   "保持位置/保持伸出"，力角色"稳定"而非托举（映射 `vocab.HAND_TO_ARM`）。
5. **抓握前预张开**：transition 含抓握动词（`GRASP_WORDS`）但此前无张开记录（`OPEN_WORDS`）时，
   于抓握前补 1s"张开手指至可抓取开度"transition（幂等，不重复补）。
6. **释放期手臂保持**：手做松开/释放类 transition 时臂无记录则补"保持位置"稳定力，直到撤回接管
   （先保持生效、再允许释放，防止"手松开时手臂不知在哪"）。幂等按“覆盖整个释放期”判，
   不用固定秒数门槛：释放期可能只有 0.2s，补出的保持和它一样长，固定门槛永远不成立，
   离线重算一次会多一条重复保持（从冰箱取出蔬菜案例踩过的坑）。

辅助：`_pose_name` 按姿态词在动作文本中的出现序组词，无姿态词退用"伸出/靠近"系词；力角色按部位定
（手=抓握、臂=托举、腿=支撑、其余=稳定）。

### 3.9 最终规范化（pipeline 内，写 stages/s02f_normalized.json）

补全动作并入后做三步收尾，保证动作表在进入语义学习层之前自洽：
`fill_states`（静息态/继承补前后状态）→ `stitch_maintains`（保持缝合）→
`trim_maintain_overlaps`（保持与同部位移动重叠截断）。这三步与 s02b_merge 同源共用，
确保"跑视频"和后续"重跑确定性层"得到同一份规范化动作表。

### 3.10 s03_sync：同步因果检验

**职责**：三重检验 + 置信度更新 + 双向修订，回答"意图和操作图是否互相支持"。

- **c1 意图能否解释操作图**（yes/partial/no）；**c2 操作图能否实现意图**（查四类缺口：
  部位缺口、动作链断裂、空间可达性——手臂范围要覆盖目标、支撑/约束——离地前必须先抓握；
  缺口记 `missing`）；**c3 前后状态一致**（A 的结束态=后继开始态、无矛盾；违例记 `inconsistencies`）。
- **置信度更新**：三检验全过 +0.05~0.15；有意图成立但有缺口则小幅调整/维持；有矛盾则下降。
  `intent_confidence_before/after` 夹取 [0,1] 保留两位，解析失败置 None 由校验拒绝。
- **双向修订**：`revisions.to_intent`（修意图表述/范围）与 `revisions.to_graph`（补/改动作），
  归一化为字符串列表。校验器要求 `checks`≥3 条且 `intent_confidence_after` 必填。

### 3.11 s04_conditions：正反例条件学习

**职责**：给每条 C_pre / C_post 配三例推理，判它是不是**有效条件**——正例证明成立时有效，
反例证明违反时真会失败。只有正例的条件可能是摆设，推不出反例的条件可能过度约束。

- **C_pre 三例**：正例=条件满足时成功执行；反例A=条件被违反时执行失败；反例B=条件不满足时
  操作根本不发起。
- **C_post 三例**：正例=完成后确实观察到效果；反例A=执行了但效果未达成；反例B=效果达成但
  非本次操作预期（别的原因达成的，不能算它的效果）。
- **verdict 四值**：`有效`（正例+两反例均可推出）、`部分有效`（仅一类反例成立）、
  `无效或过度约束`（反例推不出失败或表述过强）、`证据不足`；非法值归"证据不足"。
- **结构**：`condition_learning[]{node_id, C_pre_learning[], C_post_learning[]}`，每条
  `{condition, verdict, positive/negative_a/negative_b{text,reason}, confidence}`；字符串自动包成
  `{text,reason:""}`，confidence 夹取 [0,1] 缺省 0.6。另有
  `effective_conditions_summary[]`（成立条件）与 `rejected_conditions[]`（`{condition, why}`）。
- **纪律**：`condition_learning` 须非空；反例可以推理补出但**必须写依据**，不许无据编造反例。

### 3.12 s05_rules：语义层规则学习

**职责**：从单案例里抽出可复述的语义层规则：时序结构、约束、评价器。

- `temporal_structures[]`：`{id, level(task/action/executor，非法归 action),
  pattern(Sequence/Parallel/Alternation，非法归 Parallel), members, statement, evidence}`。
- `constraints[]`：`{id, type(空间/接触/支撑/顺序/保持/力需求/安全 七类，非法归"安全约束"),
  statement, applies_to, reason, violation_consequence, confidence(缺省 0.6)}`。
  七类见 `vocab.CONSTRAINT_TYPES`；力需求只记**有无**不记数值。
- `evaluators[]`：`{node_id, process[], completion[], failure_signals[]}`，对应评价器两级词表；
  三个键须为数组否则触发重试。

---

## 四、确定性构建层详解

这一层全部是确定性代码（零模型调用），输入是语义学习层的定稿数据，输出是交付物。
改任何规则后用 `tools/render_case.py <案例名>` 即可重跑本层并重渲染全部图表。

### 4.1 operations.py：操作图（交付主图）

**职责**：把 task_nodes + atomic_actions 确定性重组成"操作为节点"的图。与 `graph.py` 分工：
这里是调度/交付视角，那里是原子追溯视角。

**节点**：1 个 task_node → 1 个操作节点，七元组随 tuple 带入；`executors` 取 `tuple.X.parts`
（缺失回退为绑定原子动作的执行器并集）；时间取 `time_range`（缺失由 atomic_refs 的
min(start)/max(end) 推出）；记 `atomic_refs`/`observed_effects`/`inferred_steps`；`purpose` 先留空。
节点名不以执行器开头（剥前缀），执行器只写属性——这是"换执行体不重画图"的机制保证。
补充节点两个来源：①未被认领的 maintain 动作按重叠时长最长归入宿主操作
（`_adopt_orphan_maintains`）；②未认领的 inferred transition（如预张开）提升为 `step_*` 独立操作，
带 `prepares` 指向后继。

**边推导**：动作级 relations 按操作对**投票聚合**（`_vote`/`_pick`，多数票定关系与方向）。
依赖关系（sequence/enables/maintain_until）优先于软关系（parallel/alternation）——信息更强。
软关系须两操作时间重叠才成立，记 `mutual` 无向对（渲染画 ∥/⇄）。无任何票且时间不重叠的
操作对补 sequence（时间兜底）。传递约简 `_reduce_sequences` 只删冗余 sequence 边；
**enables（因果）与 maintain_until（保持）即使可传递也保留**。

- `enables` 判定：A 的 C_post 与 B 的 C_pre 字符二元组 Jaccard ≥ 0.34 视为条件衔接，
  对应 sequence 边升级为 enables。
- `intent_chain`：每条依赖边取最优 post↔pre 相似匹配（`provides`/`because`/`score`）；
  `purpose` 回填 = `为「后继」提供：{provides}`——操作意图 = 它为后继提供的前置条件。
- `carries`（跨操作保持延续）：A 中 maintain 动作在 B 开始前已建立且延续过 B 起点 → 记在
  A→B 边的 `carries`；无现成边时补 maintain_until（`cross_op_maintain`）；MAINTAIN 节点自身不挂 carries。
- **分层**（`_layer`）：硬边保证层号递增、软对拉到同层，迭代收敛后压缩层号；不收敛回退纯依赖
  分层，保证每条边从左指向右。
- 节点内协同（`inner_parallel_count`/`inner_alternations`）留在节点属性，对应多轴协同。

**保持节点提升**（`_lift_maintains`，提升为 `mode: MAINTAIN` + `maintain_until`，与执行侧
`A3_HOLD`/`A7` 同形）：

- 提升对象：mode=maintain 的手/臂/腰保持（抓握/托举/位姿/接触）。**腿部"站立支撑"不提升**——
  全程背景状态，不是"为某操作提供条件"的调度单元。
- 提升条件①：保持覆盖 ≥2 个操作（重叠 >0.05s）——跨过操作边界，本身即独立调度单元；
  条件②：仅覆盖 1 个操作时只有位姿保持（pose）提升——固定位姿与该操作动作天然两件事，
  且宾语必须是**执行器自己的位姿**（`vocab.is_self_hold`）：“右臂保持位置”“右臂保持伸出”
  提升；“右臂保持燕麦杯在桌面近处位置”不提升——后者维持的是物体在世界中的位置，手臂只是
  停在原地等释放，不以操作为目的（用户口径），留在所属操作内部当步骤。
- 不提升例外：单操作覆盖的托举/接触保持是该动作自身的一部分（搬运时手臂保持托举）；
  `busy_ratio>0.5`（保持期间同执行器还在干别的活，如拧瓶盖时的接触保持）不提升，防抢资源。
- 数量上限 `MAX_LIFTED_HOLDS=4`，覆盖操作多者优先——防背景状态淹掉主图。
- 提升后动作从宿主操作 `atomic_refs` 摘除（调度单元唯一宿主）；被覆盖操作记 `held_by`、
  来源操作记 `lifted_holds`。MAINTAIN 目标（`_maintain_target`）优先"不同执行器的最后一个
  被覆盖操作"，避免与保持同执行器互等死锁。`handoff_to`=停止事件所属且在保持结束后开始的
  操作，仅用于叙述审查，不进 maintain_until。
- 保持节点的边（`_hold_edges`）：建立者→保持为 enables；被覆盖中间操作画 mutual parallel；
  目标画 maintain_until。建立者（`_hold_entry_source`）= 时间紧邻前驱 + 后置效果同类验证；
  无前驱则不编造来路，记 `entry_within` 不画边。

**释放步骤拆分**（`_split_release_steps`）：被保持覆盖的操作若含"释放"动作（占同一执行器），
与 MAINTAIN 的 maintain_until 互等资源 → **调度死锁**。拆分规则：非 maintain 且被 hold 覆盖的
操作，恰含 1 条释放动作（transition + 松开/释放/放开/脱离/脱开）且有其它动作，且释放是最后一条
非保持动作（保持跨过释放时刻属正常）。拆出 `{op_id}_release` 新节点（`required_capabilities=["释放"]`，
带 `split_from`/`split_reason`）；原节点按剩余动作重算（end 截到释放起点、executors 取剩余动作
执行器并集——就位段占臂、释放段占终端执行器）；拆走的动作记入 `split_action_refs`（证据不丢，
只是换调度边界）；拆后 `_resync_holds_after_split` 把 hold 的 covers/maintain_until/held_by/handoff_to
改指到 release 节点；源操作→释放节点边标 `inferred_by=release_split`。
“物体状态保持不提升”（上一条判据）是这条拆分能成立的前提：那种保持一旦被提升走，
放置操作里就只剩释放一条动作，拆分条件（释放之外还有别的动作）不成立，又回到保持与
释放抢同一个执行器的老问题（燕麦杯案例踩过的坑）。

**build 流水线**：补归认领 → 提升孤立步骤 → 提升保持 → 拆释放 → 重同步 → 自动边让位保持边 →
约简 → 保持边 → carries → 先验步骤边。

### 4.2 reasoning.py：推理修正

**职责**：对图上每条关系追问到底，把结论**落回图**（不是再写一段解释）。四类追问：

- **依赖能力校验**：A 声称给 B 提供条件 X——A 的执行器有没有产生 X 的能力（部位功能先验）？
  仅有能力不能证明实际效果；缺观测后状态则**降级**为待核实关联，**不删节点**（A 可能确实发生了，
  只是与 B 无因果关系）。
- **前置覆盖缺口取证**：B 的每条 C_pre 要么有有效前驱提供，要么有当时的观测前状态支持；
  两者都不是时回头扫全部原子动作（含未被认领的）找证据；再找不到才登记为**候选缺口**——
  候选只是候选，不写成视频事实。
- **持续约束**：依赖"握持/托举/支撑"的操作，过程内必须有覆盖全程的保持动作，否则标待复核。
- **预期 vs 证据**：每个操作声明的 C_post 要在画面证据里找到落点（预期 ≠ 实际）。

处理动作四类：`keep` / `downgrade` / `flag` / `gap`，合法且降级必须真正落地（s06 的
`reasoning_traceable` 校验盯着）。边区分 `basis=required_dependency`（执行依赖）与
`basis=observed_order`（仅观测先后，不固化成执行约束——避免把示范者偶然的顺序学成规则）。
**中间触发**：前一操作未结束但其某动作已产生后继所需条件时，不降级成"并列"而算出触发点，
写成 `trigger{type:partial, event:{action_completed, ref, at}, unlocks[]}`（例：水壶放到水槽上方
才解锁"拨动水龙头开关"；落进 `program.txt` 的 `AND AFTER_ACTION(#5)` 与 `program.svg` 的 ⚡ 触发线）。

### 4.3 expand.py：子操作展开

**职责**：每操作展开成执行层可直接调度的子操作。全部来自已定稿原子动作表，不新增动作/状态；
inferred 保留推理理由。

- 子操作字段：`id={op}.s{i}`（按 start 排序）、`name`（去执行器前缀）、`executor`、`mode`、
  `kind`、`capability`、`start/end`、`pre=state_before`、`post=state_after`、
  `exerts_force/force_role/object`、`atomic_ref`、`inferred/inference_reason`、`until`、`evidence`。
- `kind` 分类：maintain→`hold`；transition→`establish`/`release`（按释放标记词）；其余→`motion`。
- `capability` 与执行侧实现词表对齐（建立抓持/解除抓持/持续保持X/承载移动/接近目标/稳定放置…），
  接过去即挂技能。
- 关系三类：`hold_covers`（hold 区间含住动作全过程 ±0.05s，比 parallel 强——是动作成立的前提）→
  沿用操作级 relations → 时间兜底（不重叠补 sequence、重叠补 mutual parallel）。
- 执行层检查点：`establish`→末尾 `state_check` 验证"真的建立了"；`release`→`state_check` 确认解除；
  `hold`→`hold_check` 在 [start,end] 区间持续监测（`monitor_during`），退出条件见 `until` 字段。
- 产物结构：`operations[]` 含 id/name/intent/executors/time_range/`expandable`(>1 子操作)/
  `sub_operations`/`relations`/`checkpoints`/`unexpanded_note`，另有 `by_operation` 索引与 `stats`。

### 4.4 predicates.py：谓词化

**职责**：确定性"谓词化"——把自由文本条件登记成稳定可引用的标识。**只命名不改写**：不改语义、
不放松纪律；谓词名只是"这条条件"的代号，不是事实；负例（门未打开）不能与正例混成同一谓词。

- **命名规则**：`base = 谓语 + 空间限定(verb+spatial)`，再按谓语决定是否拼执行主体后缀 `_{agent}`
  （Located/State/StateHeld/Negated/PoseHeld 及安全谓词不拼 agent）。
- **稳定性**：同一原文经 `by_text` 去重复用同一 id；同名撞不同文本时 `_mint` 加序号 `_2`/`_3`——
  加序号不合并、不假装同义；顺序由首次出现决定。
- **表字段**：`id`、`text`（原文永远保留）、`verb`、`agent`、`spatial`（无则空）、
  `polarity`（positive/negative）、`prefix`（"直到…"叙述前缀单独记，原文照存）、
  `roles`（引用者 node+role：pre/post/constraint/evaluator/stop_event/sub_pre/sub_post，同一张表）、
  `source=observed_text`。
- **谓语判定**（`_pick_verb`）：安全谓词 `SAFETY_PREDICATES`（名字对齐执行侧约束名，可直接挂
  检测项）最先 → 保持类组合判定（`HOLD_MARKERS`+`HOLD_QUALIFIERS`，处理"保持……的抓握"动宾隔开）
  → 一般动词表 `VERB_PREDICATES`（顺序即优先级，长词在前，"保持抓握"不被"抓握"抢认）→
  Negated → 兜底 State。
- **空间限定**：上方=Above、下/下方=Below、内类=Inside、旁类=Beside、顶部=Top、上=On；
  "中"故意不算空间词（避免"过程中"误读为 Inside）。
- **主体识别**（`AGENT_WORDS` 顺序）：手→臂→腿→手指/掌→腰躯干头颈口→环境/路径/支撑面；
  无命中归 Target。
- **极性**：`NEGATIVE_WORDS`（未/没有/不再/不/无）判负；`NEGATION_EXEMPT`（不碰撞/不滑落…）
  出现时不判负——安全约束的"不"是语气不是否定。
- **边界**：条件成不成立仍由证据侧按原文核对（support/matches 纪律不变）；`lookup` 查不到返回空，
  由调用方决定，不在此猜。

### 4.5 vocab.py：词表与先验

全链路共用的受控词表，是"定性"纪律与先验知识的集中地：

- **部位词表** `BODY_PARTS` 11 项：躯干、腰、头、颈、口、左右臂、左右手、左右腿——
  **腿脚一体不单列脚**。`PART_GROUPS` 四组：上肢（臂+手）、下肢、躯干（躯干/腰/头/颈）、口部。
- **静息态** `REST_STATE`：不给力/不活动时的默认状态（臂自然下垂、手张开、腿站立支撑、
  躯干腰直立、头颈平视、口闭合），是补全未观测部位状态的重要先验。
- **功能先验** `PART_FUNCTIONS`（executor→functions）：臂=靠近/移动/托举/旋转/保持位置；
  手=抓握/释放/接触/支撑/保持抓握；腿=站立支撑/直立/弯曲下蹲/迈步/蹬地/抬起；
  躯干=直立/前倾弯腰/后仰/转身/保持平衡；腰=弯曲/旋转/保持稳定；头=转向/低头/抬头/保持朝向；
  颈=转动/保持；口=张开/闭合/接触/吞咽。`part_functions_text()` 拼成 prompt 可读文本。
- **接触期先验** `HAND_TO_ARM`：手→同侧臂映射；手接触物体时同侧臂必停在上一动作末端保持给力
  （s02e 规则 4 与 s06 校验共用）。`CONTACT_WORDS`/`RELEASE_WORDS` + `is_contact_action()`
  判"手正在接触"（解除型优先排除）。
- **动作模式** `ACTIVITY_MODES` 三态：transition（瞬时）/ motion（区间移动）/ maintain（区间保持），
  与功能先验的 execution_mode 一致。`FORCE_ROLES`：`exerts_force=true` 时"在给什么力"的角色词
  （支撑/托举/抓握/握持/推/拉/平衡/蹬地/稳定）。
- **时序关系** `TEMPORAL_RELATIONS` 五种：sequence（A 完成后 B 才开始）、parallel（时间重叠）、
  alternation（交替往复，如走路双腿）、maintain_until（A 持续维持直到 B）、enables（A 是 B
  前置条件）。`RELATION_TEXT` 是每种关系的人话渲染模板。
- **约束元三分类**（`C_const`）——`constraint_kind()` 判定：空文本→safety；含 `SAFETY_WORDS`
  →safety；含 `HOLD_WORDS`（保持/持续/维持/全程/始终/自始至终）→hold；其余→safety：
  - `hold` 保持类：需执行器全程持续维持，必须在图上有落点（操作内覆盖全程的保持动作，
    或提升为独立 MAINTAIN 节点）。
  - `safety` 安全类：规划/力控保证的边界条件（不碰撞/不滑落/不倾倒/不损伤），
    不需要保持动作承担，记 `delegated`。
  - `local` 局部类：只在瞬间成立的质量要求（`LOCAL_WORDS`：过程中不/时不/瞬间/一刻/同时不），
    由该动作执行质量保证。
  - **分类动机**：混在一起会使每个操作都被标"缺保持动作"，安全约束永远等不到覆盖，
    "可启动性"判据失效。现在只有真正没人承担的持续约束才阻塞（`startable=false`）。
  - hold 细分 `HOLD_CATEGORY_WORDS` 四类：grasp（抓握类）/ support（托举/支撑/承载）/
    contact（接触/触碰/贴合）/ pose（位姿/位置/朝向）；`hold_category()` 按序匹配、无命中归 pose；
    覆盖判定要求**同类**（抓握约束须抓握类保持动作覆盖）。
  - 保持动作的宾语另分一层（`is_self_hold()`，2026-10-08）：宾语是执行器自己的姿态或**它**
    对物体的作用（保持位置/伸出/抓握/托举）→ 真，是执行器自己的操作；宾语是物体在世界中
    的位置（“保持〈物体〉在〈某处〉”）→ 假，这类保持不提升为 MAINTAIN 节点（见 4.1）。
    判定取“保持/维持/持续”后的首二字——执行器能保持的都是双字词，宾语是物体名时首二字
    落不进 `SELF_HOLD_WORDS`。
- 其它：`CONSTRAINT_TYPES` 七种（空间/接触/支撑/顺序/保持/力需求/安全约束）；
  `EVALUATOR_LEVELS` 两级（过程判据/完成判据）；`TUPLE_FIELDS` 七元组
  （X/O/C_pre/C_const/E/C_post/R）；`EXAMPLE_CANDIDATE_SETS` prompt 风格样例。

### 4.6 program.py：执行器语义程序

**职责**：把操作图编成"每个执行器知道自己何时开始、何时结束、给什么力"的语义程序。

- 每操作一个规则块：`WHEN`（前置谓词）/ `TRIG`（触发）/ `DO`（动作）/ `WHILE`（过程约束）/
  `UNTIL`（停止事件）；MAINTAIN 节点用 `ON` / `DO MAINTAIN` / `UNTIL STOP_WHEN`。
- `executor_schedule`：每个执行器的时刻表（何时开始、何时停止、这段时间给什么力）。
- `startable` 静态问题标记：`false`=有静态问题（如没人承担的 hold 约束）、`null`=仍需绑定与
  运行时检测；静态分析不输出 `true`。
- `blocked_by` 待核实问题清单；`code` 伪代码（`program.txt` 同源），可直接改写成执行层代码。

### 4.7 evidence.py：证据审计

**职责**：效果与前提的证据判定，是"预期 ≠ 实际"纪律的机制载体。

- `matches`：自由文本当前采用**去标点后的完整匹配**——同义但未规范化的条件保留待核实，
  不能当作不可能或失败。
- `observed_state`：只有观测后状态算成功证据；`inferred`、继承状态、动作名、前状态、推断补全
  **都不证明成功**；效果不能自证前提。
- 后状态冲突（同一效果出现矛盾证据）请求复核，不静默取舍。

### 4.8 graph.py：执行器级动作依赖图（追溯视图）

**职责**：节点=原子动作的 DAG，回答"哪个部位第几秒做了什么"，作为证据追溯视图（`graph.svg`）。

- `DEP_RELATIONS` 硬边（先后/使能/保持依赖）入图；软关系（parallel/alternation）不画成边，
  只作为同层布局约束。
- 回边检测剔除成环边（记 `dropped_edges`），保证输出一定是 DAG；最长路径分层；
  不收敛回退纯依赖分层。

### 4.9 logic.py：时序逻辑表达

**职责**：同一份依赖的两种可执行表述——谓词式（`WHEN … DO … UNTIL …`）与 PLC 式（梯形图风格）。
并行组用并查集聚合，PLC 图把同一时间段内的并行动作合并成一行，不写成一堆两两重复的关系。

### 4.10 gates.py：门控（行为树 / 状态机视图）

**职责**：把"操作之间那一跳凭什么放行"写成可判真假的**门控点**（主产物 `operations.svg`，
报告里有同一份明细），让操作图从"先后关系图"升级为"带条件放行的状态机"。

口径（领导给的定义，落在数据上就是三项合取）：

> 关键门控 G = 前序操作所需效果已成立 ∧ 下一操作前置条件已成立 ∧ 必要的场景与持续约束已成立

三值判定，互相不可顶替（判定与依据写在悬停详情、报告与工作台里，**图面上不画 T/U/F 字母**）：

- **T** 证据确认满足 → 连线画实线（放行）
- **F** 证据确认不满足 → 虚线（阻断；修条件或补操作）
- **U** 未观察到 / 尚未确认 → 虚线（等待证据）

连线一律黑（`#1a1a1a`），只有实线与虚线两种线型；保持覆盖的持续约束也是黑虚线，
与"等待放行"靠悬停详情区分而不是靠颜色。节点圆内只写动作（"接近"而不是"接近燕麦杯"），
操作对象与执行器放在七元组里。

**U 既不能当 T 放行，也不能当 F 判死**——这条纪律决定门控是"给人看的解释"还是"能接执行的开关"。
（当前两个案例的 F 都为 0：证据不足一律记 U；F 只在拿到否定证据时出现。）

门控的条件分四类，全部来自已经写好的结论，本模块不重新解释证据：

- **换挡条件（effect）**：跨列依赖边上承载的条件（`trigger.predicates` / 意图链 `provides`）；
  边上没有承载条件时，退回源操作自己的后置效果（它产生了什么，就是这一跳要交出的东西）。
- **必要前提（prior）**：下一操作 `pre_inferred` 里"由某操作提供的必要前提"（如抓握前手必须先张开）。
  推理补全 + 无画面证据 ⇒ U，不会被当成"已经张开"。
- **持续约束（constraint）**：下一操作的保持类 `C_const`，以及**有没有保持动作承担它**
  （本列或前一列存在对应的 MAINTAIN 节点就是 T；只有 `uncovered` 才是 U）。
- **场景前提（context）**：反复出现在 ≥3 个操作前置里的世界状态（"物体仍在桌上"）——
  记进明细，但**不参与放行判定**：它不是这一跳要交出的东西。

判定只读三处证据（都是前面阶段已经写好的），不新增任何事实：
`effect_evidence`（前序效果 observed / unverified）、`pre_coverage`（下一前置 provided / ambient /
candidate_source / unprovided）、`hold`（约束 covered / delegated / uncovered）。

**列序与 `operations.layers` 的分工**：层是给依赖图分层用的，保证边从左到右，但同层未必同时发生
（举升与放置会被最长路径松弛压到同一层）；门控图要回答"哪几步在同时做、在哪一跳换挡"，
所以列**按时间重叠切**：非保持操作流式分组，保持操作并入与它时间重叠最多的一组——
"手臂保持伸出"与"手掌抓握"同列，门控正好落在真正需要放行的换挡点上。

---

## 五、校验与净化：s06_validate / s07_purify

`s06_validate` 是纯确定性校验（不经模型），16 项检查全部有明确判定逻辑；阈值与禁参数正则在
`config.py`。任何一项 fail 都会写进 `validation` 与待复核清单，其中 `param_discipline` 失败
还会触发 s07 净化。

1. **param_discipline**：递归扫描全部语义文本字段（跳过 meta/validation/stats/pipeline/
   profile/window_plan/purify/temporal_logic 前缀），命中 `FORBIDDEN_PARAM_PATTERNS`
   （角度/距离/速度/力值）即 fail。定时动作的时间值是唯一允许的数字。
2. **time_sanity**：`end<start` 或时间越界（`start<-0.01`、`end>duration+0.5`）即 fail。
3. **state_chain**：同执行器相邻不重叠动作对的 `state_after→state_before` 命中矛盾词对
   （抓握/张开、持有/空手等）记 warn——"孩子被抢走后怀里不能还有孩子"。
4. **maintain_coverage**：建立抓握/托举后到解除之前必须有保持动作覆盖；空档 >1s 报缺口。
5. **leg_coverage**：腿在整个时间轴必须有状态覆盖（迈步或站立支撑），不许留白。
6. **arm_contact_hold**：手在接触/操作物体时，同侧臂必须有记录（保持位置/伸出），缺则报。
7. **intent_part_coverage**：意图声明要用的部位必须有动作记录（与 s02d 的 missing 联动）。
8. **operation_nodes**：操作节点名不得以部位开头——节点必须是操作，执行器只能是属性。
9. **operation_graph**：操作图结构自洽（边引用真实节点、关系合法）。
10. **reasoning_traceable**：推理修正的处理动作必须是 keep/downgrade/flag/gap 之一，
    且降级必须真正落到图上（不是只写一段说明）。
11. **predicate_binding**：MAINTAIN 节点必须有 `maintain_until`（否则不知道守到什么时候）。
12. **sub_operation_expansion**：子操作展开的 `hold_covers` 时间关系必须成立（±0.05s）。
13. **contract_schema**：契约字段对齐执行侧 schema（REQUIRED 键齐全），依赖无环。
14. **contract_handoff**：交接字段自洽（`END` 等待的条件必须是本图真的会产生的状态——
    否则永远等不到）。
15. **execution_contract**：可启动性检查，没人承担的 hold 约束记 `blocked_by` 并置
    `startable=false`；安全类约束记 `delegated` 不阻塞。
16. **references**：引用完整性——`atomic_refs`/`until.ref`/关系端点必须指向存在的 id。

**s07_purify（净化改写）**：仅在 param_discipline 失败时触发。把违规表述交给模型改写成
定性说法（"手腕旋转 45 度"→"转动手腕”），归一化 `rewrites` 后经 `pipeline.set_by_path`
写回原字段，重建图并**重新校验**——净化不是手工润色，是闭环里的一步。

---

## 六、产物

```
output/<视频名>/
  result.json      总产物：视角 / 意图 / 原子动作 / 时序关系 / 任务节点七元组 / 操作图 / 门控 / 执行器程序 / 因果检验 / 条件学习 / 规则 / 推理修正 / 谓词表 / 子操作展开 / 契约 / 校验
  semantic_graph.yaml   给执行侧的语义图（节点字段对齐执行侧 schema，条件写成谓词名）
  execution_policy.yaml 实现选择起点；参数绑定与超时留空待接入时填写
  operations.svg   操作图 = 门控状态机图（行为树式）：圆 = 操作（动作 + 协同小字，保持类暖色框）、
                   菱形 = 门控、同一列 = 时间上重叠的一组操作；门控 T 时连线由虚线变实线，
                   其余（U 等待 / F 阻断 / 持续约束）都是虚线；连线一律黑
  program.svg      给执行器看的程序图：每个操作一个规则块（WHEN / TRIG / DO / WHILE / UNTIL；
                   MAINTAIN 节点用 ON / DO MAINTAIN / UNTIL STOP_WHEN）
  program.json     给执行器的语义程序：每个操作的 WHEN / DO / UNTIL + 每个执行器的时刻表
  program.txt      同一份程序的伪代码（人看，可直接改写成执行层代码）
  report.html      完整报告（人看，离线可开；主图 = 门控状态机 + 门控明细，含操作展开、推理修正、可执行契约等章节）
  workbench.html   可交互工作台（主图 = 门控状态机图）：点节点看七元组 / 子操作 / 执行层对接，
                   点菱形看门控条件与依据，点连线看关系类型（跑 run.py 或 render_case.py 自动生成，
                   也可 python tools/export_workbench.py <案例> 单独重导出）
  timeline.html    执行器时间轴 + 分部位动作叙述 + 时序关系（人看）
  timeline.svg     时间轴静态图
  graph.svg        执行器级动作依赖图（DAG：节点=原子动作，边=先后/使能/保持依赖，追溯视图）
  stages/*.json    各阶段的原始输出（可追溯每一步）
  cache/*.json     模型调用缓存（prompt 与视频的指纹）
```

**两套产物，两种读者**（交付口径）：给人看的是 `operations.svg`（门控状态机）/ `report.html` /
`timeline.html` / `workbench.html`（可点击的门控工作台）；给执行器看的是 `program.svg` /
`program.json` / `program.txt`（以及 result.json 的 `operations` / `gates` / `program`）。
两套图来自同一份数据：`operations.svg` 强调"这一跳凭什么放行"（门控 T/F/U 与依据），
`program.svg` 强调"等什么、做什么、停在哪"（规则块 + 触发线），读图不需要再做推理。
`graph.svg` 退为追溯视图：回答"哪个部位第几秒做了什么"。
（卡片式操作图保留在 `render.operation_svg`，需要看节点缺口红条时用，不作主产物。）

以 `_` 开头的目录是工作目录，不是案例产物：`output/_work/`（切片临时文件）、
`output/_probe/`（模型能力探针）、`output/_test/`（长视频回归素材）、`output/_regression/`
（旧案例的跨案例回归：用当前代码重跑确定性阶段，验证新逻辑不改坏别的图）。
`output/long_test/` 是长视频回归案例，验证"切窗 → 跨窗口合并 → 边界缝合"路径。

### result.json 关键结构

- `viewpoint`：视角判别结果
- `intents[]`：意图（`statement` / `confidence` / `required_body_parts` / `expected_final_state`）
- `atomic.atomic_actions[]`：执行器级原子动作，含 `executor`（部位）、`action`、
  `mode`（transition/motion/maintain）、`start`/`end`、`exerts_force`+`force_role`、`object`、
  `state_before`→`state_after`、`until`（`{"type","ref","text"}`：保持持续到哪个事件发生）、
  `inferred`（是否推理补全）
- `relations[]`：时序关系（sequence/parallel/alternation/maintain_until/enables），端点指向
  原子动作 id，`inferred_by` 标明是画面提取还是规则推导
- `task_nodes[].tuple`：任务级节点七元组 `X / O / C_pre / C_const / E / C_post / R`
- `sync`：三重因果检验 + 置信度更新 + 双向修订建议
- `conditions.condition_learning[]`：C_pre / C_post 的正例、反例A、反例B
- `rules`：`temporal_structures` / `constraints` / `evaluators`
- `graph`：执行器级动作依赖图（DAG）：`nodes`（动作 + `layer`）、`edges`、`layers`、
  `dropped_edges`（为保无环剔除的回边）；并行/交替只作为同层布局约束
- `operations`：操作图（交付主图）：`nodes[]`（`name`/`intent`/`executors`/`pre`、`post`/
  `atomic_refs`/`inner_alternations`、`inner_parallel_count`/`purpose`/`layer`）、
  `edges[]`（sequence/enables/parallel、alternation（`mutual=true`）/maintain_until；
  `carries` 表示前一步的执行器动作延续到本步期间）、`intent_chain[]`、`parallel_groups`、
  `orchestration`（一句话调度口径）
- `program`：执行器语义程序：`operations[]`（`when`/`do`/`until`/`hold`、`startable`、`blocked_by`）、
  `executor_schedule`、`code`
- `reasoning`：推理修正：`checks[]`（逐条追问）、`revisions[]`（真正落到图上的修改）、
  `gaps[]`（候选缺口，只登记候选不写成事实）
- `predicates`：谓词表：每条条件的稳定名字（`id`/原文 `text`/谓语/主体/空间限定/极性/引用者）
- `gates`：门控（行为树 / 状态机视图）：`columns[]`（按时间重叠切的操作列）、
  `gates[]`（`from`/`to`、`state`（T/F/U）、`checks[]`（每条条件的 `kind`（effect/prior/
  constraint/context）、`text`、`state`、`verdict`、`evidence`、`gate`（是否参与放行判定））、
  `lines`（图上写哪几行）、`unresolved`、`reason`）、`stats`
- `expansion`：子操作展开：子操作、关系（含 `hold_covers`）、执行层检查点
- `contract` / `execution_policy`：给执行侧的契约（两份 YAML 的同一份数据）
- `validation`：确定性校验结论（`passed`、逐项检查、待复核清单）

---

## 七、渲染：render.py

全部 SVG / HTML / 时间轴由 `render.py` 确定性生成，不含模型调用。除了第六节的产物树，
渲染层的两个要点：

- **分部位动作叙述**：把原子动作按执行器组织成人可读的叙事（"左臂 向前伸出 → 左手 接触瓶身
  → 左手 建立抓握 → 左手保持抓握（全程给力）"），供 timeline.html 与报告使用。
- **边标签可读**：操作图边上写它承载的条件；`carries` 标"∥ 保持延续"；∥ / ⇄ 显式画在图上
  （不靠同列暗示）；MAINTAIN 节点橙框，缺口红条、待复核黄条。
- **门控状态机图（`gate_svg`，主图）**：操作图的主视图——节点画成圆（**动作 + 协同小字**，保持类暖色框）、
  门控画成菱形，同一列是时间上重叠的一组操作（并行泳道上下排），列间就是一次换挡；
  默认是**单行长图**：所有列与门控从左到右排成一条，画布宽度按内容算（查看器里横向滚动）；
  给 `wrap_width` 时才蛇形折行（上行走右、下行走左，跨行连线走行间空隙）。
  外观：节点/菱形用渐变填充 + 柔和投影；**图面上不写判定文字**——T/U/F 字母、统计胶囊、
  条件清单都不画，菱形里只有一个序号；状态与依据只出现在悬停 `<title>` 与工作台详情里。
  节点圆内第一行写动作（"接近"而不是"接近燕麦杯"），下面两行小字写这一步的协同结构：
  蓝色＝主动执行器（谁在动），橙色＝同步保持的执行器（谁在保持——"提起"时"右手保持抓握"）；
  协同由原子动作表确定性推出（节点绑定的 motion/transition = 主动，同时段的 maintain = 保持，
  写进节点属性 `coordination`），不靠模型再推理；左侧配对执行器合并（右腿+左腿 → 双腿）。
  操作对象、七元组与证据仍在悬停详情、报告与工作台里。
  **泳道固定分区**（2026-10-08）：保持节点按类别落固定泳道——**手臂保持不动** 一类
  （位姿 / 托举 / 接触保持）在主轴**上方**，**保持抓握** 一类（grasp）在主轴**下方**
  （`_gs_col_offsets`：保持节点先按类别分区，操作节点再回主轴，主轴被同列另一个操作
  占用时才就近让位）。连续几个保持节点（保持抓握 → 保持位置 这种切换）因此各占一条固定
  水平线，进入线与持续约束线不会横穿别的保持节点。
  **保持类的线都锚在门控上**：进入线从门控右尖出（先折向本泳道再水平推进，不横穿主轴），
  持续约束线箭头指向门控的上 / 下尖（不落进菱形内部）；**连续保持切换**（一个保持停在某道
  门控、下一个保持从同一道门控起）同法。
  线型只表达一件事：门控 T 画实线；其余（U 等待 / F 阻断 / 持续约束）都是虚线，
  连线一律黑（`#1a1a1a`），只有实线与虚线两种线型。
  每条连线带 `data-from`/`data-to` 锤点，工作台靠它做点击联动。

HTML 结构由 `tools/check_html.py` 粗查（标签平衡、无未闭合）。

---

## 八、工具链 tools/

- **verify_contract.py**：用执行侧自己的加载器、实例化器、调度器验证导出的契约。
  四步：①加载（缺字段、依赖成环、MAINTAIN 缺 maintain_until 直接报错）→ ②实例化
  （`GraphInstantiator` 按 execution_policy 绑到 TaskContext，检验执行器/实现/资源/超时接得上）→
  ③Dummy 调度闭环（依赖顺序与并行资源、MAINTAIN 生命周期）→ ④列出还需注册的谓词检测器。
  退出码 0=通过、2=加载被拒、3=实例化失败、4=调度结构失败。**这是结构验证，不是"机器人已经能跑"**。
- **install_contract.py**：把契约装到执行侧约定目录（语义图→`操作图同事的/robot_operation_graph/
  semantic_graph/graphs/<名>.yaml`、策略→`.../executable_graph/policies/<名>.yaml`），用它自己的
  入口跑通证明接得上。以"由 video2op"标记识别自己导出的文件，同名手写图拒绝覆盖（`--force` 也一样）；
  `--list` 看来源、`--check-only` 只预览。安装≠可执行：仍缺谓词检测器、参数绑定与真实动作实现。
- **rebuild_semantics.py**：从已保存观测重建操作语义，输出到独立目录（源目录=输出目录会被拒绝，
  保护观测）。`--refresh-task` 只对 s02c 重调模型（不看视频）；`--reobserve-video` 重跑
  s02b_atomic+s02b_merge 并另存 observations.json。旧的 sync/conditions/rules/link 移入
  `previous_analysis`（不算当前验证）。
- **render_case.py**：不调模型重跑全部确定性阶段（s02e_prior → 规范化 → s06 → logic/operations/
  graph）并重渲染 + 导出契约 + 工作台——改规则后即时见效。
- **export_workbench.py**：把案例渲染成离线可交互页 `workbench.html`——实现本体在
  `video2op/workbench.py`，`run.py` 与 `render_case.py` 跑完会自动调用它，本脚本是 CLI 薄壳，
  用于单独重导出；主图直接是**门控状态机图**
  （与 `operations.svg` 同一张图、同一套布局）：点节点看七元组 / 子操作 / 能力→实现候选台阶，
  点菱形门控看这一跳的条件、状态（T/F/U）与依据，点连线看关系类型（连线带 `data-from`/`data-to` 锤点）；
  另附示范时间轴、九节点人工对照模板与谓词表。
- **show_case.py / show_detail.py / show_probe.py**：人工检查单案例关键内容/明细/探针结果。
- **stats.py / summarize_cases.py**：产物规模统计 / 多案例汇总。
- **selftest.py**：自检（模块导入、时序逻辑、DAG、SVG），不调模型。
- **probe_vlm.py / probe_vlm2.py**：模型能力探针（mp4 base64 输入；整段 vs 短窗口的细分程度、
  时间戳精度、并行识别）。
- **check_html.py / check_prior.py**：HTML 结构粗查 / 先验补全离线验证。

---

## 九、执行侧对接

### 契约导出（contract.py）

- **semantic_graph.yaml**：`graph_id`/`start_node`/`end_node`/`nodes{…}`。每节点 REQUIRED 键：
  `name`/`subject`/`object`/`pre`/`constraints`/`evaluator`/`post`/`implementation`/`dependencies`，
  可选 `phase`/`mode`/`maintain_until`。条件写成**谓词名**（指向谓词表原文）；
  `evaluator=Verify_{谓词}`；`implementation` 是执行侧实现词表的候选集（词表未收录走关键词兜底，
  原词记入 `unmapped_capabilities` 提醒补词表）。`START`/`END` 为固定哨兵；
  `END.pre` 等待本图真的会产生的状态。`x-video2op` 扩展段（执行侧加载器忽略、人复核用）记
  示范执行者、时间范围、证据引用、中文原文、推理结论。
- **execution_policy.yaml**：`implementations`（每节点取首选候选）、`parameter_bindings`/`timeouts`
  **留空**——参数与超时必须由接入时的真实执行器给，导出层编不出来；填不出来说明该操作还需能力补齐，
  不是可略过。`x-video2op.status=unbound`。
- **MAINTAIN 导出形态**：`mode=MAINTAIN`、`maintain_until` 单目标（保持守到其完成的那一步）、
  phase=覆盖步骤 phase 拼接（如 `transport_place`）、evaluator 无观测时按 hold_category 给建议检查项。

### 运行时（操作图同事的/）

执行链路：`TaskContext` → YAML → `GraphInstantiator` → EOG → `GraphScheduler`（10–20Hz）→
`ActionGateway` → 原子动作实现（如 `DummyAction`）→ `WorldState`。操作节点 dataclass 字段
（node_id/name/phase/subject/object/preconditions/constraints/evaluators/postconditions/
implementations/dependencies/mode/maintain_until）与契约 schema 一一对应（YAML 用简写
pre/evaluator/post/implementation）。四个案例实测用它的入口跑都是 `task=SUCCESS`。

验证与安装：

```bash
python tools/verify_contract.py 移动物体          # 四步结构验证
python tools/install_contract.py 移动物体        # 装到执行侧约定目录
python tools/install_contract.py --list           # 看装了哪些、哪些是它手写的
python tools/install_contract.py 移动物体 --check-only
cd 操作图同事的 && python main.py --graph 移动物体   # 用它自己的入口跑
```

> 这一步真的能抳出东西。第一次装进去跑是 `task=FAILED`：把同事图里 `END` 的前置条件
> `PlacementCompleted` 照抄过来，而本图里没有任何节点产生它——`END` 永远等不到。修成
> "`END` 等的条件必须是本图真的会产生的状态"，并加了校验（contract_handoff）盯着它。

---

## 十、测试

```bash
/home/wj/miniconda3/envs/study/bin/python -m pytest tests/ -q
```

确定性测试不调用模型；2026-11-11 实测 394 项全部通过，按文件细分：

- **test_merge.py**：跨窗口合并确定性——重叠窗口同动作合并、until 局部 id 重映射、状态补链、
  腿部交替识别（双臂不误判）、边界缝合与反义不合并、保持与移动重叠截断、关系去重。
- **test_prior.py**：先验补全——腿部站立支撑、姿态保持、接触期保持与姿态保持重叠去重、
  补到视频结束、补全动作 id 不冲突、释放期保持的幂等（短释放期重算不重复补）。
- **test_reasoning.py**：推理修正纪律——条件不成立时降级的是依赖关系而非删节点、无主条件只能登记
  候选缺口、环境默认前提不算缺口。
- **test_validate.py**：校验与纪律（s06）的确定性测试——参数纪律、状态链断裂、抓握/托举保持缺口、
  接触期手臂保持缺口、腿部状态覆盖、意图部位覆盖、引用完整性。
- **test_dag.py**：执行器级动作图——分层、剔环、并行同层、SVG 渲染。
- **test_common.py**：词表与归一化（vocab）单元测试——力角色纪律、腿脚一体归一化。
- **test_operations.py**：操作图与执行器语义程序——节点=操作（执行器仅属性）、先后/并行/交替显式成边、
  意图链数据可读可校验、传递约简、WHEN/DO/UNTIL、时刻表、伪代码。
- **test_gates.py**：门控——列按时间重叠切且保持节点并入它覆盖的那一步、一列一个门控、
  有观测才 T（无观测是 U 不是 F）、场景前提不进放行判定、门控条件必须来自七元组字段、
  图上线型跟随状态（T 实线 / 其余虚线）、图面全黑且不写 T/U/F 与证据文字、
  节点名隐去操作对象（细节退到悬停详情）、保持节点泳道分区（手臂保持在上 / 抓握保持在下）、
  保持类的线锚在门控上（进入线从门控出、持续约束线指向门控上下尖、连续保持切换同法）。
- **test_semantic_contract.py**：操作图评审回归（离线）——效果不能自证前提、首前提不默认成立、
  推理/继承/before 状态不算成功证据、效果全需证据且极性有效、保持覆盖边界、条件依赖成事件守卫
  而非实时启动许可、完成判定不回退视频时钟、推理保持不能证明不变式、并行≠端点同步、无据改写只能作候选。
- **test_contract_export.py**：导出层回归——约束元分类不阻塞可启动性、跨操作保持提升为 MAINTAIN 节点、
  释放拆分避免保持与释放抢执行器、物体状态保持（“保持〈物体〉在〈某处〉”）不提升且不妨碍
  释放拆分、保持终点资源冲突被报出、谓词名稳定、契约 schema 对齐执行侧、
  子操作展开的保持覆盖与检查点。

2026-11-11 全量回归没有遗留失败。新增交付测试覆盖任务结果分层、审阅边界、留出隔离、七元组守恒与待绑定接口。

---

## 十一、目录结构

```
video2op/
  config.py            全部可调参数（模型、端口、切片、阈值、纪律正则）
  llm.py               vLLM 客户端：视频/文本调用、JSON 提取修复、缓存、校验重试
  media.py             ffprobe 探测、切片、帧差运动分析（客观证据，供时间校准）
  vocab.py             部位/功能先验/静息态/模式/关系/约束/评价器词表、约束元三分类
  predicates.py        谓词化：条件文本 → 稳定谓词名 + 谓词表（不改写条件）
  operations.py        操作图（节点=操作，执行器是属性）：边推导、传递约简、意图链、分层、
                       保持节点提升、释放步骤拆分
  reasoning.py         推理修正：依赖能力校验、前置覆盖与缺口取证、持续约束、预期vs证据
  expand.py            子操作展开：可调度执行单元 + 关系（含保持覆盖）+ 检查点
  program.py           执行器语义程序：WHEN/DO/UNTIL 规则 + MAINTAIN 规则块 + 执行器时刻表 + 伪代码
  evidence.py          证据审计：matches/observed_state，推断不算成功证据
  graph.py             执行器级动作依赖图（DAG）：依赖边筛选、回边剔除、分层
  gates.py             门控（行为树 / 状态机）：列按时间重叠切，门控 T/F/U 判定，条件四来源
                       （换挡条件 / 必要前提 / 持续约束 / 场景前提）
  logic.py             时序逻辑表达（谓词式 + PLC 式）
  contract.py          可执行契约导出：semantic_graph.yaml + execution_policy.yaml
  render.py            门控状态机图（单行长图）+ 操作图卡片视图 + 时间轴 SVG + 执行器级动作图 SVG + 报告 HTML + 分部位动作叙述
  pipeline.py          编排、补全动作并入、保持缝合、参数净化、产物落盘
  prompts/             全部提示词（system / user 分开，便于单独调）
  stages/              各阶段实现（common + s01 ~ s07，见上文映射表）
tests/                 确定性测试（不调用模型）
tools/                 探针、验证、安装、重建与查看脚本（见第八节）
操作图同事的/           执行侧运行时（加载器 / 实例化器 / 调度器 / 动作网关），契约的接收方
```

调 prompt 就直接改 `video2op/prompts/*.txt`，缓存按提示词内容做指纹，改动会自动重跑对应阶段。

---

## 十二、已知边界

- **不做**机器人关节轨迹、控制器参数、精确力值、具身映射；`exerts_force` 只表达"有没有持续给力"。
- **导出的契约只到语义层**：`semantic_graph.yaml` 给的是节点、条件谓词、依赖、持续节点、
  实现候选。谓词检测器（视觉/力觉/关节反馈）、参数绑定、真实动作实现都在执行侧接；
  `tools/verify_contract.py` 跑的是**结构验证**（Dummy 动作 + 预置环境前提），
  它证明依赖顺序、资源占用和 MAINTAIN 生命周期接得上，**不证明真机能执行**。
- 时间戳来自模型对画面变化的判断，配了帧差运动证据做锚点，但**不是**毫米级标注；
  长视频按窗口切分后合并，边界动作靠"截断标记 + 文本相似"缝合。
- 遮挡、多人、剧烈镜头运动会让某些部位无法观测，这类情况进入 `missing_or_unclear` 或由规则补全并标记 `inferred=true`。
- 单视频保留特例；learn.py 可跨视频归纳目的、实现和候选条件。归纳结果的适用性与因果性按证据另行核验。

---

## 附录：修订记录

### 2026-10-08 放置与释放是两个节点；保持节点的泳道与线条锚点

燕麦杯案例跑出来的三条意见（对着早先跑对的“移动物体”修）。前两条在语义层，
第三条在渲染层：

1. **“放置”与“释放”必须是两个节点**（同一执行器上不拆会自锁，执行侧文档也这么要求）。
   燕麦杯原先拆不出来：那条“右臂保持燕麦杯在桌面近处位置”（12~14s）被当成独立的位姿
   保持提升成了 MAINTAIN 节点，`放置` 操作里就只剩“手指张开释放”一条动作，
   `_split_release_steps` 找不到“其它动作”可留在原位，拆分条件不成立。
2. **“保持在桌面近处位置”这类节点不该有**：它维持的是物体在世界中的位置，不是执行器
   自己的位姿——手臂只是停在原地等释放，不以操作为目的。新增判据 `vocab.is_self_hold()`：
   单操作覆盖的位姿保持，只有宾语是**执行器自身**（保持位置 / 保持伸出）才提升；
   “保持〈物体〉在〈某处〉”不提升，留在所属操作内部当步骤。判据一变，`放置`里剩下
   “手臂停在近处”、“释放”独立成 `node_4_release`，结构与移动物体一致（列序也一致：
   `[放置] [释放+保持位置]`，连续保持切换落在同一道门控上）。
3. **图面**：保持节点泳道固定分区——保持手臂不动一类（位姿/托举/接触）在主轴上方、
   保持抓握一类在主轴下方（`_gs_col_offsets`），连续保持切换各占一条水平线；保持类
   两条线都锚在门控上：进入线从门控右尖出，持续约束线箭头指向门控的上/下尖。
   修前燕麦杯图上三条持续约束线全部挤向同一道门控、且“保持抓握”的水平线横穿
   “保持位置”的圆——现在各走本泳道，不再互穿。

4. **顺手修一个重跑累积 bug**：s02e_prior 规则 6（释放期手臂保持）的幂等判定用固定秒数门槛
   （重叠 >0.3s），而短释放期（如 1.0~1.2s）补出的保持只有 0.2s，门槛永远不成立——
   `tools/render_case.py` 每重算一次就多一条同执行器、同动作、同时段的“右臂保持位置”
   （从冰箱取出蔬菜案例里已叠了三组）。改为“覆盖整个释放期（容差 0.05s）”后重算字节级稳定；
   该案例里已叠加的重复动作一次性清掉（保留最早一组），结构随之恢复：两个释放节点
   `node_1_release` / `node_2_release` 都拆了出来。

回归：燕麦杯重跑后操作图 10 节点 / 门控 5 个（T 3 · U 2 · F 0），校验 17 项（16 通过 1 提醒）；
移动物体重跑后节点/边/门控与修改前逐字段一致（只多了先前已加上的 `coordination` 属性，
图上泳道按新规则重排）；三个案例重跑两次 `result.json` / `operations.svg` 字节级一致（幂等）。
新增 5 条测试（`test_gates.py` 泳道与线条锚点 2 条、`test_contract_export.py` 物体状态保持
判据 1 条 + 物体状态保持不妨碍释放拆分 1 条、`test_prior.py` 短释放期幂等 1 条）。

### 2026-09-23 门控：从"先后关系图"到"带条件放行的状态机"

上一版的操作图能回答"先做哪个、哪个并行"，但回答不了领导最关心的问题：**这一跳凭什么放行？**
这一版把这句问话变成图上可核查的东西（新模块 `gates.py`，`operations.svg` 直接改成门控状态机图，
报告与工作台都按同一份数据展示）：

1. **门控点**：列与列之间一个菱形，条件 = 前序操作的效果 ∧ 下一操作的前置条件 ∧ 持续约束；
   四项来源都落在七元组上（`C_post` / `C_pre` / `pre_inferred` / `C_const`），不另造条件。
2. **三值判定**：T 实线（放行）/ F 阻断 / U 虚线（等待证据），**U 不当 T 也不当 F**；
   判定只读前面阶段已经写好的证据（`effect_evidence` / `pre_coverage` / `hold`），不重新解释证据。
   两个案例跑出来的 F 都是 0：证据不足一律记 U——这是纪律，不是缺功能。
3. **列按时间重叠切**（不是复用依赖图的 layer）：同列 = 同时在做，保持节点并入它覆盖的那一步，
   门控才落在真正的换挡点上；并行关系因此画成"同一列的上下泳道"，不再需要读者自己推断。
4. **场景前提单列一类**（反复出现在 ≥3 个前置里的世界状态）：记进明细，但不参与放行判定——
   否则"杯子还在桌上"这种话会永久拖住每一个门控。
5. **行为树式布局**：圆 = 操作，菱形 = 门控，默认**单行长图**（列与门控从左到右一条线，
   画布宽度按内容算，横向滚动查看）；跨行折行仍保留为可选参数（`gate_svg(..., wrap_width=2048)`）。

### 2026-09-24 门控图面收敛：只留动作与黑线

领导看过门控图后的四条意见，全部落在**渲染层**（不动 `result.json` 的语义数据）：

1. **隐去操作对象**：节点圆内只写动作（"接近"而不是"接近燕麦杯"），对象与执行器在七元组、
   子操作展开与悬停详情里给（`_gs_display_name` 只做显示层剥离，不碰数据）。
2. **保持覆盖的终点按覆盖范围取**：`maintain_until` 原先被映射成目标列**之前**那道门控，
   线会往回折；现在终点取 `covers ∪ maintain_until` 里最靠右那一步**之后**的道门（语义：
   保持到那一步完成，如"保持抓握"覆盖搬运到放置，就停在放置之后）；后面已无门控时终点收在
   "结束"圆左侧，竖线落在最后一列节点与结束圆之间，不沿主轴穿过节点。
3. **全黑、两种线型**：连线统一 `#1a1a1a`，只有实线（T 放行）与虚线（U 等待 / F 阻断 /
   持续约束），不再用灰蓝与橙色区分语义。
4. **不再画判定文字**：T/U/F 字母、T/U/F 统计胶囊、菱形里的条件清单与"另 N 条"提示全部撤掉，
   菱形只留序号；状态与依据仍在悬停 `<title>`、报告"门控明细"与工作台详情里可查。
   另外修掉两类多余线：主干连线不再把下一列的所有节点当放行目标（保持节点不是被放行的操作，
   它由前序操作建立），非 MAINTAIN 节点发起的 `maintain_until`（如"下蹲期双腿保持站立支撑"
   与主干完全重合）不再画线。保持节点自己的进入线单独画一条——由它左侧**紧邻**的那道门控
   进来（不按语义前驱取，否则会拉出向左跨列的折回线），保证线只向右。

测试加 **2 条**（黑线／无判定文字、节点只写动作），并同步 `tools/export_workbench.py` 与文档口径。

### 2026-09-24 工作台随分析自动生成

`workbench.html` 原先得手工跑 `tools/export_workbench.py <案例>` 才出现，跑完 `run.py` 的目录里
会缺这一份。现在实现本体搬进包内 `video2op/workbench.py`（`tools/export_workbench.py` 退化为
CLI 薄壳），`pipeline.run_case` 与 `tools/render_case.py` 在渲染阶段结束后自动调用
`workbench.export()`：跑完 `run.py data/<视频>.mp4` 就有 `output/<案例>/workbench.html`。
工作台是附加交互视图，导出失败只打印告警，不阻断主流程。

本版确定性测试加 **9 条**（`tests/test_gates.py`）。
操作图主产物 `operations.svg` 与工作台 `workbench.html` 的主图已换成门控状态机图
（卡片式操作图 `render.operation_svg` 保留为追溯视图，需要看节点缺口红条时用）。

### 2026-09-21 交付修订：从"操作图"到"执行侧拿得走的契约"

上一版把节点做成了操作，但条件还是自然语言、保持只是边上的一句标记、粒度停在任务阶段。
这一版补上三件事，每个案例多两份产物（semantic_graph.yaml / execution_policy.yaml）。
支撑它的四件新事（都在 result.json 里可查）：

1. **约束元分类**（vocab.py）：C_const 分 hold/safety/local 三类。分类之前两者一样待遇，
   结果每个操作都被标成"缺保持动作"，可启动性全是 false；现在只有真正没人承担的持续约束才阻塞
   （`startable=false`），安全类记 `delegated`。
2. **保持节点提升**（operations.py）：跨两个以上操作的保持动作提升为操作层 MAINTAIN 节点
   （`mode: MAINTAIN` + `maintain_until`），与执行侧 `A3_HOLD` / `A7` 同形。只覆盖单个操作的
   保持不提升；执行器在这段时间里还在干别的活的也不提升。
3. **释放步骤拆分**：被保持覆盖的操作里，"释放"那一步拆成独立节点，原节点按剩余动作重算执行器。
   不拆就死锁——保持节点占着终端执行器直到终点达成，而终点本身要抢它。执行侧那张图把
   "建立支撑"（不占夹爪）放在保持终点、"释放"（占夹爪）放在其后，正是这个道理。
4. **谓词化 + 子操作展开**（predicates.py / expand.py）：每条条件有稳定谓词名
   （GraspEstablished_RH / CollisionFree / NoSlip / PoseHeld），同一份输入永远得到同一个名字；
   谓词化只给条件命名，不改写条件、不放松证据。每个操作另外展开成子操作（建立/移动/保持）+
   关系（先后/并行/保持覆盖）+ 执行层要设的检查点。

本版确定性测试从 102 条加到 **123 条**，校验从 12 项加到 **16 项**。

### 2026-09-20 语义修订

- 操作节点保留 `required_capabilities`、`invariants`、`completion`、`observed_effects` 与逐项 `effect_evidence`。
- 视频观察增加 `operation_intent`（推测目的）和 `world_before/world_after`（可见世界状态）。原子节点必须只有一个执行器。
- 条件相似只提出候选关联。有效依赖需要先前操作的观测后状态；动作名、前状态、继承状态、推断补全不证明成功。
- 自由文本当前采用去标点后的完整匹配；同义但未规范化的条件保留待核实，不能当作不可能或失败。
- 首个节点的前提不默认成立；后续操作不能提供过去的前提；不相关的保持动作不能证明持续约束。
- `program.json` v2 提供操作命令、待绑定能力、`start_guard` / `stop_guard`、持续约束和失效处理要求。
  `startable=null` 表示仍需绑定和运行时检测，`false` 表示还有静态问题；静态分析不输出 `true`。
- `demonstration_graph` 保留按单执行器动作划分的证据节点、父操作引用与原始停止事件；复合操作和单执行器步骤分层表示。
- 并行表示时段重叠，不承诺同时开始/结束；示范秒数不用于目标机器人的调度。

重建已有案例（独立输出，保留原结果）：

```bash
cd /home/wj/codex-workspace/videostudy_operation
/home/wj/miniconda3/envs/study/bin/python tools/rebuild_semantics.py \
  output/搬物体/result.json output/搬物体_语义修订 --refresh-task
```

此命令重新生成操作节点并审计证据，不重新观看视频。需要重提视频观察时，把 `--refresh-task`
替换成 `--reobserve-video data/搬物体.mp4`。旧的同步检验/条件学习/规则/动作归属保存在
`previous_analysis`，避免把针对旧节点的分析冒充新版结论。完整视频流程仍使用 `run.py`。

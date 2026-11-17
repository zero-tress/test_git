# 视频学习第1—7步改造建议（基于服务器现状）
日期：2026-11-17
项目：/home/wj/codex-workspace/videostudy_operation
性质：设计建议；本次只读核对源码及产物，并新增本文档，未修改业务代码、模型服务、数据库或现有输出。

## 1. 结论与范围
单视频应完成“有证据、有歧义、有局部条件的特例学习”：步骤1、2、3，步骤4/5的实例级部分，以及步骤7的实例校验。跨视频负责步骤4/5的对比归纳、步骤6的语义聚合，以及步骤7的通用知识校验与固化。
步骤4、5不能只放在单视频一次完成。一个视频可能含多次成功/失败尝试，可提供局部对比；跨实例、跨实现的适用条件仍需集合学习。
当前阶段完成视频到知识的流程；控制器绑定、机器人执行、闭环进化作为后续接口。结构通过、视频效果得到支持、因果成立、机器人可执行是四件不同的事。

## 2. 本次服务器核对
- pipeline.py:186 已用两个客户端和线程并行执行 s02a_intent 与 s02b_atomic。
- stages/s02c_task.py 的 run 仍将 INTENTS 传入节点生成；它还限定节点名称与单臂/单手主体，因此现有节点主要是靠近/打开/抓取/移动等操作功能。
- intent_hierarchy.py 及 stages/s03_sync.py 已支持总任务候选、共存子任务及逐项解释性/可达性/状态一致性校验。这里应接续已有改动，而非重做平铺候选。
- pipeline.build_learning_graph 调用 single_actor.build 重建节点和依赖，并用生成的边覆盖 bundle.rules；原始规则保存在 source_analysis。
- single_actor.py 将部分观察顺序与抓取准备规则变成 required_dependency；靠近/打开的 parallel 带 semantic_independence。应区分观察事实、规则推导与因果假设。
- temporal_learning.py 已支持 Sequence/Parallel/Alternation/Branch/Synchronization，缺口主要是来源、证据等级及主图表示的一致性，而非重新加五个枚举。
- knowledge.py 已按 goal_key 归并、保留实现方式和来源；general_graph.py 已保留完整来源路径，防止不同路径随意拼接。这些应复用。
- condition_induction.py 已区分 success/failure/not_executed/unknown；明确未执行不是失败、条件缺失但成功可反驳必要性。应保留。
- skill_tuple.py 当前将跨视频技能级 C_pre/C_const 固定导出为空，候选条件主要留在 R 内。本次读取 output/current/knowledge_development/skill_tuples.json，6个技能的上述两字段均为空。
- 指定的 output/抓取2_semantic_v3 是指向 output/runs/single_video_layout_live_8032_20261115/抓取2_semantic_v3 的兼容入口。result.json 内含 semantic_graph、operations、graph；没有独立 G_case.json。当前图非终端节点为靠近、打开、抓取、移动。
- output/意图拿笔/merged_operation_graph.json 已有跨视频模型合并图，functional_realizations 为候选直接抓取/移障后抓取；仍主要是操作与条件门控图，尚不能直接等同于参考图二的“语义技能—多实现子图”结构。
- model_merged_graph.py 及上述合并产物显式采用 gate_before_end=false、completion_validation=false。可以保留不在图中画末端门控的展示约定，但新的知识包必须单独保存任务效果的评价规则和证据判定，不能从流程走到 END 推出目标成功。
- 工作区存在未提交的意图层级、绘图等修改。本建议不回退或覆盖这些修改。
以上为源码与保存产物核对；本次未重新运行模型或回归测试，历史验收记录不当作本次验证。

## 3. 单视频：学习边界及 G_case
输入视频及可选任务背景，背景仅作为假设上下文。
两条分支：
A. 意图候选：总任务/子任务、期望效果、支持及反对证据、初始评分。
B. 观察操作图：对象、动作区间、状态变化、观察到的时间关系；先不读取分支A的答案。
在同步阶段对两路做关联：意图能否解释动作、动作是否支持目标实现、前后状态是否一致。保留更新前后评分、被排除候选和未决项；不把解释评分当成成功概率。
现有 s02c_task 可保留用于对齐后的解释，但不能把受意图影响的结果再声称为独立观察证据。建议新增明确的 observed operation graph 输入契约，s03 首先用该契约核对。

G_case 表示该视频的实例知识：
- video_uid、analysis_id、来源及版本；
- intent_hypotheses、alignment、支持/反对证据；
- semantic_skill_instances：本视频中的清障/抓取目标/搬运/放置等语义实例，以目的和效果定义；
- operation_graph_ref：具体靠近/张开/接触/抓取/移动/释放的来源子图；
- realizes 映射：语义实例关联动作子图、对象角色、时间区间和局部结果；
- temporal_relations：事件区间与偏序、并行、交替、条件分支及同步；逐项记录依据；
- condition_observations、constraint_candidates、evaluator_candidates；
- task_outcome 与各局部技能 outcome 分别保存；
- validation 与 unresolved。

不要为符合示意图而固定补齐四个语义技能。拿起笔视频没有放置证据，就不添加“已执行放置”。未观察分支可作假设，但不能成为观察事实。
“打开状态已满足”不是“观察到一次打开动作”；持续握持优先作为约束，不凭空补保持动作。
G_case 的主事实来自已有 result.json 及新增 case_graph 字段；独立 G_case.json 是带来源版本/hash的导出契约，不允许双向分别编辑两份事实。

单视频输出建议：
- result.json：兼容现有入口与完整记录；
- operations.svg：保留用户指定的现有图型；
- workbench.html：保留交互审阅；
- G_case.json：新增明确、版本化的特例图接口；
- G_case.svg：新增语义技能实例与实现映射视图；
- 现有 skill_instances.json、clip/sequence.json 与片段继续复用。
G_case.svg 可先作为工作台的第二个视图，避免重画替换 operations.svg。

## 4. 多视频：两条归纳线，共用证据
A. 同一任务目的的 G_case 对齐，学习上层技能节点及其偏序/分支/同步结构。
B. 同一局部语义技能的实例对齐，比较不同实现及成功/失败/未执行证据，学习技能合同与 R 适用条件。
两条线沿用 learning_tracks.py，但以统一 case_graph/skill_instance 身份和来源引用衔接。

合并标准是“目的 + 角色绑定 + 预期/已观察效果的一致性 + 约束兼容性”。
例如清障要求目标相关的阻挡关系解除或可接近性改善；Push/Pull/GraspMove 是不同 R。移动过一个杯子但没有支持解除阻挡的证据，只能保留“移动杯子”及候选清障解释。
同名 Push 可能属于清障、关门、调整位置等不同功能；同名动作不能决定语义类别。goal_key 作为检索入口，还需检查效果、作用对象及约束，不能只靠标签相同强合并。
开放视频遇到既有词表未覆盖的目标时，允许未解析实例和候选新技能；经过审阅及契约检查再进入目录，不强塞已有模板。

保留完整来源路径与各节点所处状态，防止跨视频边的并集产生任何来源都没有支持的新路径。对新组合可作待验证候选，不能标成已观察实现。
失败案例保留在知识证据中；成功流程只是一个展示视图。整体任务成功不覆盖局部抓取失败，整体失败也不抹掉前面局部技能的成功。
只对可比较的技能、阶段、对象角色及环境上下文做条件对比；同一视频重分析和重复切片不增加独立支持数。

## 5. 条件、约束与评价规则
证据分开保存 truth(T/F/U)、provenance、review_status、binding_status；不要将这些不同维度压成一个 status。
必要条件候选：缺少该条件却成功的可比实例可反驳必要性。条件成立但失败不能证明该条件必要或无效；未执行仅提示选择/回避，不等于执行失败。
没有真实对比证据时输出候选及证据缺口。多个实现共享某因素、成功样本频繁出现某因素，都不能单独证明因果必要性。
每个候选记录 promote_to_skill / keep_under_realization / rejected / unresolved、适用范围、来源、反例、理由与待补证据。技能级只提升在声明范围内获得足够支持的条件；默认不把所有 R 的条件做并集。

保留项目七字段 X,O,C_pre,C_const,E,C_post,R。文稿若坚持“六元组”，可称“六元组主体 + 实现集合 R”，不要丢掉当前任何字段。
C_pre 是进入条件；C_const 是过程约束；C_post 是预期效果；E 说明怎样评价效果、过程及实现适用性。
E 可分 completion、process_constraint、implementation_applicability 三类，均有 unknown 行为及证据引用。
与控制有关的知识暂固化为能力/传感/状态需求、约束和未来绑定槽。人体视频不足以确定机器人控制器参数、策略程序或可用检测器；controller_ref/detector_ref 保留 unbound。
下层行为子图可呈现 Reach→Contact→StableGrasp 等观察到的实现结构；若输出 BT，它在此阶段是声明性草图，执行状态单独标记，不自动成为可运行机器人程序。

## 6. 时序与逻辑校验
每条关系至少含 relation、source_refs、basis、confidence/status：
- observed_order / observed_overlap：本视频观察；
- declared_rule：模板/人工规则；
- inferred_dependency / candidate_parallelism：可检验推断；
- supported_semantic_dependency：在给定范围内经证据支持的依赖。
观察到先后不能直接升级成必然前置；未观察到先后也不能据此认定并行。
偏序只约束 precedence 类关系；并行/同步按各自语义检查。交替与重试区分技能类型和事件出现次数，不能用一个普通 DAG 强行抹除重复。
Branch 保留条件和支持路径；Synchronization 保留参与节点、目标及 all/any 语义；U 分支不能默认为真。
类型/引用、前后置蕴含、时序可满足性、因果证据、实现效果覆盖、来源可追溯分别报告。C_post(A) 与 C_pre(B) 不必字符串相同，应结合环境状态检查是否支持；无法判断则 unresolved。
最终知识包分别报告 structure_valid、semantic_supported、causal_status、execution_binding_status。END 仅为图结构结束，成功由效果证据判定。

## 7. 多视频固定产物
建议每批次在 output/runs/<新批次>/knowledge/ 新建：
- G_semantic.json：任务语义操作图与技能引用；
- semantic_operation_graph.svg：参考图二的两层总览；
- skill_catalog.json：七字段技能合同及版本；
- realizations.json：R集合、实现子图、适用条件、来源；
- condition_decisions.json：条件提升/保留/否定及理由；
- validation.json：结构、语义、证据和绑定状态；
- workbench.html：从技能、R、条件跳回视频片段。
已有知识库导出尽量复用，通过索引和引用连接，避免再复制一套事实。

上层节点是语义技能实例/类型及目标效果，下层展开多个 R 的操作子图；点击清障才看 Push/Pull/GraspMove。每个 R 的动作和前置条件可以不同，但应覆盖所声明的技能效果。
无需先建设机器人运行层，即可完成图一第1—7步的工程流程和图二的视频知识部分。

## 8. 推荐实施顺序与源码位置
P0：先冻结契约和兼容产物。
修改 case_outputs.py、semantic.py，新增 case_graph 构建/导出；区分 action instance 与 semantic skill instance，保留现有 SVG、对象/证据引用和旧读取接口。
验收：抓取2仍有原风格 operations.svg；G_case 可定位每个技能对应的真实片段、未执行项和不确定结论。

P1：使意图与事实分支独立，并统一时间关系来源。
修改 pipeline.py、stages/s02c_task.py、stages/s03_sync.py、intent_hierarchy.py、learning_alignment.py、single_actor.py、temporal_learning.py。
验收：歧义样本保留多候选及逐项更新；实例图不受预设任务强行补动作；观察时间关系与规则推导可分辨。不能要求每个清晰样本也虚构多个候选。

P2：把已有双学习线接到语义技能层。
修改 learning_tracks.py、skill_episodes.py、knowledge.py、cross_video_alignment.py、general_graph.py。
验收：同目的/同效果不同实现形成一个技能下的多个 R；相同动作不同目的不会误合并；各来源路径可重建，失败/未知可追溯。

P3：完成条件归纳和固化决策。
修改 condition_induction.py、contrastive_learning.py、skill_tuple.py、semantic_checks.py；新增 condition promotion 决策导出。
验收：必要性反例可推翻候选；未执行不计失败；条件保留在 R 或提升到技能都有可核查理由；当前空字段不靠固定默认文本填满。

P4：输出参考图二的两层总览，并做独立留出验证。
修改 cross_video_render.py、cross_video_workbench.py 或新增 semantic_skill_render.py，与现有 model_merged_graph.py 的成功流程展示并存。
验收：上层技能点击能看到多个 R、实现子图与证据；没有证据的节点/分支不显示为已学会。冻结训练实例及其来源hash后再评估留出，报告技能归属、效果解释、实现覆盖与未知拒绝，禁止用留出标注先改知识再报告泛化。

所有后续代码、测试和计算在服务器已有 conda study 环境通过 cloud_wj 执行；模型调用如需网络另按当前会话授权执行。本次不触碰数据库技能表、共享版本库或服务。

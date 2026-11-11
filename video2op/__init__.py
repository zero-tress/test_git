#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video2op：把人体操作视频变成"执行器可读的任务语义操作图"。

流水线（与任务书五步对应）：
  ① 视角判别        stages/s01_viewpoint.py
  ② 2a 意图学习     stages/s02a_intent.py     （意图 + 置信度 + 所需身体部位）
     2b 操作图学习  stages/s02b_atomic.py     （执行器级原子动作，窗口化）
                    stages/s02b_merge.py      （跨窗口合并，确定性）
                    stages/s02c_task.py       （任务级节点，七元组）
                    stages/s02d_link.py       （动作链归属 + 缺失动作推理补全）
  ③ 同步因果检验    stages/s03_sync.py
  ④ 正反例条件学习  stages/s04_conditions.py
  ⑤ 语义层规则学习  stages/s05_rules.py
  ⑥ 一致性与参数纪律校验 + 渲染   stages/s06_validate.py, render.py
"""

__version__ = "1.1.0"

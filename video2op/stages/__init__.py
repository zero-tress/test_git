"""旧阶段导入路径。实际代码位于 video2op.single_video.stages。"""

import sys
from importlib import import_module

__all__ = (
    "common",
    "s01_viewpoint",
    "s02a_intent",
    "s02b_atomic",
    "s02b_merge",
    "s02c_task",
    "s02d_link",
    "s02e_prior",
    "s03_sync",
    "s04_conditions",
    "s05_rules",
    "s06_validate",
    "s07_purify",
    "s08_scope",
)

# 旧脚本与新流程共用模块对象，避免同一阶段被加载为两个版本。
for stage_name in __all__:
    stage = import_module(f"..single_video.stages.{stage_name}", __name__)
    globals()[stage_name] = stage
    sys.modules[f"{__name__}.{stage_name}"] = stage

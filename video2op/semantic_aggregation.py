"""旧导入路径，实际实现见 .cross_video.semantic_aggregation。"""

import sys

from .cross_video import semantic_aggregation

# 共用同一个模块对象，旧入口与新入口使用相同配置和运行状态。
sys.modules[__name__] = semantic_aggregation

"""旧导入路径，实际实现见 .single_video.pipeline。"""

import sys

from .single_video import pipeline

# 共用同一个模块对象，旧入口与新入口使用相同配置和运行状态。
sys.modules[__name__] = pipeline

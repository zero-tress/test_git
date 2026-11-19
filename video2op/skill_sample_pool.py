"""旧导入路径，实际实现见 .cross_video.skill_sample_pool。"""

import sys

from .cross_video import skill_sample_pool

# 共用同一个模块对象，旧入口与新入口使用相同配置和运行状态。
sys.modules[__name__] = skill_sample_pool

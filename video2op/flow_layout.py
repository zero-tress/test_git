"""旧导入路径，实际实现见 .presentation.flow_layout。"""

import sys

from .presentation import flow_layout

# 共用同一个模块对象，旧入口与新入口使用相同配置和运行状态。
sys.modules[__name__] = flow_layout

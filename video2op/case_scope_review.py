"""旧导入路径，实际实现见 .single_video.case_scope_review。"""

import sys

from .single_video import case_scope_review

# 共用同一个模块对象，旧入口与新入口使用相同配置和运行状态。
sys.modules[__name__] = case_scope_review

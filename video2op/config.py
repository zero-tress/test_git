#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video2op 全局配置。

约定：所有可调参数集中于此，支持环境变量覆盖，便于换机器/换端口。
"""

from __future__ import annotations

import os
from pathlib import Path

# ---- 路径 ----
PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent                       # 项目根目录
DATA_DIR = ROOT / "data"                    # 输入视频
OUTPUT_DIR = ROOT / "output" / "runs"       # 单视频产物；CLI再按运行时间隔离
PROMPTS_DIR = PKG_DIR / "prompts"           # 外置提示词
WORK_DIR = OUTPUT_DIR / "_work"             # 切片等中间文件

# ---- 模型服务（vLLM OpenAI 兼容接口，卡1）----
BASE_URL = os.environ.get("V2O_BASE_URL", "http://127.0.0.1:8032")
MODEL = os.environ.get("V2O_MODEL", "qwen3.8-27b")

# ---- 调用参数 ----
TEMPERATURE = 0.1
RETRY_TEMPERATURE_STEP = 0.15
MAX_ATTEMPTS = 3
VIDEO_TIMEOUT = 1800.0
TEXT_TIMEOUT = 900.0
VIDEO_MAX_TOKENS = 16840
TEXT_MAX_TOKENS = 16840
REQUEST_CONNECT_TIMEOUT = 30.0

# ---- 视频处理 ----
CLIP_WIDTH = 704                # 送模型前的缩放宽度（控制视觉 token）
CLIP_FPS = 8                    # 送模型前的采样帧率
CLIP_CRF = 28                   # x264 质量
WINDOW_SECONDS = 8.0            # 长视频切窗目标时长
WINDOW_OVERLAP_SECONDS = 0.6    # 相邻窗口重叠（用于边界动作缝合）
SINGLE_SHOT_MAX_SECONDS = 20.0  # 不超过该时长直接整段分析

MOTION_SAMPLE_STRIDE = 2        # 运动分析抽帧步长
MOTION_DIFF_THRESHOLD = 16      # 帧差二值化阈值（灰度）
MOTION_SMOOTH_WIN = 5           # 运动能量平滑窗口（采样点）
MOTION_CHANGE_MIN_GAP = 0.8     # 变化点最小间隔（秒）

# ---- 证据与置信度 ----
CONFIDENCE_FLOOR = 0.35         # 低于该值的结论标记 needs_review
DEFAULT_INTENT_CONFIDENCE = 0.5

# ---- 语义参数纪律 ----
# 输出中禁止出现具体数值参数（角度/距离/力值），只允许定性描述。
FORBIDDEN_PARAM_PATTERNS = [
    r"\d+(?:\.\d+)?\s*(?:度|°|deg|degree)",
    r"\d+(?:\.\d+)?\s*(?:厘米|cm|毫米|mm|米|m|米/秒|m/s)\b",
    r"\d+(?:\.\d+)?\s*(?:牛顿|N|kg|千克|克|斤)\b",
    r"(?:角度|幅度|速度|力值|力矩)\D{0,4}\d",
]

# 精简输出而不跳过分析阶段；预算是上限，不是期望输出长度。
STAGE_MAX_TOKENS = {
    "s01_viewpoint": 1024, "s02a_intent": 4096,
    "s02b_atomic": 12000, "s02c_task": 8000, "s02d_link": 6000,
    "s03_sync": 8192, "s04_conditions": 10000, "s05_rules": 6000,
    "s07_purify": 4096,
}
CACHE_VERSION = "operation-v2"

# ---- 视频整体理解 + 关键状态帧 + 局部复查 ----
KEYFRAMES_ENABLED = os.environ.get("V2O_KEYFRAMES", "1") != "0"
KEYFRAME_CANDIDATE_FPS = 8.0
KEYFRAME_MAX_PER_WINDOW = 9
LOCAL_REVIEW_ENABLED = os.environ.get("V2O_LOCAL_REVIEW", "1") != "0"
LOCAL_REVIEW_MAX_WINDOWS = 3
LOCAL_REVIEW_MAX_SECONDS = 4.0
LOCAL_REVIEW_MAX_FRAMES = 9
LOCAL_REVIEW_FPS = 16
LOCAL_REVIEW_CONFIDENCE = 0.65

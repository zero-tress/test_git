"""Analyze the user's pen examples through the normal pipeline; loopback 8032 only."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config
from video2op.llm import VLMClient
from video2op.single_video.pipeline import run_case
from video2op.skill_clips import save


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--allow-8032", action="store_true")
    args = ap.parse_args(argv)
    endpoint = urlparse(config.BASE_URL)
    if not args.allow_8032 or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.port != 8032:
        ap.error("Only the authorized existing loopback 8032 service is allowed")
    config.OUTPUT_DIR = args.out.resolve()
    config.WORK_DIR = config.OUTPUT_DIR / "_work"
    config.MAX_ATTEMPTS = 2
    config.VIDEO_TIMEOUT = 300
    config.TEXT_TIMEOUT = 300
    original = VLMClient.__init__

    def bounded(self, *a, **kw):
        original(self, *a, **kw)
        self.session.trust_env = False
        post = self.session.post
        self.session.post = lambda *pa, **pk: post(*pa, **{**pk, "allow_redirects": False})

    VLMClient.__init__ = bounded
    bundle = run_case(
        args.video,
        description="用户提供的任务目标是从桌面拿起笔，使笔被持有并离开原支撑。此文字只说明任务意图，实际动作、路径及是否成功必须以视频为准。",
    )
    save(
        config.OUTPUT_DIR / (bundle["meta"]["name"] + "_semantic_v3") / "input_goal.json",
        {
            "goal_key": "acquire_object",
            "target_category": "pen",
            "statement": "拿起笔",
            "origin": "user_provided_goal",
            "observed_success": False,
        },
    )
    print(
        json.dumps(
            {
                "video": str(args.video),
                "validation": bundle["validation"]["summary"],
                "calls": bundle["pipeline"]["llm_stats"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return int(bool(bundle.get("errors")) or not bundle["validation"]["passed"])


if __name__ == "__main__":
    raise SystemExit(main())

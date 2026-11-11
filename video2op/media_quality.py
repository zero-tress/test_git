"""Read-only decode audit. A successful graph build does not prove complete video coverage."""
from __future__ import annotations

import subprocess


def audit(video, timeout=60):
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(video),
                            "-map", "0:v:0", "-an", "-progress", "pipe:1", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "not_verified", "coverage_verified": False,
                "reason": str(exc), "decoded_frames": None, "decoded_until_seconds": None}
    progress = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            progress[key] = value.strip()
    try:
        frames = int(progress.get("frame", 0))
        seconds = int(progress.get("out_time_us", 0)) / 1_000_000
    except ValueError:
        frames, seconds = 0, 0
    clean = r.returncode == 0 and not r.stderr.strip() and frames > 0
    return {"status": "ok" if clean else "decode_warning", "coverage_verified": clean,
            "decoder_returncode": r.returncode, "decoded_frames": frames,
            "decoded_until_seconds": seconds, "diagnostics": r.stderr[:5000],
            "policy": "Decode warnings require review; unavailable tail is not negative task evidence."}


def annotate(bundle):
    quality = (bundle.get("meta") or {}).get("media_quality") or {}
    end = quality.get("decoded_until_seconds")
    if quality.get("status") == "decode_warning" and end is not None:
        for a in (bundle.get("atomic") or {}).get("atomic_actions") or []:
            if a.get("end", 0) > end + 0.05:
                a["media_coverage_status"] = "outside_decoded_coverage"
            else:
                a["media_coverage_status"] = "available_prefix_with_decoder_warning"
    return quality

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3.8-27B（vLLM OpenAI 兼容接口）客户端。

职责：
  1. 视频 / 文本两种调用（视频以 data:video/mp4;base64 内联发送）
  2. 输出 JSON 提取与修复（剥离 thinking、代码围栏、截断补全）
  3. 按 (阶段, 提示词, 视频, 模型, 参数) 指纹做磁盘缓存
  4. 校验器失败自动重试（温度微调，避免重复踩同一个坑）
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from . import config

_THINK_RE = re.compile(r"</think(?:ing)?>", re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


class LLMError(RuntimeError):
    def __init__(self, message: str, raw: list[str] | None = None,
                 errors: list[str] | None = None):
        super().__init__(message)
        self.raw = list(raw or [])
        self.errors = list(errors or [])


def strip_thinking(text: str) -> str:
    matches = list(_THINK_RE.finditer(text))
    if matches:
        text = text[matches[-1].end():]
    return text.strip()


def _repair_truncated(text: str) -> str | None:
    """尽力补齐被截断的 JSON（闭合字符串与括号，必要时砍掉尾部残句）。"""
    def _close(s: str) -> str | None:
        stack: list[str] = []
        in_str = False
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack:
                    stack.pop()
        if in_str:
            s += '"'
        s += "".join(reversed(stack))
        return s

    if not text.strip():
        return None
    for cut in range(0, min(len(text), 400), 20):
        tail = text[:len(text) - cut] if cut else text
        tail = tail.rstrip().rstrip(",")
        try:
            json.loads(_close(tail))
            return _close(tail)
        except Exception:
            continue
    return None


def extract_json(text: str) -> Any:
    """从模型输出中提取 JSON 对象。"""
    text = strip_thinking(text)
    if not text:
        raise LLMError("模型输出为空")
    candidates: list[str] = []
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text)
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        candidates.append(text[i:j + 1])
    errors: list[str] = []
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        try:
            return json.loads(cand)
        except Exception as e:
            errors.append(str(e))
        fixed = _repair_truncated(cand)
        if fixed is not None:
            try:
                return json.loads(fixed)
            except Exception as e:
                errors.append(str(e))
    raise LLMError(f"JSON 解析失败：{errors[-1] if errors else '未知'}", [text[:800]])


class VLMClient:
    """Content-addressed cache, complete JSON, bounded retries and per-attempt metrics."""

    def __init__(self, cache_dir: Path, base_url: str | None = None,
                 model: str | None = None, use_cache: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.model = model or config.MODEL
        self.use_cache = use_cache
        self.session = requests.Session()
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0, "seconds": 0.0,
                      "attempts": []}

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _fingerprint(self, stage: str, system: str, user_text: str,
                     video_id: str, temperature: float, max_tokens: int = 0) -> str:
        h = hashlib.sha1()
        for s in (config.CACHE_VERSION, stage, system, user_text, video_id,
                  self.base_url, self.model, str(max_tokens), f"{temperature:.3f}"):
            h.update(s.encode())
            h.update(b"\x00")
        return f"{stage}_{h.hexdigest()[:16]}"

    def ask(self, *, stage: str, system: str, user_text: str,
            video: Path | None = None, video_id: str = "",
            images: list[dict] | None = None,
            validator: Callable[[Any], None] | None = None,
            temperature: float | None = None, max_tokens: int | None = None,
            attempts: int | None = None, timeout: float | None = None) -> Any:
        temperature = config.TEMPERATURE if temperature is None else temperature
        attempts = attempts or config.MAX_ATTEMPTS
        has_video = video is not None or bool(images)
        limit = config.VIDEO_MAX_TOKENS if has_video else config.TEXT_MAX_TOKENS
        stage_name = "s02b_atomic" if stage.startswith("s02b_atomic_w") else stage
        budget = max_tokens or config.STAGE_MAX_TOKENS.get(stage_name, limit)
        limit = max(limit, budget)
        timeout = timeout or (config.VIDEO_TIMEOUT if has_video else config.TEXT_TIMEOUT)

        video_bytes = Path(video).read_bytes() if video is not None else None
        # Always include actual bytes: sampling, resolution or source replacement
        # must invalidate the request cache, even when the logical video_id is fixed.
        vid_id = video_id
        if video_bytes is not None:
            vid_id += "#" + hashlib.sha1(video_bytes).hexdigest()
        image_inputs = []
        for image in images or []:
            path = Path(image["path"])
            data = path.read_bytes()
            label = (f'源视频帧 {image["frame_id"]}；全局时间 {image["timestamp"]:.6f}s。'
                     '选帧阶段不证明接触或动作；请读取画面。')
            vid_id += "#" + hashlib.sha256(data + label.encode()).hexdigest()
            image_inputs.append((data, label, "image/png" if path.suffix.lower() == ".png" else "image/jpeg"))
        key = self._fingerprint(stage, system, user_text, vid_id, temperature, budget)
        cache_path = self._cache_path(key)
        if self.use_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("complete") is not True:
                    raise ValueError("legacy cache has no completeness marker")
                if validator is not None:
                    validator(cached["result"])
                self.stats["cache_hits"] += 1
                self.stats["attempts"].append({"stage": stage, "cache_hit": True,
                                               "seconds": 0.0})
                print(f"    [cache] {stage}")
                return cached["result"]
            except (ValueError, KeyError, TypeError):
                pass

        content_parts = []
        if video_bytes is not None:
            b64 = base64.b64encode(video_bytes).decode()
            content_parts.append({"type": "video_url",
                                  "video_url": {"url": f"data:video/mp4;base64,{b64}"}})
        for data, label, mime in image_inputs:
            content_parts.append({"type": "text", "text": label})
            content_parts.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64," + base64.b64encode(data).decode()}})
        content_parts.append({"type": "text", "text": user_text})
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": content_parts if has_video else user_text}]
        raw_outputs, errors = [], []
        for attempt in range(attempts):
            payload = {"model": self.model, "messages": messages,
                       "temperature": round(temperature + attempt * config.RETRY_TEMPERATURE_STEP, 3),
                       "max_tokens": budget,
                       "chat_template_kwargs": {"enable_thinking": False}}
            metric = {"stage": stage, "attempt": attempt + 1, "cache_hit": False,
                      "max_tokens": budget, "input_chars": len(system) + len(user_text)}
            t0 = time.perf_counter()
            self.stats["calls"] += 1
            try:
                r = self.session.post(f"{self.base_url}/v1/chat/completions",
                                      json=payload,
                                      timeout=(config.REQUEST_CONNECT_TIMEOUT, timeout))
                if r.status_code != 200:
                    raise LLMError(f"HTTP {r.status_code}")
                response = r.json()
                choice = response["choices"][0]
                content = choice["message"].get("content") or ""
                metric.update({"output_chars": len(content),
                               "usage": response.get("usage") or {},
                               "finish_reason": choice.get("finish_reason")})
                raw_outputs.append(content)
                if choice.get("finish_reason") == "length":
                    budget = min(limit, max(budget + 1024, int(budget * 1.5)))
                    raise LLMError("output truncated; retry with expanded budget")
                if choice.get("finish_reason") not in (None, "stop"):
                    raise LLMError("model did not finish a normal response")
                # Do not salvage a truncated list by closing brackets: a valid
                # prefix can omit entire operations and still pass shallow checks.
                text = strip_thinking(content)
                fence = _FENCE_RE.search(text)
                result = json.loads(fence.group(1) if fence else text)
                if validator is not None:
                    validator(result)
                metric["status"] = "ok"
                dt = time.perf_counter() - t0
                cache_path.write_text(json.dumps(
                    {"stage": stage, "result": result, "complete": True,
                     "seconds": round(dt, 3), "attempt": attempt + 1,
                     "usage": metric["usage"], "output_chars": len(content)},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"    [ok] {stage} ({dt:.1f}s)")
                return result
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                errors.append(message)
                metric.update({"status": "error", "error": message[:300]})
                print(f"    [!] {stage} {message[:120]}")
                # Feed validation failures back, rather than repeating an identical request.
                messages = [*messages[:2], {"role": "user", "content":
                    "上次输出未通过校验，请完整重新输出并修正：" + message[:500]}]
                if isinstance(exc, requests.exceptions.ConnectionError):
                    break  # unavailable endpoint: do not wait through three identical failures
            finally:
                dt = time.perf_counter() - t0
                metric["seconds"] = round(dt, 3)
                self.stats["seconds"] += dt
                self.stats["attempts"].append(metric)
        self.stats["failures"] += 1
        raise LLMError(f"{stage} 在 {len(errors)} 次尝试后仍失败", raw_outputs, errors)

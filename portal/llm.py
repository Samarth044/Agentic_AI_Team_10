"""Thin Groq wrapper. Every call is written to the audit log (prompt log) with
model, latency and token count.

Kept light on the free tier: low reasoning effort for gpt-oss models, at most
two calls at once, back-off on HTTP 429. If the key is missing or a call
fails, the caller's deterministic fallback is used and the result is
labelled mode="offline", so the portal always works and shows honestly
which path produced the output."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable

from . import config
from .guardrails import audit

_client = None
last_error = ""   # shown in the UI so a broken key is visible


def _fail(e: Exception) -> None:
    global last_error
    last_error = str(e)[:200]


def _ok() -> None:
    global last_error
    last_error = ""


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=config.GROQ_API_KEY, timeout=40, max_retries=0)
    return _client


_slots = threading.Semaphore(2)  # free-tier token-per-minute limits: keep concurrency low


def _create(**kw):
    """One completion call with back-off on rate limits (HTTP 429)."""
    if "gpt-oss" in kw.get("model", ""):
        kw.setdefault("reasoning_effort", "low")  # far fewer hidden reasoning tokens
    for attempt in range(5):
        try:
            with _slots:
                return client().chat.completions.create(**kw)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" not in msg or attempt == 4:
                raise
            m = re.search(r"try again in ([\d.]+)s", msg)
            time.sleep(min(20.0, float(m.group(1)) + 0.5 if m else 5.0 * (attempt + 1)))


def _usage(resp) -> int | None:
    u = getattr(resp, "usage", None)
    return getattr(u, "total_tokens", None)


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(agent: str, system: str, user: str, fallback: Callable[[], dict],
              fast: bool = False, run_id: str | None = None,
              record_id: str | None = None) -> tuple[dict, str]:
    """Ask the model for a JSON object. Returns (data, mode)."""
    model = config.MODEL_FAST if fast else config.MODEL_PRIMARY
    if not available():
        audit("llm", agent, "offline_fallback", {"reason": "GROQ_API_KEY not set", "prompt": user[:600]},
              record_id, run_id)
        return fallback(), "offline"
    t = time.perf_counter()
    try:
        resp = _create(model=model, temperature=0.2, response_format={"type": "json_object"},
                       messages=[{"role": "system", "content": system + "\n\nRespond with one JSON object only."},
                                 {"role": "user", "content": user}])
        text = resp.choices[0].message.content
        data = _extract_json(text)
        audit("llm", agent, "model_call", {"model": model, "ms": round((time.perf_counter() - t) * 1000),
                                           "tokens": _usage(resp), "prompt": user[:1500],
                                           "response": text[:1500]}, record_id, run_id)
        _ok()
        return data, "llm"
    except Exception as e:  # network, quota, bad JSON: degrade, never crash the workflow
        _fail(e)
        audit("llm", agent, "llm_error_fallback", {"model": model, "error": str(e)[:300]}, record_id, run_id)
        return fallback(), "offline"


def chat_tools(agent: str, messages: list[dict], tools: list[dict]):
    """One function-calling round trip (Career Assistant). Returns the assistant message."""
    t = time.perf_counter()
    resp = _create(model=config.MODEL_PRIMARY, temperature=0, messages=messages, tools=tools,
                   tool_choice="auto")
    msg = resp.choices[0].message
    audit("llm", agent, "model_call", {
        "model": config.MODEL_PRIMARY, "ms": round((time.perf_counter() - t) * 1000), "tokens": _usage(resp),
        "function_calls": [tc.function.name for tc in (msg.tool_calls or [])],
        "prompt": str(messages[-1].get("content", ""))[:600], "response": (msg.content or "")[:800]})
    _ok()
    return msg

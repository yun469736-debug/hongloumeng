# -*- coding: utf-8 -*-
"""模型提供器：默认本地 Ollama，可由前端临时传入 DeepSeek 密钥切到 DeepSeek。

两个提供器输出同一套事件协议，切换时前端无需改动。

关于密钥：密钥只随请求传进来、只在内存里活到这次调用结束；
校验结果按密钥的 SHA-256 指纹缓存若干分钟，**从不落盘、也从不写进日志**。
dataclass 的 api_key 字段一律 repr=False，免得异常回溯里带出密钥。
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, Sequence

from agent.config import settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """模型调用失败。"""


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> str:
        ...

    def stream(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> Iterator[str]:
        ...


def _content_of(response: Any) -> str:
    if isinstance(response, dict):
        message = response.get("message") or {}
        return message.get("content") or ""
    message = getattr(response, "message", None)
    return getattr(message, "content", "") or ""


def _apply_schema(payload: list[dict], schema: dict | None) -> list[dict]:
    """不支持 schema 约束的提供器：把结构写进系统提示，退而求其次。"""
    if schema is None or not payload or payload[0].get("role") != "system":
        return payload
    import json

    merged = list(payload)
    merged[0] = {
        "role": "system",
        "content": merged[0]["content"] + "\n\n严格遵循以下 JSON Schema：\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
    }
    return merged


@dataclass
class OllamaProvider:
    """本地 Ollama。默认关闭思考模式、限制上下文长度，以保证首句及时返回。"""

    name: str = "ollama"
    model: str = ""
    _client: Any = field(default=None, repr=False, compare=False)
    _supports_think: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        import ollama

        self.model = self.model or settings.ollama_model
        self._client = ollama.Client(host=settings.ollama_host, trust_env=False, timeout=900)
        try:
            self._supports_think = "think" in inspect.signature(self._client.chat).parameters
        except (TypeError, ValueError):
            self._supports_think = False

    def _options(self, max_tokens: int | None) -> dict:
        return {
            "num_ctx": settings.num_ctx,
            "num_predict": max_tokens or settings.num_predict,
            "temperature": settings.temperature,
        }

    def _kwargs(self, messages: Sequence[dict], max_tokens: int | None, schema: dict | None, json_mode: bool) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "options": self._options(max_tokens),
            "keep_alive": settings.keep_alive,
        }
        if schema is not None:
            # 结构化输出：由服务端语法约束 JSON 结构与枚举，杜绝格式跑偏
            kwargs["format"] = schema
        elif json_mode:
            kwargs["format"] = "json"
        if self._supports_think:
            kwargs["think"] = settings.think
        return kwargs

    def complete(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> str:
        kwargs = self._kwargs(messages, max_tokens, schema, json_mode)
        try:
            response = self._client.chat(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama 调用失败：{exc}") from exc
        content = _content_of(response)
        if not content.strip():
            raise LLMError("Ollama 返回了空内容。")
        return content

    def stream(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> Iterator[str]:
        kwargs = self._kwargs(messages, max_tokens, schema, json_mode)
        kwargs["stream"] = True
        try:
            parts = self._client.chat(**kwargs)
            for part in parts:
                content = _content_of(part)
                if content:
                    yield content
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama 流式调用失败：{exc}") from exc


@dataclass
class DeepSeekProvider:
    """DeepSeek 开放平台适配器。

    密钥来源二选一：随请求传入的 api_key（前端用户自己填的，优先），
    或 .env 里的 DEEPSEEK_API_KEY（给脚本/接口调用用）。
    """

    name: str = "deepseek"
    model: str = ""
    api_key: str = field(default="", repr=False, compare=False)
    _client: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        from openai import OpenAI

        key = (self.api_key or settings.deepseek_api_key or "").strip()
        if not key:
            raise LLMError("缺少 DeepSeek 密钥，无法启用 DeepSeek 提供器。")
        self.api_key = key
        self.model = self.model or settings.deepseek_model
        self._client = OpenAI(api_key=key, base_url=settings.deepseek_base_url)

    def _kwargs(self, messages: Sequence[dict], max_tokens: int | None, schema: dict | None, json_mode: bool) -> dict:
        payload = _apply_schema(list(messages), schema)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "temperature": settings.temperature,
            "max_tokens": max_tokens or settings.num_predict,
        }
        if json_mode or schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def complete(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> str:
        try:
            response = self._client.chat.completions.create(**self._kwargs(messages, max_tokens, schema, json_mode))
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"DeepSeek 调用失败：{exc}") from exc
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise LLMError("DeepSeek 返回了空内容。")
        return content

    def stream(
        self,
        messages: Sequence[dict],
        json_mode: bool = True,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> Iterator[str]:
        kwargs = self._kwargs(messages, max_tokens, schema, json_mode)
        kwargs["stream"] = True
        try:
            for chunk in self._client.chat.completions.create(**kwargs):
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"DeepSeek 流式调用失败：{exc}") from exc


def _explain(exc: Exception) -> str:
    """把 SDK 异常翻成一句人话，便于直接显示给用户。"""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "密钥无效或无权访问"
    if status == 402:
        return "账户余额不足"
    if status == 429:
        return "请求过于频繁"
    if status == 404:
        return "接口地址或模型名有误"
    if status:
        return f"接口返回 {status}"
    text = str(exc).strip()
    return text[:80] if text else "无法连接 DeepSeek"


# 校验结论按密钥指纹缓存：只存 sha256 前 16 位，不存密钥本身
_KEY_VERDICTS: dict[str, tuple[float, bool, str]] = {}
_KEY_TTL_SECONDS = 600.0


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def check_deepseek_key(api_key: str, *, use_cache: bool = True) -> tuple[bool, str]:
    """校验 DeepSeek 密钥，返回 (是否可用, 不可用原因)。

    用 models.list() 做一次只读探测：不消耗生成额度，也能把 401 分辨出来。
    """
    key = (api_key or "").strip()
    if not key:
        return False, "密钥为空"

    fingerprint = _fingerprint(key)
    now = time.time()
    if use_cache:
        hit = _KEY_VERDICTS.get(fingerprint)
        if hit and now - hit[0] < _KEY_TTL_SECONDS:
            return hit[1], hit[2]

    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=settings.deepseek_base_url, timeout=20)
        client.models.list()
        ok, detail = True, ""
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, _explain(exc)

    _KEY_VERDICTS[fingerprint] = (now, ok, detail)
    return ok, detail


def get_provider(api_key: str | None = None) -> LLMProvider:
    """按传入密钥选提供器；没传密钥时退回 .env 配置（默认本地 Ollama）。"""
    key = (api_key or "").strip()
    if key:
        return DeepSeekProvider(api_key=key)
    if settings.llm_provider.strip().lower() == "deepseek":
        logger.warning("已按 .env 配置启用 DeepSeek 提供器（非默认自托管链路）。")
        return DeepSeekProvider()
    return OllamaProvider()


def resolve_provider(api_key: str | None = None) -> tuple[LLMProvider, str]:
    """选好提供器，并给出需要告知用户的提示。

    前端填了密钥就以它为准：校验通过走 DeepSeek，校验不过就**退回本地**并带回一句
    "密钥错误"。没填密钥则按 .env 配置，默认就是本地。
    """
    key = (api_key or "").strip()
    if not key:
        return get_provider(), ""

    ok, detail = check_deepseek_key(key)
    if ok:
        return DeepSeekProvider(api_key=key), ""
    logger.warning("DeepSeek 密钥校验未通过（%s），本轮改用本地模型。", detail)
    return get_provider(), f"DeepSeek 密钥错误：{detail}。已改用本地模型。"

"""LLM 适配层：统一封装 OpenAI 兼容协议的大模型调用。

所有 LLM 调用必须经由本模块，出口处统一过 sanitizer，确保数据边界约束。
"""
import json
import logging
import time

import httpx

from ..config import get_settings
from .sanitizer import sanitize

logger = logging.getLogger(__name__)

# LLM 调用计数器（spike 成本评估用）
_call_count = 0


def reset_call_count() -> None:
    global _call_count
    _call_count = 0


def get_call_count() -> int:
    return _call_count


class LLMError(Exception):
    pass


class LLMAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.llm_base_url.rstrip("/")
        self.api_key = self.settings.llm_api_key
        self.model = self.settings.llm_model
        self.timeout = self.settings.llm_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        """调用 chat completions，返回完整响应 JSON（含 tool_calls / content）。"""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens

        # 统一出口 sanitize：messages 中的文本内容打码后出域
        sanitized_messages = self._sanitize_messages(messages)

        url = f"{self.base_url}/chat/completions"
        global _call_count
        _call_count += 1  # 每次 chat() 调用计数（成本代理）
        for attempt in range(3):  # 适配层重试 2 次（共 3 次调用）
            try:
                resp = httpx.post(
                    url,
                    headers=self._headers(),
                    json={**payload, "messages": sanitized_messages},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning("LLM HTTP error (attempt %d): %s", attempt + 1, e)
                if attempt == 2:
                    raise LLMError(f"LLM 调用失败: {e.response.text[:500]}") from e
            except httpx.HTTPError as e:
                logger.warning("LLM transport error (attempt %d): %s", attempt + 1, e)
                if attempt == 2:
                    raise LLMError(f"LLM 调用失败: {e}") from e
            time.sleep(2 * (attempt + 1))  # 指数退避，缓解网络抖动
        raise LLMError("LLM 调用失败")

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        """对 messages 中所有文本内容做 PII/敏感打码后再出域。"""
        keywords = self.settings.sensitive_keyword_list
        out = []
        for m in messages:
            c = dict(m)
            if isinstance(c.get("content"), str):
                c["content"] = sanitize(c["content"], keywords)
            out.append(c)
        return out

    def chat_text(self, messages: list[dict], **kwargs) -> str:
        resp = self.chat(messages, **kwargs)
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"LLM 响应格式异常: {json.dumps(resp)[:500]}") from e

    def chat_with_tools(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        """返回 message 对象（含 content 与 tool_calls）。"""
        resp = self.chat(messages, tools=tools, **kwargs)
        try:
            return resp["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"LLM 响应格式异常: {json.dumps(resp)[:500]}") from e


_adapter: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LLMAdapter()
    return _adapter

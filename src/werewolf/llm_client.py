"""统一的异步 LLM 调用客户端，支持多厂商模型切换、JSON 强制输出和重试机制"""

import json
import logging
import asyncio
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("werewolf.llm")

# OpenAI SDK 的兼容异常类型
_API_EXCEPTIONS = (
    Exception,  # 宽泛捕获，因为各厂商 SDK 异常类型不一致
)


class LLMClient:
    """异步 LLM 客户端，通过 OpenAI SDK 兼容接口调用不同厂商模型"""

    def __init__(self, base_url: str, api_key: str, model: str, max_retries: int = 3):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=120.0,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_API_EXCEPTIONS),
    )
    async def _call_raw(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        """底层 API 调用，带重试"""
        # Anthropic 的兼容接口不支持 response_format，所以用 prompt 约束
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError(f"Model {self.model} returned empty content")
        return content

    async def call_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_parse_retries: int = 2,
    ) -> dict[str, Any]:
        """
        调用 LLM 并强制解析为 JSON dict。
        先尝试 API 层面的 JSON mode（仅 OpenAI 兼容端点支持），
        不支持则通过 prompt 约束 + 多次解析重试兜底。
        """
        # 第一次尝试：用 response_format=json_object（部分 API 支持）
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content:
                return json.loads(content)
        except Exception:
            logger.info(f"response_format=json_object not supported for {self.model}, falling back to prompt constraint")

        # 降级：prompt 约束 + 解析重试
        for attempt in range(max_parse_retries + 1):
            raw = await self._call_raw(messages, temperature)
            try:
                result = json.loads(raw)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                # 尝试提取 JSON 片段（LLM 可能包裹在 markdown 中）
                extracted = _extract_json_from_text(raw)
                if extracted:
                    try:
                        result = json.loads(extracted)
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        pass

                if attempt < max_parse_retries:
                    logger.warning(f"JSON parse failed for {self.model}, retrying (attempt {attempt + 1})")
                else:
                    logger.error(f"JSON parse failed after {max_parse_retries} retries for {self.model}. Raw: {raw[:200]}")
                    raise ValueError(f"Cannot parse JSON from model {self.model}: {raw[:200]}")

        raise RuntimeError("Unreachable")

    async def call_text(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        """调用 LLM 返回纯文本"""
        return await self._call_raw(messages, temperature)

    async def close(self):
        await self._client.close()


def _extract_json_from_text(text: str) -> str | None:
    """从可能包含 markdown 代码块的文本中提取 JSON"""
    # 去除 ```json ... ``` 包裹
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            return text[start:end].strip()
    if "```" in text:
        start = text.find("```") + 3
        end = text.rfind("```")
        if end > start:
            candidate = text[start:end].strip()
            if candidate.startswith("{") or candidate.startswith("["):
                return candidate
    # 找到第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return None


async def call_concurrent(
    tasks: list[tuple[LLMClient, list[dict[str, str]], float]],
) -> list[dict[str, Any]]:
    """
    并发调用多个 LLM 客户端。
    tasks: [(client, messages, temperature), ...]
    返回与 tasks 顺序对应的 JSON 结果列表。
    """
    coros = [client.call_json(messages, temperature) for client, messages, temperature in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)
    output: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(f"Concurrent call {i} failed: {r}")
            output.append({"error": str(r)})
        else:
            output.append(r)
    return output
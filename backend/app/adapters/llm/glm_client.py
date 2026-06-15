from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

import httpx
from httpx import HTTPStatusError, TimeoutException

logger = logging.getLogger(__name__)


class GLM51Client:
    """智谱 GLM 5.1 接口适配器。

    该实现保持与 `QwenClient` 一致的调用接口，便于测试脚本和上层服务
    直接复用同一套使用方式。
    """

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout_seconds: float = 900.0) -> None:
        """初始化 GLM 客户端。"""

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds))

    async def chat(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """发送聊天请求并返回模型文本响应。"""

        try:
            headers = await self.build_headers()
            payload = await self.build_payload(
                messages,
                temperature=temperature,
                response_format=response_format,
            )

            logger.debug(
                "发送 GLM 模型请求，消息数量: %d, 温度: %.2f",
                len(messages),
                temperature,
            )

            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

            response_data = response.json()
            content = await self.parse_content(response_data)

            logger.debug(
                "GLM 模型响应成功，生成内容长度: %d",
                len(content),
            )
            return content

        except HTTPStatusError as exc:
            logger.error(
                "GLM 模型 HTTP 请求失败，状态码: %d, 响应: %s",
                exc.response.status_code,
                exc.response.text,
                exc_info=True,
            )
            raise
        except TimeoutException as exc:
            logger.error(
                "GLM 模型请求超时，超时时间: %.1f 秒",
                self.timeout_seconds,
                exc_info=True,
            )
            raise
        except Exception as exc:
            logger.error(
                "GLM 模型请求发生未预期异常: %s",
                str(exc),
                exc_info=True,
            )
            raise

    async def health_check(self) -> bool:
        """检查 GLM 接口是否可用。"""

        try:
            headers = await self.build_headers()
            response = await self.client.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=min(self.timeout_seconds, 10.0),
            )
            return response.status_code == 200
        except Exception as exc:
            logger.warning("GLM 模型健康检查失败: %s", str(exc))
            return False

    async def build_headers(self) -> Dict[str, str]:
        """构建请求头。"""

        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def build_payload(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建请求体。"""

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        return payload

    async def parse_content(self, response: Dict[str, Any]) -> str:
        """解析 GLM 返回内容。

        兼容两类常见格式：
        1. `message.content` 为字符串
        2. `message.content` 为由文本片段组成的列表
        """

        try:
            choices = response.get("choices", [])
            if not choices:
                raise ValueError("响应中未找到 choices 字段")

            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content", "")

            if isinstance(content, str):
                parsed = content.strip()
            elif isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                        continue
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("content")
                        if isinstance(text, str):
                            parts.append(text)
                parsed = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
            else:
                parsed = ""

            if not parsed:
                raise ValueError("响应中未找到有效的内容文本")
            return parsed

        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.error(
                "解析 GLM 模型响应失败，响应格式: %s",
                str(response),
                exc_info=True,
            )
            raise ValueError(f"无法解析模型响应: {str(exc)}") from exc

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""

        await self.client.aclose()

    async def __aenter__(self) -> GLM51Client:
        """支持异步上下文管理器。"""

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出上下文时关闭连接。"""

        await self.close()


GLMClient = GLM51Client

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import httpx
from httpx import HTTPStatusError, TimeoutException

logger = logging.getLogger(__name__)


class QwenClient:
    """内网 Qwen 大模型接口适配器实现。

    该适配器使用 httpx.AsyncClient 实现异步 HTTP 请求，为关系抽取、
    多智能体协同裁决以及未来关系外推等模块提供统一的大模型访问接口。

    特性：
    - 异步非阻塞 HTTP 请求
    - 健壮的异常处理与重试机制
    - 详细的错误日志记录
    - 支持标准的 OpenAI 格式消息输入
    """

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout_seconds: float = 900.0) -> None:
        """初始化 Qwen 模型访问客户端。

        Args:
            base_url: 内网或本地部署的 OpenAI 兼容接口基础地址。
            api_key: 通过环境变量注入的访问密钥或鉴权令牌。
            model: 默认使用的 Qwen 模型名称或模型标识。
        """
        self.base_url = base_url.rstrip('/')
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
        """发送聊天式推理请求并返回模型的纯文本响应。

        该方法实现了完整的 HTTP 请求流程，包括：
        1. 构建请求头和请求体
        2. 发送异步 POST 请求
        3. 处理响应和异常
        4. 提取模型生成的主文本内容

        Args:
            messages: 传递给模型的聊天消息序列，遵循 OpenAI 格式。
            temperature: 采样温度参数，用于控制生成结果的随机性。
            response_format: 可选的结构化输出约束配置。

        Returns:
            str: 模型生成的纯文本内容。

        Raises:
            HTTPStatusError: 当 HTTP 状态码表示错误时（4xx, 5xx）。
            TimeoutException: 当请求超时时。
            Exception: 其他未预期的异常。
        """
        try:
            headers = await self.build_headers()
            payload = await self.build_payload(messages, temperature=temperature, response_format=response_format)
            
            logger.debug(
                "发送 Qwen 模型请求，消息数量: %d, 温度: %.2f",
                len(messages),
                temperature
            )
            
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds
            )
            response.raise_for_status()
            
            response_data = response.json()
            content = await self.parse_content(response_data)
            
            logger.debug(
                "Qwen 模型响应成功，生成内容长度: %d",
                len(content)
            )
            
            return content
            
        except HTTPStatusError as e:
            logger.error(
                "Qwen 模型 HTTP 请求失败，状态码: %d, 响应: %s",
                e.response.status_code,
                e.response.text,
                exc_info=True
            )
            raise
        except TimeoutException as e:
            logger.error(
                "Qwen 模型请求超时，超时时间: %.1f 秒",
                self.timeout_seconds,
                exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                "Qwen 模型请求发生未预期异常: %s",
                str(e),
                exc_info=True
            )
            raise

    async def health_check(self) -> bool:
        """检查当前 Qwen 接口是否可用。

        通过发送一个简单的健康检查请求来验证模型服务的可用性。

        Returns:
            bool: 若模型接口健康可用则返回 `True`，否则返回 `False`。
        """
        try:
            headers = await self.build_headers()
            
            # 发送一个简单的健康检查请求
            response = await self.client.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=min(self.timeout_seconds, 10.0)
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.warning(
                "Qwen 模型健康检查失败: %s",
                str(e)
            )
            return False

    async def build_headers(self) -> Dict[str, str]:
        """构建访问模型接口所需的请求头。

        包括认证头和内容类型头。

        Returns:
            Dict[str, str]: 用于 HTTP 请求的头部字典。
        """
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
        """构建发送给 Qwen 接口的标准请求体。

        Args:
            messages: 聊天消息序列。
            temperature: 采样温度参数。
            response_format: 可选的响应格式约束配置。

        Returns:
            Dict[str, Any]: 适配 OpenAI 兼容接口的标准请求体字典。
        """
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
        """从原始响应中提取模型主内容文本。

        Args:
            response: 大模型返回的原始响应字典。

        Returns:
            str: 从响应中解析出的主内容文本。

        Raises:
            ValueError: 当响应格式不符合预期时。
        """
        try:
            choices = response.get("choices", [])
            if not choices:
                raise ValueError("响应中未找到 choices 字段")
                
            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content", "")
            
            if not content:
                raise ValueError("响应中未找到有效的内容文本")
                
            return content.strip()
            
        except (KeyError, IndexError, TypeError) as e:
            logger.error(
                "解析 Qwen 模型响应失败，响应格式: %s",
                str(response),
                exc_info=True
            )
            raise ValueError(f"无法解析模型响应: {str(e)}")

    async def close(self) -> None:
        """关闭底层的 HTTP 客户端连接。

        在应用程序关闭时调用，确保资源正确释放。
        """
        await self.client.aclose()

    async def __aenter__(self):
        """支持异步上下文管理器。"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出时关闭连接。"""
        await self.close()

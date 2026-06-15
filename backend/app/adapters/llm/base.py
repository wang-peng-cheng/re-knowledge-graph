from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Sequence, runtime_checkable


@runtime_checkable
class LLMClientProtocol(Protocol):
    """统一的大模型客户端协议。"""

    model: str
    timeout_seconds: float

    async def chat(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """发送聊天请求并返回文本响应。"""

    async def health_check(self) -> bool:
        """执行连通性或模型可用性检查。"""

    async def close(self) -> None:
        """关闭底层连接资源。"""

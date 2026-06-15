from __future__ import annotations

import os
from typing import Callable, Mapping

from app.adapters.llm.base import LLMClientProtocol
from app.adapters.llm.glm_client import GLM51Client
from app.adapters.llm.qwen_client import QwenClient
from app.core.config import AppSettings, get_settings

ClientBuilder = Callable[[str, str, str, float], LLMClientProtocol]


def _build_qwen_client(base_url: str, api_key: str, model: str, timeout_seconds: float) -> LLMClientProtocol:
    return QwenClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def _build_glm_client(base_url: str, api_key: str, model: str, timeout_seconds: float) -> LLMClientProtocol:
    return GLM51Client(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def _build_deepseek_client(base_url: str, api_key: str, model: str, timeout_seconds: float) -> LLMClientProtocol:
    # DeepSeek 当前同样走 OpenAI 兼容接口，因此复用通用实现。
    return QwenClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )


CLIENT_BUILDERS: dict[str, ClientBuilder] = {
    "qwen": _build_qwen_client,
    "glm": _build_glm_client,
    "deepseek": _build_deepseek_client,
}

PROVIDER_ENV_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "qwen": {
        "base_url": ("QWEN_BASE_URL",),
        "api_key": ("QWEN_API_KEY",),
        "model": ("QWEN_MODEL",),
    },
    "glm": {
        "base_url": ("GLM_BASE_URL", "GLM51_BASE_URL"),
        "api_key": ("GLM_API_KEY", "GLM51_API_KEY"),
        "model": ("GLM_MODEL", "GLM51_MODEL"),
    },
    "deepseek": {
        "base_url": ("DEEPSEEK_BASE_URL",),
        "api_key": ("DEEPSEEK_API_KEY",),
        "model": ("DEEPSEEK_MODEL",),
    },
}


def build_llm_client(
    provider: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 900.0,
) -> LLMClientProtocol:
    """按提供商构建统一的大模型客户端实例。"""

    normalized_provider = provider.strip().lower()
    if normalized_provider not in CLIENT_BUILDERS:
        raise ValueError(f"未注册的 LLM 提供商: {normalized_provider}")
    if not base_url.strip():
        raise ValueError(f"{normalized_provider} 的 base_url 不能为空。")
    if not api_key.strip():
        raise ValueError(f"{normalized_provider} 的 api_key 不能为空。")
    if not model.strip():
        raise ValueError(f"{normalized_provider} 的 model 不能为空。")

    builder = CLIENT_BUILDERS[normalized_provider]
    return builder(base_url.strip(), api_key.strip(), model.strip(), timeout_seconds)


def build_llm_client_from_settings(
    *,
    settings: AppSettings | None = None,
    provider: str | None = None,
    timeout_seconds: float = 900.0,
    overrides: Mapping[str, str | None] | None = None,
) -> LLMClientProtocol:
    """根据全局配置与运行时覆盖项构建客户端。"""

    current_settings = settings or get_settings()
    resolved_config = current_settings.resolve_llm_config(provider)

    merged_config: dict[str, str | None] = dict(resolved_config)
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                merged_config[key] = value

    resolved_provider = str(merged_config["provider"])
    base_url = str(merged_config.get("base_url") or "")
    api_key = str(merged_config.get("api_key") or "")
    model = str(merged_config.get("model") or "")
    return build_llm_client(
        resolved_provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def build_llm_client_from_environment(
    provider: str,
    *,
    timeout_seconds: float = 900.0,
    overrides: Mapping[str, str | None] | None = None,
) -> LLMClientProtocol:
    """在配置中心不可用时，直接从环境变量构建客户端。"""

    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDER_ENV_KEYS:
        raise ValueError(f"未注册的 LLM 提供商: {normalized_provider}")

    provider_env_keys = PROVIDER_ENV_KEYS[normalized_provider]
    resolved_values: dict[str, str] = {}
    for field_name, env_keys in provider_env_keys.items():
        resolved_value = ""
        for env_key in env_keys:
            candidate = os.getenv(env_key)
            if candidate:
                resolved_value = candidate
                break
        resolved_values[field_name] = resolved_value

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                resolved_values[key] = value

    return build_llm_client(
        normalized_provider,
        base_url=resolved_values.get("base_url", ""),
        api_key=resolved_values.get("api_key", ""),
        model=resolved_values.get("model", ""),
        timeout_seconds=timeout_seconds,
    )

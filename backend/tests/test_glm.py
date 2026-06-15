from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

from dotenv import load_dotenv

from app.adapters.llm.glm_client import GLM51Client
from backend.tests.test_support import assert_non_empty_text, run_with_timeout

load_dotenv(BACKEND_DIR / ".env")


def parse_args() -> argparse.Namespace:
    """解析 GLM 连通性测试参数。"""

    parser = argparse.ArgumentParser(description="GLM 连通性测试")
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0, help="请求超时秒数")
    parser.add_argument("--min-response-length", type=int, default=10, help="最小响应字符数")
    return parser.parse_args()


async def main() -> None:
    """执行 GLM 连通性测试。"""

    args = parse_args()
    print("正在初始化 GLM 客户端...")

    base_url = os.getenv("GLM_BASE_URL") or os.getenv("GLM51_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    api_key = os.getenv("GLM_API_KEY") or os.getenv("GLM51_API_KEY", "")
    model_name = os.getenv("GLM_MODEL") or os.getenv("GLM51_MODEL", "glm-5.1")

    if not api_key:
        raise ValueError("找不到 API Key，请检查 .env 文件中是否配置了 GLM_API_KEY 或 GLM51_API_KEY。")

    client = GLM51Client(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        timeout_seconds=args.request_timeout_seconds,
    )
    test_messages = [
        {"role": "system", "content": "你是一个严谨的 AI 助手。"},
        {"role": "user", "content": "请用一句话证明你已经连线成功，并报出你的模型名字。"},
    ]

    print(f"正在向 {base_url} 发送请求...")
    try:
        response = await run_with_timeout(
            "GLM 连通性测试",
            client.chat(test_messages),
            args.request_timeout_seconds,
        )
        assert_non_empty_text(
            response,
            label="GLM 连通性响应",
            min_length=args.min_response_length,
        )
        print("\n连接成功，GLM 响应如下：")
        print("-" * 40)
        print(response)
        print("-" * 40)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

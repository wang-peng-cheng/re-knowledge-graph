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

from app.adapters.llm.qwen_client import QwenClient
from backend.tests.test_support import assert_non_empty_text, run_with_timeout

load_dotenv(BACKEND_DIR / ".env")


def parse_args() -> argparse.Namespace:
    """解析 Qwen 连通性测试参数。"""

    parser = argparse.ArgumentParser(description="Qwen 连通性测试")
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0, help="请求超时秒数")
    parser.add_argument("--min-response-length", type=int, default=10, help="最小响应字符数")
    return parser.parse_args()


async def main() -> None:
    """执行 Qwen 连通性测试。"""

    args = parse_args()
    print("正在初始化 Qwen 客户端...")

    base_url = os.getenv("QWEN_BASE_URL", "http://10.109.118.166:11434/v1")
    api_key = os.getenv("QWEN_API_KEY", "sk-123456")
    model_name = os.getenv("QWEN_MODEL", "qwen3:8b")

    client = QwenClient(
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
            "Qwen 连通性测试",
            client.chat(test_messages),
            args.request_timeout_seconds,
        )
        assert_non_empty_text(
            response,
            label="Qwen 连通性响应",
            min_length=args.min_response_length,
        )
        print("\n连接成功，Qwen 响应如下：")
        print("-" * 40)
        print(response)
        print("-" * 40)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

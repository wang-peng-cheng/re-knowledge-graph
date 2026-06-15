from __future__ import annotations

"""Smoke runner for the ablation suite matrix."""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from backend.tests.run_ablation_suite import AVAILABLE_LLM_PROVIDERS, AVAILABLE_MODES, SuiteConfig, run_suite_from_config
from backend.tests.test_support import DEFAULT_DATASET, DEFAULT_REL_INFO, ensure_default_raw_assets


def parse_args() -> argparse.Namespace:
    """Parse smoke-batch arguments."""

    parser = argparse.ArgumentParser(description="小批次消融实验矩阵冒烟测试")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=AVAILABLE_MODES,
        default=list(AVAILABLE_MODES),
        help="需要执行的实验模式列表",
    )
    parser.add_argument("--docs", type=int, default=2, help="每个模式测试文档数量")
    parser.add_argument("--dataset", type=str, default=DEFAULT_DATASET, help="数据集路径")
    parser.add_argument(
        "--relation-mapping-path",
        type=str,
        default=DEFAULT_REL_INFO,
        help="关系映射文件路径",
    )
    parser.add_argument("--batch-size", type=int, default=1, help="每批处理文档数")
    parser.add_argument("--max-processes", type=int, default=1, help="文档级并发槽位")
    parser.add_argument("--max-concurrency", type=int, default=2, help="单文档 chunk 并发上限")
    parser.add_argument("--document-timeout-seconds", type=float, default=900.0, help="单文档超时秒数")
    parser.add_argument("--suite-timeout-seconds", type=float, default=7200.0, help="整套实验超时秒数")
    parser.add_argument("--request-timeout-seconds", type=float, default=600.0, help="Qwen 请求超时秒数")
    parser.add_argument("--gpu-memory-threshold", type=float, default=1.0, help="GPU 显存占比阈值")
    parser.add_argument("--llm-provider", choices=AVAILABLE_LLM_PROVIDERS, default="qwen", help="底层大模型提供商")
    parser.add_argument("--qwen-base-url", type=str, default=None, help="覆盖 QWEN_BASE_URL")
    parser.add_argument("--qwen-api-key", type=str, default=None, help="覆盖 QWEN_API_KEY")
    parser.add_argument("--qwen-model", type=str, default=None, help="覆盖 QWEN_MODEL")
    parser.add_argument("--glm-base-url", type=str, default=None, help="覆盖 GLM_BASE_URL / GLM51_BASE_URL")
    parser.add_argument("--glm-api-key", type=str, default=None, help="覆盖 GLM_API_KEY / GLM51_API_KEY")
    parser.add_argument("--glm-model", type=str, default=None, help="覆盖 GLM_MODEL / GLM51_MODEL")
    parser.add_argument("--deepseek-base-url", type=str, default=None, help="覆盖 DEEPSEEK_BASE_URL")
    parser.add_argument("--deepseek-api-key", type=str, default=None, help="覆盖 DEEPSEEK_API_KEY")
    parser.add_argument("--deepseek-model", type=str, default=None, help="覆盖 DEEPSEEK_MODEL")
    return parser.parse_args()


async def run_batch(args: argparse.Namespace) -> None:
    """Run all selected modes sequentially with bounded smoke settings."""

    archives: list[dict[str, str]] = []
    for mode in args.modes:
        config = SuiteConfig(
            mode=mode,
            dataset=args.dataset,
            relation_mapping_path=args.relation_mapping_path,
            docs=args.docs,
            batch_size=args.batch_size,
            max_processes=args.max_processes,
            max_concurrency=args.max_concurrency,
            document_timeout_seconds=args.document_timeout_seconds,
            suite_timeout_seconds=args.suite_timeout_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            gpu_memory_threshold=args.gpu_memory_threshold,
            experiment_group_id=f"smoke-{mode}",
            llm_provider=args.llm_provider,
            qwen_base_url=args.qwen_base_url,
            qwen_api_key=args.qwen_api_key,
            qwen_model=args.qwen_model,
            glm_base_url=args.glm_base_url,
            glm_api_key=args.glm_api_key,
            glm_model=args.glm_model,
            deepseek_base_url=args.deepseek_base_url,
            deepseek_api_key=args.deepseek_api_key,
            deepseek_model=args.deepseek_model,
        )
        config.validate()
        paths = await run_suite_from_config(config)
        archives.append({"mode": mode, "archive_dir": str(paths.archive_dir)})

    for item in archives:
        print(f"Mode={item['mode']} Archive={item['archive_dir']}")


def main() -> None:
    """CLI entrypoint."""

    args = parse_args()
    ensure_default_raw_assets()
    asyncio.run(run_batch(args))


if __name__ == "__main__":
    main()

from __future__ import annotations

"""Legacy compatibility wrapper for the new ablation suite."""

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

from backend.tests.run_ablation_suite import AVAILABLE_MODES, SuiteConfig, run_suite_from_config
from backend.tests.test_support import DEFAULT_DATASET, DEFAULT_REL_INFO, ensure_default_raw_assets


def parse_args() -> argparse.Namespace:
    """Parse the legacy ablation CLI surface."""

    parser = argparse.ArgumentParser(description="兼容入口：消融实验命令行封装")
    parser.add_argument("--mode", choices=AVAILABLE_MODES, required=True, help="实验模式")
    parser.add_argument("--docs", type=int, default=10, help="测试文档数量")
    parser.add_argument("--dataset", type=str, default=DEFAULT_DATASET, help="数据集路径")
    parser.add_argument(
        "--relation-mapping-path",
        type=str,
        default=DEFAULT_REL_INFO,
        help="关系映射文件路径",
    )
    parser.add_argument("--batch-size", type=int, default=1, help="每批处理文档数")
    parser.add_argument("--max-processes", type=int, default=1, help="文档级并发槽位")
    parser.add_argument("--max-concurrency", type=int, default=4, help="单文档 chunk 并发上限")
    parser.add_argument("--gpu-memory-threshold", type=float, default=1.0, help="GPU 显存占比阈值")
    parser.add_argument("--document-timeout-seconds", type=float, default=1800.0, help="单文档超时秒数")
    parser.add_argument("--suite-timeout-seconds", type=float, default=21600.0, help="整套实验超时秒数")
    parser.add_argument("--request-timeout-seconds", type=float, default=900.0, help="Qwen 请求超时秒数")
    parser.add_argument("--experiment-group-id", type=str, default=None, help="显式实验分组标识")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> Path:
    """Run the ablation suite through the compatibility facade."""

    config = SuiteConfig(
        mode=args.mode,
        dataset=args.dataset,
        relation_mapping_path=args.relation_mapping_path,
        docs=args.docs,
        batch_size=args.batch_size,
        max_processes=args.max_processes,
        max_concurrency=args.max_concurrency,
        gpu_memory_threshold=args.gpu_memory_threshold,
        document_timeout_seconds=args.document_timeout_seconds,
        suite_timeout_seconds=args.suite_timeout_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        experiment_group_id=args.experiment_group_id,
    )
    config.validate()
    paths = await run_suite_from_config(config)
    return paths.archive_dir


def main() -> None:
    """CLI entrypoint."""

    args = parse_args()
    ensure_default_raw_assets()
    archive_dir = asyncio.run(async_main(args))
    print(f"Ablation experiment archive: {archive_dir}")


if __name__ == "__main__":
    main()

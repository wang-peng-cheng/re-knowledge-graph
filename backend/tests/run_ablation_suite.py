from __future__ import annotations

"""Unified ablation experiment entrypoint with archival and traceability."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from dotenv import load_dotenv

from app.adapters.llm.qwen_client import QwenClient
from app.core.config import get_settings
from app.domain.models import CleanedTextChunk, ExtractionResult
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.services.cleaning_service import TextCleaningService
from app.v2_pipeline.filters import CascadeFilterPipeline, FilterDecision, HeuristicFilter
from app.v2_pipeline.injectors import SyntaxInjector
from app.v2_pipeline.parallel_engine import MapReduceExtractionEngine, PartialGraphResult
from backend.tests.run_docred_evaluation import (
    build_document_record,
    build_gold_entities,
    build_gold_relations,
    build_pred_relations,
    compute_relation_metrics,
    load_json_file,
    summarize_overall_metrics,
)
from backend.tests.test_support import (
    AVAILABLE_MODES,
    MODE_LABELS,
    ExperimentPaths,
    SuiteConfig,
    assert_metric_payload,
    build_experiment_group_id,
    build_manifest_payload,
    build_suite_config,
    chunked,
    create_experiment_paths,
    ensure_default_raw_assets,
    ensure_qwen_env_defaults,
    load_yaml_config,
    run_with_timeout,
    setup_run_logger,
    summarize_failure_counts,
    validate_suite_environment,
    write_json_file,
    write_yaml_file,
)

logger = logging.getLogger("backend.tests.ablation_suite")


class KeepAllFilter(HeuristicFilter):
    """Filter implementation used by the no-filter ablation mode."""

    def filter_chunks(self, chunks: Sequence[CleanedTextChunk]) -> list[FilterDecision]:
        return [self.evaluate_chunk(chunk) for chunk in chunks]

    def evaluate_chunk(self, chunk: CleanedTextChunk) -> FilterDecision:
        return FilterDecision(
            chunk=chunk,
            keep=True,
            score=1.0,
            reason="消融模式关闭 Filter 阶段，默认保留全部文本块",
            metadata={"filter_mode": "disabled"},
        )


class NoReduceMapReduceEngine(MapReduceExtractionEngine):
    """MapReduce engine variant that disables relation fusion."""

    async def reduce_aggregate(
        self,
        document_id: str,
        partial_graphs: Sequence[PartialGraphResult],
    ) -> ExtractionResult:
        entities = [entity for partial in partial_graphs for entity in partial.entities]
        relations = [relation for partial in partial_graphs for relation in partial.relations]
        return ExtractionResult(
            document_id=document_id,
            entities=entities,
            relations=relations,
            agent_trace=[],
            metadata={
                "reduce_mode": "disabled",
                "partial_graph_count": len(partial_graphs),
            },
        )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the ablation suite."""

    parser = argparse.ArgumentParser(description="Paper1 消融实验统一总控台")
    parser.add_argument("--config", type=str, default=None, help="YAML 配置文件路径")
    parser.add_argument("--mode", choices=AVAILABLE_MODES, default=None, help="实验模式")
    parser.add_argument("--dataset", type=str, default=None, help="数据集路径")
    parser.add_argument("--relation-mapping-path", type=str, default=None, help="关系映射文件路径")
    parser.add_argument("--docs", type=int, default=None, help="参与实验的文档数量")
    parser.add_argument("--batch-size", type=int, default=None, help="每批次处理的文档数")
    parser.add_argument("--max-processes", type=int, default=None, help="文档级并发槽位上限")
    parser.add_argument("--max-concurrency", type=int, default=None, help="单文档 chunk 并发上限")
    parser.add_argument("--gpu-memory-threshold", type=float, default=None, help="GPU 显存占用阈值，范围 (0,1]")
    parser.add_argument("--document-timeout-seconds", type=float, default=None, help="单文档超时秒数")
    parser.add_argument("--suite-timeout-seconds", type=float, default=None, help="整套实验超时秒数")
    parser.add_argument("--request-timeout-seconds", type=float, default=None, help="Qwen HTTP 请求超时秒数")
    parser.add_argument("--experiment-group-id", type=str, default=None, help="显式指定实验分组标识")
    parser.add_argument("--qwen-base-url", type=str, default=None, help="覆盖 QWEN_BASE_URL")
    parser.add_argument("--qwen-api-key", type=str, default=None, help="覆盖 QWEN_API_KEY")
    parser.add_argument("--qwen-model", type=str, default=None, help="覆盖 QWEN_MODEL")
    return parser.parse_args()


def namespace_to_cli_values(args: argparse.Namespace) -> dict[str, Any]:
    """Convert argparse namespace to a config merge payload."""

    return {
        "mode": args.mode,
        "dataset": args.dataset,
        "relation_mapping_path": args.relation_mapping_path,
        "docs": args.docs,
        "batch_size": args.batch_size,
        "max_processes": args.max_processes,
        "max_concurrency": args.max_concurrency,
        "gpu_memory_threshold": args.gpu_memory_threshold,
        "document_timeout_seconds": args.document_timeout_seconds,
        "suite_timeout_seconds": args.suite_timeout_seconds,
        "request_timeout_seconds": args.request_timeout_seconds,
        "experiment_group_id": args.experiment_group_id,
        "qwen_base_url": args.qwen_base_url,
        "qwen_api_key": args.qwen_api_key,
        "qwen_model": args.qwen_model,
    }


def build_engine_for_mode(
    *,
    config: SuiteConfig,
    extraction_service: MultiAgentRelationExtractionService,
    target_schemas: Sequence[str],
) -> MapReduceExtractionEngine:
    """Build a V2 engine variant for the requested ablation mode."""

    syntax_injector = SyntaxInjector()
    cascade_filter = cast(HeuristicFilter, CascadeFilterPipeline(target_schemas=list(target_schemas)))

    if config.mode == "v2_no_filter":
        return MapReduceExtractionEngine(
            extraction_service=extraction_service,
            chunk_filter=KeepAllFilter(),
            syntax_injector=syntax_injector,
            max_concurrency=config.max_concurrency,
            target_schemas=target_schemas,
            worker_timeout_seconds=config.document_timeout_seconds,
        )
    if config.mode == "v2_no_reduce":
        return NoReduceMapReduceEngine(
            extraction_service=extraction_service,
            chunk_filter=cascade_filter,
            syntax_injector=syntax_injector,
            max_concurrency=config.max_concurrency,
            target_schemas=target_schemas,
            worker_timeout_seconds=config.document_timeout_seconds,
        )
    if config.mode == "v2_full":
        return MapReduceExtractionEngine(
            extraction_service=extraction_service,
            chunk_filter=cascade_filter,
            syntax_injector=syntax_injector,
            max_concurrency=config.max_concurrency,
            target_schemas=target_schemas,
            worker_timeout_seconds=config.document_timeout_seconds,
        )
    raise ValueError(f"不支持的 V2 模式: {config.mode}")


def build_target_schemas(relation_mapping: dict[str, str]) -> list[str]:
    """Build target schemas from relation mapping values."""

    return sorted({str(value).strip() for value in relation_mapping.values() if str(value).strip()})


def build_qwen_client(config: SuiteConfig) -> QwenClient:
    """Build the Qwen client with suite-level timeout overrides."""

    load_dotenv(BACKEND_DIR / ".env")
    ensure_qwen_env_defaults(config)

    try:
        settings = get_settings()
        return QwenClient(
            base_url=os.getenv("QWEN_BASE_URL", settings.qwen_base_url),
            api_key=os.getenv("QWEN_API_KEY", settings.qwen_api_key),
            model=os.getenv("QWEN_MODEL", settings.qwen_model),
            timeout_seconds=config.request_timeout_seconds,
        )
    except Exception:
        base_url = os.getenv("QWEN_BASE_URL", config.qwen_base_url or "http://10.109.118.166:11434/v1")
        api_key = os.getenv("QWEN_API_KEY", config.qwen_api_key or "EMPTY")
        model = os.getenv("QWEN_MODEL", config.qwen_model or "qwen3:8b")
        return QwenClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=config.request_timeout_seconds,
        )


async def extract_document_by_mode(
    *,
    index: int,
    doc: dict[str, Any],
    config: SuiteConfig,
    relation_mapping: dict[str, str],
    cleaning_service: TextCleaningService,
    extraction_service: MultiAgentRelationExtractionService,
) -> dict[str, Any]:
    """Run one document through the configured ablation mode."""

    record = build_document_record(doc, index)
    chunks = await run_with_timeout(
        f"文档清洗[{record.document_id}]",
        cleaning_service.clean_document(record),
        config.document_timeout_seconds,
    )
    if len(chunks) <= 0:
        raise AssertionError(f"文档 {record.document_id} 清洗后 chunk 数必须大于 0。")

    target_schemas = build_target_schemas(relation_mapping)
    if config.mode == "baseline_v1":
        result = await run_with_timeout(
            f"文档抽取[{record.document_id}]",
            extraction_service.extract(record.document_id, chunks, target_schemas=target_schemas),
            config.document_timeout_seconds,
        )
        filter_decisions = [
            FilterDecision(
                chunk=chunk,
                keep=True,
                score=1.0,
                reason="baseline_v1 直通模式，不执行 V2 Filter",
                metadata={"mode": config.mode},
            )
            for chunk in chunks
        ]
        injected_chunk_count = 0
        partial_graph_count = 0
    else:
        engine = build_engine_for_mode(
            config=config,
            extraction_service=extraction_service,
            target_schemas=target_schemas,
        )
        filter_decisions = engine.chunk_filter.filter_chunks(chunks)
        retained_chunks = [decision.chunk for decision in filter_decisions if decision.keep]
        injected_chunks = engine.syntax_injector.batch_inject(retained_chunks)
        partial_graphs = await run_with_timeout(
            f"文档 Map 阶段[{record.document_id}]",
            engine.map_extract(document_id=record.document_id, chunks=injected_chunks),
            config.document_timeout_seconds,
        )
        result = await run_with_timeout(
            f"文档 Reduce 阶段[{record.document_id}]",
            engine.reduce_aggregate(document_id=record.document_id, partial_graphs=partial_graphs),
            config.document_timeout_seconds,
        )
        injected_chunk_count = len(injected_chunks)
        partial_graph_count = len(partial_graphs)

    gold_entities = build_gold_entities(doc.get("vertexSet", []))
    gold_relations = build_gold_relations(doc.get("labels", []), gold_entities, relation_mapping)
    pred_relations = build_pred_relations(result)
    metrics = compute_relation_metrics(pred_relations, gold_relations)
    assert_metric_payload(metrics, label=f"文档指标[{record.document_id}]")

    kept_count = sum(1 for decision in filter_decisions if decision.keep)
    dropped_count = len(filter_decisions) - kept_count
    return {
        "status": "success",
        "mode": config.mode,
        "mode_label": MODE_LABELS[config.mode],
        "document_id": record.document_id,
        "title": doc.get("title", f"docred_doc_{index}"),
        "chunk_count": len(chunks),
        "retained_chunk_count": kept_count,
        "dropped_chunk_count": dropped_count,
        "injected_chunk_count": injected_chunk_count,
        "partial_graph_count": partial_graph_count,
        "pred_entity_count": len(result.entities),
        "pred_relation_count": len(pred_relations),
        "gold_relation_count": len(gold_relations),
        "metrics": metrics,
    }


async def execute_suite_run(
    *,
    config: SuiteConfig,
    dataset_path: Path,
    relation_mapping_path: Path,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Execute the ablation suite for one configured mode."""

    relation_mapping = load_json_file(relation_mapping_path)
    dataset_payload = load_json_file(dataset_path)
    if not isinstance(relation_mapping, dict):
        raise ValueError("关系映射 JSON 顶层必须为字典。")
    if not isinstance(dataset_payload, list):
        raise ValueError("数据集 JSON 顶层必须为列表。")

    target_docs = dataset_payload[:config.docs]
    if len(target_docs) <= 0:
        raise AssertionError("实验数据集为空，至少需要 1 篇文档。")

    logger.info(
        "启动消融实验 mode=%s(%s) docs=%d batch_size=%d max_processes=%d max_concurrency=%d dataset=%s",
        config.mode,
        MODE_LABELS[config.mode],
        len(target_docs),
        config.batch_size,
        config.max_processes,
        config.max_concurrency,
        dataset_path,
    )

    cleaning_service = TextCleaningService()
    qwen_client = build_qwen_client(config)
    extraction_service = MultiAgentRelationExtractionService(qwen_client=qwen_client)
    per_doc_results: list[dict[str, Any]] = []

    try:
        batches = chunked(target_docs, config.batch_size)
        for batch_index, batch_docs in enumerate(batches, start=1):
            logger.info("开始处理批次 %d/%d，文档数=%d", batch_index, len(batches), len(batch_docs))
            semaphore = asyncio.Semaphore(config.max_processes)

            async def process_one(global_index: int, doc: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    title = doc.get("title", f"docred_doc_{global_index}")
                    try:
                        result = await extract_document_by_mode(
                            index=global_index,
                            doc=doc,
                            config=config,
                            relation_mapping=relation_mapping,
                            cleaning_service=cleaning_service,
                            extraction_service=extraction_service,
                        )
                        logger.info(
                            "文档实验完成 title=%s | gold=%d | pred=%d | P=%.4f | R=%.4f | F1=%.4f",
                            result["title"],
                            result["gold_relation_count"],
                            result["pred_relation_count"],
                            result["metrics"]["precision"],
                            result["metrics"]["recall"],
                            result["metrics"]["f1"],
                        )
                        return result
                    except Exception as exc:
                        logger.exception("文档处理失败 title=%s | 错误=%s", title, exc)
                        return {
                            "status": "failed",
                            "mode": config.mode,
                            "mode_label": MODE_LABELS[config.mode],
                            "document_id": f"docred_eval_{global_index:03d}",
                            "title": title,
                            "chunk_count": 0,
                            "retained_chunk_count": 0,
                            "dropped_chunk_count": 0,
                            "injected_chunk_count": 0,
                            "partial_graph_count": 0,
                            "pred_entity_count": 0,
                            "pred_relation_count": 0,
                            "gold_relation_count": 0,
                            "metrics": {
                                "true_positive": 0.0,
                                "false_positive": 0.0,
                                "false_negative": 0.0,
                                "predicted_count": 0.0,
                                "gold_count": 0.0,
                                "precision": 0.0,
                                "recall": 0.0,
                                "f1": 0.0,
                            },
                            "error": str(exc),
                        }

            tasks = [
                process_one(global_index=batch_offset + item_index, doc=doc)
                for item_index, doc in enumerate(batch_docs)
                for batch_offset in [((batch_index - 1) * config.batch_size)]
            ]
            per_doc_results.extend(await asyncio.gather(*tasks))
    finally:
        await qwen_client.close()

    success_results = [item for item in per_doc_results if item.get("status") == "success"]
    if not success_results:
        raise RuntimeError("没有任何文档成功完成消融实验，无法生成有效评测结果。")

    overall_metrics = summarize_overall_metrics(success_results)
    assert_metric_payload(overall_metrics, label=f"总体指标[{config.mode}]")

    summary = {
        "mode": config.mode,
        "mode_label": MODE_LABELS[config.mode],
        "document_count": len(target_docs),
        "success_count": len(success_results),
        "failure_count": summarize_failure_counts(per_doc_results),
        "batch_count": len(chunked(target_docs, config.batch_size)),
        "dataset": str(dataset_path),
        "relation_mapping_path": str(relation_mapping_path),
        "overall_metrics": overall_metrics,
        "per_doc_details": per_doc_results,
    }
    logger.info(
        "消融实验完成 mode=%s | success=%d | failure=%d | P=%.4f | R=%.4f | F1=%.4f",
        config.mode,
        summary["success_count"],
        summary["failure_count"],
        overall_metrics["precision"],
        overall_metrics["recall"],
        overall_metrics["f1"],
    )
    return summary


async def run_suite_from_config(config: SuiteConfig) -> ExperimentPaths:
    """Run the full experiment pipeline and persist all archive artifacts."""

    dataset_path, relation_mapping_path = validate_suite_environment(config)
    group_id = build_experiment_group_id(config.mode, config.experiment_group_id)
    paths = create_experiment_paths(group_id)
    run_logger = setup_run_logger(paths, group_id, config)
    manifest_payload = build_manifest_payload(
        group_id=group_id,
        config=config,
        dataset_path=dataset_path,
        relation_mapping_path=relation_mapping_path,
    )
    write_yaml_file(paths.config_path, manifest_payload)

    summary = await run_with_timeout(
        f"消融实验套件[{group_id}]",
        execute_suite_run(
            config=config,
            dataset_path=dataset_path,
            relation_mapping_path=relation_mapping_path,
            logger=run_logger,
        ),
        config.suite_timeout_seconds,
    )
    write_json_file(paths.metrics_path, summary)
    return paths


def build_config_from_args(args: argparse.Namespace) -> SuiteConfig:
    """Build validated suite config from CLI and optional YAML."""

    yaml_values: dict[str, Any] | None = None
    if args.config:
        yaml_values = load_yaml_config(Path(args.config))

    if not args.mode and not (yaml_values and yaml_values.get("mode")):
        raise ValueError("必须通过 CLI 或 YAML 指定实验模式 mode。")

    return build_suite_config(cli_values=namespace_to_cli_values(args), yaml_values=yaml_values)


def main() -> None:
    """CLI entrypoint for the ablation suite."""

    args = parse_args()
    ensure_default_raw_assets()
    config = build_config_from_args(args)
    paths = asyncio.run(run_suite_from_config(config))
    print(f"Ablation suite finished. Archive: {paths.archive_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.models import CleanedTextChunk, EntityMention, ExtractionResult, ProcessingStatus, TemporalRelation
from app.services.agentic_re_service import MultiAgentRelationExtractionService

from .filters import FilterDecision, HeuristicFilter
from .injectors import InjectedChunk, SyntaxInjector

logger = logging.getLogger(__name__)


def normalize_name(value: Any) -> str:
    """对实体名或关系键做轻量归一化，便于哈希聚合。"""

    if value is None:
        return ""
    return str(value).strip().lower()


def clamp_confidence(value: Any) -> float:
    """将置信度裁剪到 [0.0, 1.0] 区间，避免脏值污染聚合结果。"""

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric_value))


def fuse_independent_confidence(current_confidence: Any, new_confidence: Any) -> float:
    """使用独立证据联合概率公式融合两路关系置信度。"""

    c1 = clamp_confidence(current_confidence)
    c2 = clamp_confidence(new_confidence)
    return c1 + c2 - (c1 * c2)


def _ensure_entity_runtime_metadata(entity: EntityMention) -> dict[str, Any]:
    """在不修改 Pydantic 模型定义的前提下，为实体实例挂载运行时元数据。"""

    metadata = getattr(entity, "metadata", None)
    if isinstance(metadata, dict):
        return metadata

    runtime_metadata: dict[str, Any] = {}
    object.__setattr__(entity, "metadata", runtime_metadata)
    return runtime_metadata


def _merge_entity_aliases(retained: EntityMention, discarded: EntityMention) -> None:
    """将被淘汰实体的表层名合并到保留实体的别名列表中。"""

    discarded_aliases: list[str] = []
    if discarded.surface_form.strip():
        discarded_aliases.append(discarded.surface_form.strip())

    discarded_metadata = getattr(discarded, "metadata", None)
    if isinstance(discarded_metadata, dict):
        aliases = discarded_metadata.get("aliases", [])
        if isinstance(aliases, list):
            discarded_aliases.extend(str(alias).strip() for alias in aliases if str(alias).strip())

    if not discarded_aliases:
        return

    retained_metadata = _ensure_entity_runtime_metadata(retained)
    existing_aliases = retained_metadata.get("aliases", [])
    alias_list = list(existing_aliases) if isinstance(existing_aliases, list) else []

    for alias in discarded_aliases:
        if alias and alias != retained.surface_form and alias not in alias_list:
            alias_list.append(alias)

    retained_metadata["aliases"] = alias_list


@dataclass(slots=True)
class PartialGraphResult:
    """表示 Map 阶段单个 Worker 返回的局部图谱结果。

    在正式版中，每个 Worker 将针对单个 Chunk 产出局部实体集合、局部关
    系集合以及与抽取过程相关的元数据。为了保持当前骨架代码安全，本结
    构先只承载稳定字段，不绑定任何具体 LLM Provider。
    """

    document_id: str
    source_chunk_id: str
    entities: list[Any] = field(default_factory=list)
    relations: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MapReduceExtractionEngine:
    """v2.0 长文本跨文档知识图谱抽取的 Map-Reduce 编排骨架。

    架构定位：

    - `HeuristicFilter` 负责前置裁剪低价值 Chunk。
    - `SyntaxInjector` 负责为每个 Chunk 注入可扩展的结构化先验。
    - `map_extract()` 负责对单个 Chunk 执行并发抽取。
    - `reduce_aggregate()` 负责把所有局部图谱上收为文档级统一结果。

    设计原则：

    - 与 v1.0 `MultiAgentRelationExtractionService` 解耦，不在构造阶段强制
      绑定具体 LLM 客户端。
    - 保留稳定的领域接口，让未来真实实现能渐进式替换当前占位逻辑。
    - 默认采用“安全骨架模式”，即便注入了 v1.0 服务也不会在当前版本
      中真的调用外部大模型。
    """

    def __init__(
        self,
        extraction_service: MultiAgentRelationExtractionService | None = None,
        chunk_filter: HeuristicFilter | None = None,
        syntax_injector: SyntaxInjector | None = None,
        max_concurrency: int = 4,
        target_schemas: Sequence[str] | None = None,
        worker_timeout_seconds: float | None = 1800.0,
    ) -> None:
        """初始化 v2.0 并行抽取引擎。

        Args:
            extraction_service: v1.0 多智能体关系抽取服务的可选实例。当前
                骨架仅记录该依赖，不执行真实调用。
            chunk_filter: 文本块过滤器。若为空，则使用默认启发式过滤器。
            syntax_injector: 句法先验注入器。若为空，则使用默认注入器。
            max_concurrency: Map 阶段的最大并发度，避免无限并发导致资源
                抢占或未来外部模型限流。
            target_schemas: 透传给 v1 抽取服务的标准关系类别库。
            worker_timeout_seconds: 单个 Map Worker 的超时时间，超时后仅丢弃
                当前 Chunk，避免阻断整篇文档。
        """

        self.extraction_service = extraction_service
        self.chunk_filter = chunk_filter or HeuristicFilter()
        self.syntax_injector = syntax_injector or SyntaxInjector()
        self.max_concurrency = max(1, max_concurrency)
        self.target_schemas = list(target_schemas or [])
        self.worker_timeout_seconds = worker_timeout_seconds

    async def map_extract(
        self,
        document_id: str,
        chunks: Sequence[InjectedChunk],
    ) -> list[PartialGraphResult]:
        """并发执行 Map 阶段的局部图谱抽取。

        - 该阶段会把每个 `InjectedChunk` 视为一个独立 Worker 单元。
        - 若配置了 `MultiAgentRelationExtractionService`，每个 Worker 会真实
          调用 v1.0 抽取服务完成单 Chunk 局部图谱抽取。
        - 若未配置抽取服务，则返回空的局部结果，但仍保留可审计元数据，
          方便渐进式集成与测试。
        """

        logger.info("Map 阶段开始，document_id=%s, chunk_count=%d", document_id, len(chunks))

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _guarded_map(chunk: InjectedChunk) -> PartialGraphResult:
            async with semaphore:
                try:
                    task = self._map_single_chunk(document_id=document_id, chunk=chunk)
                    if self.worker_timeout_seconds is not None:
                        return await asyncio.wait_for(task, timeout=self.worker_timeout_seconds)
                    return await task
                except asyncio.TimeoutError:
                    logger.exception(
                        "Map Worker 超时，已跳过当前 chunk，document_id=%s, chunk_id=%s, timeout=%.1fs",
                        document_id,
                        chunk.original_chunk.chunk_id,
                        self.worker_timeout_seconds,
                    )
                except Exception:
                    logger.exception(
                        "Map Worker 失败，已跳过当前 chunk，document_id=%s, chunk_id=%s",
                        document_id,
                        chunk.original_chunk.chunk_id,
                    )

                return PartialGraphResult(
                    document_id=document_id,
                    source_chunk_id=chunk.original_chunk.chunk_id,
                    entities=[],
                    relations=[],
                    metadata={
                        "worker_mode": "failed",
                        "chunk_sequence_no": chunk.original_chunk.sequence_no,
                        "has_injected_text": bool(chunk.injected_text),
                        "injected_hint_keys": sorted(chunk.hints.keys()),
                    },
                )

        return await asyncio.gather(*[_guarded_map(chunk) for chunk in chunks])

    async def reduce_aggregate(
        self,
        document_id: str,
        partial_graphs: Sequence[PartialGraphResult],
    ) -> ExtractionResult:
        """执行 Reduce 阶段，聚合所有 Worker 返回的局部图谱。

        当前实现采用哈希表驱动的确定性聚合策略：

        - 实体按规范化名称进行跨 Chunk 去重，并保留置信度最高的实例。
        - 被淘汰实体的 `surface_form` 会合并到保留实体的运行时别名表中，
          以便后续拓扑分析继续保留表层信息。
        - 关系按 `(head, relation_type, tail)` 唯一键聚合，合并证据 Chunk
          并通过独立证据联合概率公式提升整体置信度。
        - 不引入额外全局模型，因此行为稳定、可审计，适合作为 v2 管线的
          第一版可运行聚合器。
        """

        logger.info(
            "Reduce 阶段开始，document_id=%s, partial_graph_count=%d",
            document_id,
            len(partial_graphs),
        )

        merged_entities: dict[str, EntityMention] = {}
        merged_relations: dict[tuple[str, str, str], TemporalRelation] = {}

        for partial in partial_graphs:
            for entity in partial.entities:
                entity_key = normalize_name(entity.canonical_name or entity.surface_form)
                if not entity_key:
                    continue

                candidate_entity = deepcopy(entity)
                current_best = merged_entities.get(entity_key)
                if current_best is None:
                    merged_entities[entity_key] = candidate_entity
                    continue

                if clamp_confidence(candidate_entity.confidence) > clamp_confidence(current_best.confidence):
                    _merge_entity_aliases(candidate_entity, current_best)
                    merged_entities[entity_key] = candidate_entity
                else:
                    _merge_entity_aliases(current_best, candidate_entity)

            for relation in partial.relations:
                relation_copy = deepcopy(relation)
                relation_key = (
                    normalize_name(relation_copy.head_entity_id),
                    normalize_name(relation_copy.relation_type),
                    normalize_name(relation_copy.tail_entity_id),
                )
                if not all(relation_key):
                    continue

                relation_evidence_ids = list(relation_copy.evidence_chunk_ids)
                if partial.source_chunk_id and partial.source_chunk_id not in relation_evidence_ids:
                    relation_evidence_ids.append(partial.source_chunk_id)

                if relation_key not in merged_relations:
                    relation_copy.evidence_chunk_ids = relation_evidence_ids
                    relation_copy.confidence = clamp_confidence(relation_copy.confidence)
                    merged_relations[relation_key] = relation_copy
                    continue

                existing_relation = merged_relations[relation_key]
                merged_evidence_ids = list(
                    dict.fromkeys(list(existing_relation.evidence_chunk_ids) + relation_evidence_ids)
                )
                existing_relation.evidence_chunk_ids = merged_evidence_ids
                existing_relation.confidence = fuse_independent_confidence(
                    existing_relation.confidence,
                    relation_copy.confidence,
                )
                existing_relation.evidence_texts = list(
                    dict.fromkeys(
                        list(existing_relation.evidence_texts)
                        + list(relation_copy.evidence_texts)
                    )
                )

        logger.debug(
            "Reduce 聚合完成，document_id=%s, merged_entities=%d, merged_relations=%d",
            document_id,
            len(merged_entities),
            len(merged_relations),
        )

        return ExtractionResult(
            document_id=document_id,
            entities=list(merged_entities.values()),
            relations=list(merged_relations.values()),
            agent_trace=[],
            status=ProcessingStatus.EXTRACTED,
        )

    async def process_document(
        self,
        document_id: str,
        chunks: Sequence[CleanedTextChunk],
    ) -> ExtractionResult:
        """执行 Filter -> Inject -> Map -> Reduce 的主编排方法。

        这是 v2.0 对外的统一入口，负责以严格的阶段顺序串联整个长文本抽
        取链路。典型执行流程如下：

        1. Filter: 剔除低价值、低信息密度或明显噪声 Chunk。
        2. Inject: 为保留下来的 Chunk 注入句法和结构化先验提示。
        3. Map: 并发对每个 Chunk 执行局部图谱抽取。
        4. Reduce: 聚合所有局部图谱并进行全局实体合并与消歧。

        当前实现保持“安全可运行”，即使未接入真实模型，也能稳定返回一
        个结构正确的空结果对象。
        """

        logger.info("v2 process_document 开始，document_id=%s", document_id)

        filter_decisions = self.chunk_filter.filter_chunks(chunks)
        retained_chunks = [decision.chunk for decision in filter_decisions if decision.keep]

        logger.info(
            "Filter 阶段完成，document_id=%s, kept=%d, dropped=%d",
            document_id,
            len(retained_chunks),
            len(filter_decisions) - len(retained_chunks),
        )

        injected_chunks = self.syntax_injector.batch_inject(retained_chunks)
        logger.info("Inject 阶段完成，document_id=%s, injected=%d", document_id, len(injected_chunks))

        partial_graphs = await self.map_extract(document_id=document_id, chunks=injected_chunks)
        result = await self.reduce_aggregate(document_id=document_id, partial_graphs=partial_graphs)

        logger.info("v2 process_document 完成，document_id=%s", document_id)
        self._log_filter_summary(document_id=document_id, decisions=filter_decisions)
        return result

    async def _map_single_chunk(
        self,
        document_id: str,
        chunk: InjectedChunk,
    ) -> PartialGraphResult:
        """处理单个 Chunk 的 Map Worker。

        当配置了 `extraction_service` 时，该方法会把当前 Chunk 直接交给
        v1.0 抽取服务执行真实抽取；否则返回空局部结果，保证上层编排在
        无模型依赖时也能安全运行。
        """

        if self.extraction_service is None:
            logger.debug("Map Worker 未配置 extraction_service，返回空局部结果，chunk_id=%s", chunk.original_chunk.chunk_id)
            return PartialGraphResult(
                document_id=document_id,
                source_chunk_id=chunk.original_chunk.chunk_id,
                entities=[],
                relations=[],
                metadata={
                    "worker_mode": "no_extraction_service",
                    "chunk_sequence_no": chunk.original_chunk.sequence_no,
                    "has_injected_text": bool(chunk.injected_text),
                    "injected_hint_keys": sorted(chunk.hints.keys()),
                },
            )

        extraction_result = await self.extraction_service.extract(
            document_id,
            [chunk.original_chunk],
            target_schemas=self.target_schemas,
        )

        return PartialGraphResult(
            document_id=document_id,
            source_chunk_id=chunk.original_chunk.chunk_id,
            entities=list(extraction_result.entities),
            relations=list(extraction_result.relations),
            metadata={
                "worker_mode": "real_extraction",
                "chunk_sequence_no": chunk.original_chunk.sequence_no,
                "has_injected_text": bool(chunk.injected_text),
                "injected_hint_keys": sorted(chunk.hints.keys()),
                "extracted_entity_count": len(extraction_result.entities),
                "extracted_relation_count": len(extraction_result.relations),
            },
        )

    def _log_filter_summary(
        self,
        *,
        document_id: str,
        decisions: Sequence[FilterDecision],
    ) -> None:
        """记录过滤阶段摘要，便于灰度期观测。

        当前只写日志，不将其塞入领域模型，避免在未完成数据契约设计前破
        坏已有的 `ExtractionResult` 边界。
        """

        kept_count = sum(1 for decision in decisions if decision.keep)
        dropped_count = len(decisions) - kept_count

        logger.debug(
            "Filter summary document_id=%s kept=%d dropped=%d",
            document_id,
            kept_count,
            dropped_count,
        )

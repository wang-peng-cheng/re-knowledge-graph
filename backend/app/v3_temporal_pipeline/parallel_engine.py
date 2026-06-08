from __future__ import annotations

import asyncio
import logging
import math
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from app.domain.models import CleanedTextChunk, EntityMention, ExtractionResult, ProcessingStatus, TemporalRelation
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.v2_pipeline.filters import FilterDecision, HeuristicFilter
from app.v2_pipeline.injectors import InjectedChunk, SyntaxInjector

logger = logging.getLogger(__name__)


def normalize_name(value: Any) -> str:
    """对实体名或关系键做轻量归一化，便于哈希聚合。"""

    if value is None:
        return ""
    return str(value).strip().lower()


def clamp_confidence(value: Any) -> float:
    """将置信度裁剪到 [0.0, 1.0] 区间。"""

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


def calculate_hawkes_confidence(
    base_conf: Any,
    current_time: float | None,
    last_mention_time: float | None,
    decay_rate: float = 0.05,
) -> float:
    """计算 Hawkes 风格的时间衰减置信度。"""

    base_value = clamp_confidence(base_conf)
    if current_time is None or last_mention_time is None:
        return base_value

    time_delta = max(0.0, current_time - last_mention_time)
    return clamp_confidence(base_value * math.exp(-decay_rate * time_delta))


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


def _parse_time_value(value: Any) -> float | None:
    """将文本时间解析为可排序的浮点时间戳。"""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    normalized_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized_text).timestamp()
    except ValueError:
        pass

    for time_format in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, time_format).timestamp()
        except ValueError:
            continue
    return None


def _resolve_chunk_time_value(chunk: InjectedChunk) -> float:
    """为 Chunk 解析一个可用于时态排序和衰减计算的时间值。"""

    publish_time = chunk.original_chunk.metadata.get("publish_time", "")
    parsed_publish_time = _parse_time_value(publish_time)
    if parsed_publish_time is not None:
        return parsed_publish_time

    for time_expression in chunk.original_chunk.detected_time_expressions:
        parsed_time_expression = _parse_time_value(time_expression)
        if parsed_time_expression is not None:
            return parsed_time_expression

    return float(chunk.original_chunk.sequence_no)


def _resolve_relation_time_value(relation: TemporalRelation, fallback_time: float) -> float:
    """优先使用关系显式时间，否则回退到 Chunk 时间。"""

    explicit_time = _parse_time_value(relation.observed_at) or _parse_time_value(relation.valid_from)
    if explicit_time is not None:
        return explicit_time
    return fallback_time


def _ensure_relation_temporal_state(relation: TemporalRelation) -> dict[str, Any]:
    """确保关系属性字典中可写入时态演化状态。"""

    if not isinstance(relation.attributes, dict):
        relation.attributes = {}
    return relation.attributes


@dataclass(slots=True)
class PartialGraphResult:
    """表示 Map 阶段单个 Worker 返回的局部图谱结果。"""

    document_id: str
    source_chunk_id: str
    entities: list[Any] = field(default_factory=list)
    relations: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TemporalMapReduceEngine:
    """v3.0 面向时态演化研究的 Map-Reduce 编排引擎。"""

    def __init__(
        self,
        extraction_service: MultiAgentRelationExtractionService | None = None,
        chunk_filter: HeuristicFilter | None = None,
        syntax_injector: SyntaxInjector | None = None,
        max_concurrency: int = 4,
        decay_rate: float = 0.05,
    ) -> None:
        self.extraction_service = extraction_service
        self.chunk_filter = chunk_filter or HeuristicFilter()
        self.syntax_injector = syntax_injector or SyntaxInjector()
        self.max_concurrency = max(1, max_concurrency)
        self.decay_rate = max(0.0, decay_rate)

    async def map_extract(
        self,
        document_id: str,
        chunks: Sequence[InjectedChunk],
    ) -> list[PartialGraphResult]:
        """并发执行 Map 阶段的局部图谱抽取。"""

        logger.info("V3 Map 阶段开始，document_id=%s, chunk_count=%d", document_id, len(chunks))

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _guarded_map(chunk: InjectedChunk) -> PartialGraphResult:
            async with semaphore:
                return await self._map_single_chunk(document_id=document_id, chunk=chunk)

        return await asyncio.gather(*[_guarded_map(chunk) for chunk in chunks])

    async def reduce_aggregate(
        self,
        document_id: str,
        partial_graphs: Sequence[PartialGraphResult],
    ) -> ExtractionResult:
        """执行带 Hawkes 衰减与自激发机制的时态 Reduce 聚合。"""

        logger.info(
            "V3 Reduce 阶段开始，document_id=%s, partial_graph_count=%d",
            document_id,
            len(partial_graphs),
        )

        merged_entities: dict[str, EntityMention] = {}
        merged_relations: dict[tuple[str, str, str], TemporalRelation] = {}

        sorted_partial_graphs = sorted(
            partial_graphs,
            key=lambda item: float(item.metadata.get("chunk_time_value", 0.0)),
        )

        for partial in sorted_partial_graphs:
            chunk_time_value = float(partial.metadata.get("chunk_time_value", 0.0))
            chunk_time_text = partial.metadata.get("chunk_time_text")

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

                relation_time_value = _resolve_relation_time_value(relation_copy, chunk_time_value)
                relation_evidence_ids = list(relation_copy.evidence_chunk_ids)
                if partial.source_chunk_id and partial.source_chunk_id not in relation_evidence_ids:
                    relation_evidence_ids.append(partial.source_chunk_id)

                relation_state = _ensure_relation_temporal_state(relation_copy)
                if relation_key not in merged_relations:
                    relation_copy.evidence_chunk_ids = relation_evidence_ids
                    relation_copy.confidence = clamp_confidence(relation_copy.confidence)
                    relation_state["last_mention_time"] = chunk_time_text or relation_time_value
                    relation_state["last_mention_time_value"] = relation_time_value
                    relation_state["decayed_confidence"] = calculate_hawkes_confidence(
                        relation_copy.confidence,
                        relation_time_value,
                        relation_time_value,
                        decay_rate=self.decay_rate,
                    )
                    merged_relations[relation_key] = relation_copy
                    continue

                existing_relation = merged_relations[relation_key]
                existing_state = _ensure_relation_temporal_state(existing_relation)
                previous_mention_time = existing_state.get("last_mention_time_value")
                decayed_existing_confidence = calculate_hawkes_confidence(
                    existing_relation.confidence,
                    relation_time_value,
                    previous_mention_time if isinstance(previous_mention_time, (int, float)) else None,
                    decay_rate=self.decay_rate,
                )

                merged_evidence_ids = list(
                    dict.fromkeys(list(existing_relation.evidence_chunk_ids) + relation_evidence_ids)
                )
                existing_relation.evidence_chunk_ids = merged_evidence_ids
                existing_relation.evidence_texts = list(
                    dict.fromkeys(list(existing_relation.evidence_texts) + list(relation_copy.evidence_texts))
                )

                # 新提及到来时触发自激发：先按 Hawkes 衰减旧置信度，再与新证据做 D-S 风格融合。
                existing_relation.confidence = fuse_independent_confidence(
                    decayed_existing_confidence,
                    relation_copy.confidence,
                )
                existing_state["last_mention_time"] = chunk_time_text or relation_time_value
                existing_state["last_mention_time_value"] = relation_time_value
                existing_state["decayed_confidence"] = calculate_hawkes_confidence(
                    existing_relation.confidence,
                    relation_time_value,
                    relation_time_value,
                    decay_rate=self.decay_rate,
                )

        logger.debug(
            "V3 Reduce 聚合完成，document_id=%s, merged_entities=%d, merged_relations=%d",
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
        """执行 Filter -> Inject -> Map -> Temporal Reduce 的主编排方法。"""

        logger.info("v3 process_document 开始，document_id=%s", document_id)

        filter_decisions = self.chunk_filter.filter_chunks(chunks)
        retained_chunks = [decision.chunk for decision in filter_decisions if decision.keep]

        logger.info(
            "V3 Filter 阶段完成，document_id=%s, kept=%d, dropped=%d",
            document_id,
            len(retained_chunks),
            len(filter_decisions) - len(retained_chunks),
        )

        injected_chunks = self.syntax_injector.batch_inject(retained_chunks)
        logger.info("V3 Inject 阶段完成，document_id=%s, injected=%d", document_id, len(injected_chunks))

        partial_graphs = await self.map_extract(document_id=document_id, chunks=injected_chunks)
        result = await self.reduce_aggregate(document_id=document_id, partial_graphs=partial_graphs)

        logger.info("v3 process_document 完成，document_id=%s", document_id)
        self._log_filter_summary(document_id=document_id, decisions=filter_decisions)
        return result

    async def _map_single_chunk(
        self,
        document_id: str,
        chunk: InjectedChunk,
    ) -> PartialGraphResult:
        """处理单个 Chunk 的 Map Worker，并透传时间元数据。"""

        chunk_time_value = _resolve_chunk_time_value(chunk)
        chunk_time_text = chunk.original_chunk.metadata.get("publish_time") or (
            chunk.original_chunk.detected_time_expressions[0] if chunk.original_chunk.detected_time_expressions else ""
        )

        if self.extraction_service is None:
            logger.debug("V3 Map Worker 未配置 extraction_service，返回空局部结果，chunk_id=%s", chunk.original_chunk.chunk_id)
            return PartialGraphResult(
                document_id=document_id,
                source_chunk_id=chunk.original_chunk.chunk_id,
                entities=[],
                relations=[],
                metadata={
                    "worker_mode": "no_extraction_service",
                    "chunk_sequence_no": chunk.original_chunk.sequence_no,
                    "chunk_time_value": chunk_time_value,
                    "chunk_time_text": chunk_time_text,
                    "has_injected_text": bool(chunk.injected_text),
                    "injected_hint_keys": sorted(chunk.hints.keys()),
                },
            )

        extraction_result = await self.extraction_service.extract(
            document_id,
            [chunk.original_chunk],
        )

        return PartialGraphResult(
            document_id=document_id,
            source_chunk_id=chunk.original_chunk.chunk_id,
            entities=list(extraction_result.entities),
            relations=list(extraction_result.relations),
            metadata={
                "worker_mode": "real_extraction",
                "chunk_sequence_no": chunk.original_chunk.sequence_no,
                "chunk_time_value": chunk_time_value,
                "chunk_time_text": chunk_time_text,
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
        """记录过滤阶段摘要，便于灰度期观测。"""

        kept_count = sum(1 for decision in decisions if decision.keep)
        dropped_count = len(decisions) - kept_count

        logger.debug(
            "V3 Filter summary document_id=%s kept=%d dropped=%d",
            document_id,
            kept_count,
            dropped_count,
        )

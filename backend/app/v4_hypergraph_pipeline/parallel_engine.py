from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.models import CleanedTextChunk, EntityMention, ExtractionResult, TemporalRelation
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.v2_pipeline.filters import FilterDecision, HeuristicFilter
from app.v2_pipeline.injectors import InjectedChunk, SyntaxInjector

logger = logging.getLogger(__name__)


def normalize_name(value: Any) -> str:
    """对实体名或事件类型做轻量归一化。"""

    if value is None:
        return ""
    return str(value).strip().lower()


def sanitize_identifier(value: Any) -> str:
    """生成适合拼接为事件标识的安全字符串。"""

    normalized = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", str(value).strip())
    return normalized.strip("_") or "unknown"


def clamp_confidence(value: Any) -> float:
    """将置信度裁剪到 [0.0, 1.0] 区间。"""

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric_value))


@dataclass(slots=True)
class HyperEdgeParticipant:
    """定义超边中的单个参与者及其角色。"""

    entity_id: str
    entity_name: str
    role: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HyperEdgeResult:
    """定义以事件为中心的星型超边。"""

    event_id: str
    event_type: str
    core_entities: list[str] = field(default_factory=list)
    participants: list[HyperEdgeParticipant] = field(default_factory=list)
    supporting_chunk_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PartialHypergraphResult:
    """表示 Map 阶段单个 Worker 返回的局部超图结果。"""

    document_id: str
    source_chunk_id: str
    entities: list[EntityMention] = field(default_factory=list)
    relations: list[TemporalRelation] = field(default_factory=list)
    hyperedges: list[HyperEdgeResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HypergraphExtractionResult:
    """定义 V4 超图抽取引擎的最终输出。"""

    document_id: str
    hyperedges: list[HyperEdgeResult] = field(default_factory=list)
    incidence_matrix: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _build_entity_lookup(entities: Sequence[EntityMention]) -> dict[str, EntityMention]:
    """构建实体 ID 到实体对象的映射。"""

    return {entity.entity_id: entity for entity in entities}


def _build_hyperedge_participants(
    relation: TemporalRelation,
    entity_lookup: dict[str, EntityMention],
) -> tuple[list[HyperEdgeParticipant], list[str]]:
    """根据一条二元关系构造局部超边参与者列表与核心实体集合。"""

    participants: list[HyperEdgeParticipant] = []
    core_entities: list[str] = []

    head_entity = entity_lookup.get(relation.head_entity_id)
    tail_entity = entity_lookup.get(relation.tail_entity_id)

    for entity, role in ((head_entity, "head"), (tail_entity, "tail")):
        if entity is None:
            continue
        entity_name = entity.canonical_name or entity.surface_form or entity.entity_id
        normalized_entity_name = normalize_name(entity_name)
        if normalized_entity_name and normalized_entity_name not in core_entities:
            core_entities.append(normalized_entity_name)
        participants.append(
            HyperEdgeParticipant(
                entity_id=entity.entity_id,
                entity_name=entity_name,
                role=role,
                confidence=clamp_confidence(entity.confidence),
            )
        )

    attributes = relation.attributes if isinstance(relation.attributes, dict) else {}
    raw_participants = attributes.get("participants", [])
    if isinstance(raw_participants, list):
        for item in raw_participants:
            if not isinstance(item, dict):
                continue
            entity_name = str(item.get("entity") or item.get("name") or "").strip()
            role = str(item.get("role") or "participant").strip() or "participant"
            if not entity_name:
                continue
            participants.append(
                HyperEdgeParticipant(
                    entity_id=str(item.get("entity_id") or sanitize_identifier(entity_name)),
                    entity_name=entity_name,
                    role=role,
                    confidence=clamp_confidence(item.get("confidence", relation.confidence)),
                    metadata={"source": "relation.attributes.participants"},
                )
            )

    return participants, core_entities


def _build_local_hyperedges(
    chunk_id: str,
    extraction_result: ExtractionResult,
) -> list[HyperEdgeResult]:
    """将 V1/V2 风格的二元关系结果重组为局部星型超边。"""

    entity_lookup = _build_entity_lookup(extraction_result.entities)
    hyperedges: list[HyperEdgeResult] = []

    for relation_index, relation in enumerate(extraction_result.relations):
        participants, core_entities = _build_hyperedge_participants(relation, entity_lookup)
        if not participants:
            continue

        event_type = relation.relation_type or "unknown_event"
        event_id = f"Event_{sanitize_identifier(event_type)}_{sanitize_identifier(chunk_id)}_{relation_index:03d}"
        hyperedges.append(
            HyperEdgeResult(
                event_id=event_id,
                event_type=event_type,
                core_entities=core_entities,
                participants=participants,
                supporting_chunk_ids=[chunk_id],
                confidence=clamp_confidence(relation.confidence),
                metadata={
                    "source_relation_id": relation.relation_id,
                    "observed_at": relation.observed_at,
                    "valid_from": relation.valid_from,
                    "valid_to": relation.valid_to,
                    "attributes": dict(relation.attributes) if isinstance(relation.attributes, dict) else {},
                },
            )
        )

    return hyperedges


def _merge_participants(existing: HyperEdgeResult, incoming: HyperEdgeResult) -> None:
    """将新增参与者合并到已有事件中心。"""

    participant_index = {
        (normalize_name(participant.entity_name), normalize_name(participant.role)): participant
        for participant in existing.participants
    }

    for participant in incoming.participants:
        participant_key = (normalize_name(participant.entity_name), normalize_name(participant.role))
        if participant_key not in participant_index:
            existing.participants.append(participant)
            participant_index[participant_key] = participant
            continue

        current_participant = participant_index[participant_key]
        if participant.confidence > current_participant.confidence:
            current_participant.confidence = participant.confidence
        if participant.entity_id and not current_participant.entity_id:
            current_participant.entity_id = participant.entity_id


def _build_incidence_matrix(hyperedges: Sequence[HyperEdgeResult]) -> dict[str, Any]:
    """将超图结果转换为直观的关联矩阵表示。"""

    entity_columns = sorted(
        {
            participant.entity_name
            for hyperedge in hyperedges
            for participant in hyperedge.participants
            if participant.entity_name
        }
    )
    event_rows = [hyperedge.event_id for hyperedge in hyperedges]

    values: list[list[int]] = []
    role_annotations: list[dict[str, str]] = []
    for hyperedge in hyperedges:
        participant_names = {participant.entity_name for participant in hyperedge.participants}
        values.append([1 if entity_name in participant_names else 0 for entity_name in entity_columns])
        role_annotations.append({participant.entity_name: participant.role for participant in hyperedge.participants})

    return {
        "rows": event_rows,
        "columns": entity_columns,
        "values": values,
        "role_annotations": role_annotations,
    }


class HypergraphExtractionEngine:
    """v4.0 面向高阶网络与超图建模的独立抽取引擎。"""

    def __init__(
        self,
        extraction_service: MultiAgentRelationExtractionService | None = None,
        chunk_filter: HeuristicFilter | None = None,
        syntax_injector: SyntaxInjector | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.extraction_service = extraction_service
        self.chunk_filter = chunk_filter or HeuristicFilter()
        self.syntax_injector = syntax_injector or SyntaxInjector()
        self.max_concurrency = max(1, max_concurrency)

    async def map_extract(
        self,
        document_id: str,
        chunks: Sequence[InjectedChunk],
    ) -> list[PartialHypergraphResult]:
        """并发执行 Map 阶段的局部超图抽取。"""

        logger.info("V4 Map 阶段开始，document_id=%s, chunk_count=%d", document_id, len(chunks))

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _guarded_map(chunk: InjectedChunk) -> PartialHypergraphResult:
            async with semaphore:
                return await self._map_single_chunk(document_id=document_id, chunk=chunk)

        return await asyncio.gather(*[_guarded_map(chunk) for chunk in chunks])

    async def reduce_aggregate(
        self,
        document_id: str,
        partial_graphs: Sequence[PartialHypergraphResult],
    ) -> HypergraphExtractionResult:
        """按事件类型与核心实体交集执行全局超边聚合。"""

        logger.info(
            "V4 Reduce 阶段开始，document_id=%s, partial_graph_count=%d",
            document_id,
            len(partial_graphs),
        )

        merged_hyperedges: dict[str, HyperEdgeResult] = {}
        core_entity_index: dict[tuple[str, str], set[str]] = {}

        for partial in partial_graphs:
            for hyperedge in partial.hyperedges:
                normalized_event_type = normalize_name(hyperedge.event_type)
                normalized_core_entities = [normalize_name(entity_name) for entity_name in hyperedge.core_entities if normalize_name(entity_name)]

                candidate_event_ids: set[str] = set()
                for core_entity in normalized_core_entities:
                    candidate_event_ids.update(core_entity_index.get((normalized_event_type, core_entity), set()))

                target_event_id: str | None = None
                for existing_event_id in sorted(candidate_event_ids):
                    existing_hyperedge = merged_hyperedges.get(existing_event_id)
                    if existing_hyperedge is None:
                        continue
                    existing_core_entity_set = {normalize_name(item) for item in existing_hyperedge.core_entities}
                    if existing_core_entity_set.intersection(normalized_core_entities):
                        target_event_id = existing_event_id
                        break

                if target_event_id is None:
                    merged_hyperedge = HyperEdgeResult(
                        event_id=hyperedge.event_id,
                        event_type=hyperedge.event_type,
                        core_entities=list(dict.fromkeys(hyperedge.core_entities)),
                        participants=list(hyperedge.participants),
                        supporting_chunk_ids=list(dict.fromkeys(hyperedge.supporting_chunk_ids)),
                        confidence=hyperedge.confidence,
                        metadata=dict(hyperedge.metadata),
                    )
                    merged_hyperedges[merged_hyperedge.event_id] = merged_hyperedge
                    for core_entity in normalized_core_entities:
                        core_entity_index.setdefault((normalized_event_type, core_entity), set()).add(merged_hyperedge.event_id)
                    continue

                existing_hyperedge = merged_hyperedges[target_event_id]
                existing_hyperedge.core_entities = list(
                    dict.fromkeys(existing_hyperedge.core_entities + hyperedge.core_entities)
                )
                existing_hyperedge.supporting_chunk_ids = list(
                    dict.fromkeys(existing_hyperedge.supporting_chunk_ids + hyperedge.supporting_chunk_ids)
                )
                existing_hyperedge.confidence = max(existing_hyperedge.confidence, hyperedge.confidence)
                _merge_participants(existing_hyperedge, hyperedge)

                for core_entity in normalized_core_entities:
                    core_entity_index.setdefault((normalized_event_type, core_entity), set()).add(target_event_id)

        hyperedges = list(merged_hyperedges.values())
        incidence_matrix = _build_incidence_matrix(hyperedges)

        return HypergraphExtractionResult(
            document_id=document_id,
            hyperedges=hyperedges,
            incidence_matrix=incidence_matrix,
            metadata={
                "hyperedge_count": len(hyperedges),
                "event_topology": "star_schema",
                "aggregation_strategy": "event_type_plus_core_entity_intersection",
            },
        )

    async def process_document(
        self,
        document_id: str,
        chunks: Sequence[CleanedTextChunk],
    ) -> HypergraphExtractionResult:
        """执行 Filter -> Inject -> Map -> Hypergraph Reduce 的主编排方法。"""

        logger.info("V4 process_document 开始，document_id=%s", document_id)

        filter_decisions = self.chunk_filter.filter_chunks(chunks)
        retained_chunks = [decision.chunk for decision in filter_decisions if decision.keep]

        logger.info(
            "V4 Filter 阶段完成，document_id=%s, kept=%d, dropped=%d",
            document_id,
            len(retained_chunks),
            len(filter_decisions) - len(retained_chunks),
        )

        injected_chunks = self.syntax_injector.batch_inject(retained_chunks)
        logger.info("V4 Inject 阶段完成，document_id=%s, injected=%d", document_id, len(injected_chunks))

        partial_graphs = await self.map_extract(document_id=document_id, chunks=injected_chunks)
        result = await self.reduce_aggregate(document_id=document_id, partial_graphs=partial_graphs)

        logger.info("V4 process_document 完成，document_id=%s", document_id)
        self._log_filter_summary(document_id=document_id, decisions=filter_decisions)
        return result

    async def _map_single_chunk(
        self,
        document_id: str,
        chunk: InjectedChunk,
    ) -> PartialHypergraphResult:
        """处理单个 Chunk 的 Map Worker，并将二元关系重组为局部超边。"""

        if self.extraction_service is None:
            logger.debug("V4 Map Worker 未配置 extraction_service，返回空局部超图结果，chunk_id=%s", chunk.original_chunk.chunk_id)
            return PartialHypergraphResult(
                document_id=document_id,
                source_chunk_id=chunk.original_chunk.chunk_id,
                entities=[],
                relations=[],
                hyperedges=[],
                metadata={
                    "worker_mode": "no_extraction_service",
                    "chunk_sequence_no": chunk.original_chunk.sequence_no,
                    "has_injected_text": bool(chunk.injected_text),
                },
            )

        extraction_result = await self.extraction_service.extract(
            document_id,
            [chunk.original_chunk],
        )
        hyperedges = _build_local_hyperedges(
            chunk_id=chunk.original_chunk.chunk_id,
            extraction_result=extraction_result,
        )

        return PartialHypergraphResult(
            document_id=document_id,
            source_chunk_id=chunk.original_chunk.chunk_id,
            entities=list(extraction_result.entities),
            relations=list(extraction_result.relations),
            hyperedges=hyperedges,
            metadata={
                "worker_mode": "real_extraction",
                "chunk_sequence_no": chunk.original_chunk.sequence_no,
                "has_injected_text": bool(chunk.injected_text),
                "local_hyperedge_count": len(hyperedges),
            },
        )

    def _log_filter_summary(
        self,
        *,
        document_id: str,
        decisions: Sequence[FilterDecision],
    ) -> None:
        """记录过滤阶段摘要。"""

        kept_count = sum(1 for decision in decisions if decision.keep)
        dropped_count = len(decisions) - kept_count

        logger.debug(
            "V4 Filter summary document_id=%s kept=%d dropped=%d",
            document_id,
            kept_count,
            dropped_count,
        )

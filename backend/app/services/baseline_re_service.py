from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Sequence

from app.adapters.llm.qwen_client import QwenClient
from app.domain.models import AgentDecision, CleanedTextChunk, EntityMention, ExtractionResult, TemporalRelation

logger = logging.getLogger(__name__)


class BaselineRelationExtractionService:
    """单体大模型关系抽取 Baseline 服务。

    该服务用于论文中的 Baseline 对比实验，刻意不引入多智能体博弈、
    自我降噪、时间纠错或复杂容错逻辑，而是直接将所有文本块拼接后
    一次性提交给大模型，观察单体模型在脏数据场景下的真实表现。
    """

    def __init__(self, qwen_client: QwenClient) -> None:
        """初始化 Baseline 关系抽取服务。

        Args:
            qwen_client: 大模型访问客户端。
        """

        self.qwen_client = qwen_client

    async def extract(self, document_id: str, chunks: Sequence[CleanedTextChunk]) -> ExtractionResult:
        """执行单次 Prompt 的 Baseline 关系抽取。

        Args:
            document_id: 当前待抽取文档的唯一标识。
            chunks: 已完成清洗的文本块序列。

        Returns:
            ExtractionResult: 直接由单体大模型输出组装得到的抽取结果。
        """

        logger.info("开始 Baseline 单体关系抽取，文档: %s，文本块数量: %d", document_id, len(chunks))

        messages = self._build_messages(document_id=document_id, chunks=chunks)
        response_text = await self.qwen_client.chat(messages, temperature=0.2)
        payload = self._extract_json_payload(response_text)

        entities = [
            EntityMention(
                entity_id=item["entity_id"],
                surface_form=item["surface_form"],
                canonical_name=item["canonical_name"],
                entity_type=item["entity_type"],
                char_start=item.get("char_start", 0),
                char_end=item.get("char_end", 0),
                confidence=item.get("confidence", 0.0),
            )
            for item in payload.get("entities", [])
        ]

        relations = [
            TemporalRelation(
                relation_id=item["relation_id"],
                head_entity_id=item["head_entity_id"],
                tail_entity_id=item["tail_entity_id"],
                relation_type=item["relation_type"],
                confidence=item.get("confidence", 0.0),
                observed_at=item.get("observed_at"),
                valid_from=item.get("valid_from"),
                valid_to=item.get("valid_to"),
                evidence_chunk_ids=item.get("evidence_chunk_ids", []),
                evidence_texts=item.get("evidence_texts", []),
                agent_votes=item.get("agent_votes", {}),
                attributes=item.get("attributes", {}),
            )
            for item in payload.get("relations", [])
        ]

        baseline_trace = AgentDecision(
            agent_role="extractor",
            rationale=payload.get("rationale", "Baseline 单次调用，无多智能体博弈。"),
            accepted_relations=[relation.relation_id for relation in relations],
            rejected_relations=[],
            metadata={
                "baseline_mode": "single_prompt",
                "raw_response": response_text,
            },
        )

        result = ExtractionResult(
            document_id=document_id,
            entities=entities,
            relations=relations,
            agent_trace=[baseline_trace],
        )

        logger.info(
            "Baseline 单体关系抽取完成，文档: %s，实体数量: %d，关系数量: %d",
            document_id,
            len(result.entities),
            len(result.relations),
        )
        return result

    def _build_messages(self, document_id: str, chunks: Sequence[CleanedTextChunk]) -> List[Dict[str, str]]:
        """构建单次 Baseline Prompt。"""

        joined_chunks = "\n\n".join(
            [
                (
                    f"文本块序号: {chunk.sequence_no}\n"
                    f"文本块ID: {chunk.chunk_id}\n"
                    f"文本内容: {chunk.cleaned_text}\n"
                    f"时间表达: {chunk.detected_time_expressions}\n"
                    f"元数据: {json.dumps(chunk.metadata, ensure_ascii=False)}"
                )
                for chunk in chunks
            ]
        )

        return [
            {
                "role": "system",
                "content": (
                    "你是一个单体关系抽取模型。"
                    "请抽取出文本中的所有实体和关系，并以 JSON 格式返回。"
                    "输出格式必须为 ```json 代码块，且 JSON 顶层包含 "
                    "`rationale`、`entities`、`relations` 三个字段。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"文档ID: {document_id}\n\n"
                    f"以下是待抽取文本，请直接抽取出文本中的所有实体和关系，并以 JSON 格式返回：\n\n{joined_chunks}"
                ),
            },
        ]

    def _extract_json_payload(self, response_text: str) -> Dict[str, Any]:
        """从大模型响应中提取 JSON 负载。"""

        json_block_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_block_match:
            return json.loads(json_block_match.group(1))

        fallback_match = re.search(r"(\{[\s\S]*\})", response_text)
        if fallback_match:
            return json.loads(fallback_match.group(1))

        logger.error("Baseline 响应中未找到可解析的 JSON，原始响应: %s", response_text)
        raise ValueError("大模型返回内容中未找到 JSON 数据。")

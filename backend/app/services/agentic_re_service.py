from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from app.adapters.llm.base import LLMClientProtocol
from app.domain.models import AgentDecision, CleanedTextChunk, EntityMention, ExtractionResult, TemporalRelation

logger = logging.getLogger(__name__)


class MultiAgentRelationExtractionService:
    """多智能体零样本关系抽取服务实现。"""

    def __init__(self, llm_client: LLMClientProtocol) -> None:
        self.llm_client = llm_client
        # 保留兼容别名，避免现有调用点和调试脚本失效。
        self.qwen_client = llm_client

    def _extract_json_from_response(self, response: str, agent_name: str) -> Dict[str, Any]:
        """从大模型响应中稳健提取并解析 JSON。

        提取策略（按优先级执行）：
        1) 优先提取 ```json ... ``` 代码块中的内容。
        2) 若未找到 json 标签，尝试提取任意 ``` ... ``` 代码块内容作为候选 JSON。
        3) 若仍未找到，使用兜底正则从原始文本中提取最外层的 {...} 或 [...]：
           re.search(r'(\\{[\\s\\S]*\\}|\\[[\\s\\S]*\\])', response)
        4) 若仍失败，打印包含 agent_name 的详细现场（含原始 response）并抛出 ValueError。

        解析策略：
        - 对候选字符串使用 json.loads 解析。
        - 若发生 JSONDecodeError，打印原始候选字符串并抛出异常，便于定位模型输出问题。

        Args:
            response: 大模型返回的原始文本响应。
            agent_name: 代理名称，用于错误现场定位（例如 Planner/Extractor/Critic/Judge）。

        Returns:
            Dict[str, Any]: 解析后的 JSON 字典对象。

        Raises:
            ValueError: 无法从响应中提取 JSON 时抛出。
            json.JSONDecodeError: JSON 解析失败时抛出。
        """

        json_str: str | None = None

        json_block = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL | re.IGNORECASE)
        if json_block:
            json_str = json_block.group(1)
        else:
            any_code_block = re.search(r"```\s*(.*?)\s*```", response, re.DOTALL)
            if any_code_block:
                json_str = any_code_block.group(1)
            else:
                fallback = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
                if fallback:
                    json_str = fallback.group(1)

        if not json_str:
            print(f"❌ [{agent_name}] 未在模型输出中找到可解析的 JSON。原始 response 如下：\n{response}")
            raise ValueError(f"[{agent_name}] 响应中未找到 JSON 内容")

        try:
            try:
                import json_repair  # type: ignore
            except Exception:
                json_repair = None  # type: ignore

            if json_repair is not None:
                parsed = json_repair.loads(json_str)  # type: ignore[attr-defined]
            else:
                parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            print(
                f"❌ [{agent_name}] JSON 解析失败: {exc}\n"
                f"------ 原始候选 JSON 字符串 ------\n{json_str}\n"
                f"------ 原始 response（便于对照） ------\n{response}"
            )
            raise
        except Exception as exc:
            print(
                f"❌ [{agent_name}] JSON 解析发生异常: {exc}\n"
                f"------ 原始候选 JSON 字符串 ------\n{json_str}\n"
                f"------ 原始 response（便于对照） ------\n{response}"
            )
            raise

        if not isinstance(parsed, dict):
            print(
                f"❌ [{agent_name}] JSON 顶层不是对象(dict)，实际类型: {type(parsed)}\n"
                f"------ 原始候选 JSON 字符串 ------\n{json_str}\n"
                f"------ 原始 response ------\n{response}"
            )
            raise ValueError(f"[{agent_name}] JSON 顶层必须为对象(dict)")

        return parsed

    def _align_and_clean_judge_output(self, judge_data: Dict[str, Any], extractor_decision: AgentDecision) -> Dict[str, Any]:
        """对 Judge 输出进行接口规范化与外键对齐。

        该方法的目标是在不改变多智能体核心流程的前提下，尽可能把模型输出
        的“脏字段/乱字段”转换为可被 Pydantic 模型接收的标准结构。
        """

        def _is_placeholder_entity_name(value: Any) -> bool:
            if value is None:
                return False
            s = str(value).strip().lower()
            return bool(re.match(r"^ent[_-]?\d+$", s))

        def _extract_name_from_entity_dict(entity: Dict[str, Any]) -> str:
            return (
                entity.get("surface_form")
                or entity.get("canonical_name")
                or entity.get("name")
                or entity.get("text")
                or entity.get("姓名")
                or entity.get("地域")
                or _pick_first_string_value(entity)
                or ""
            ).strip()

        extractor_names: Dict[str, str] = {}

        extractor_meta = extractor_decision.metadata if isinstance(extractor_decision.metadata, dict) else {}
        extractor_entities = extractor_meta.get("entities", [])
        if isinstance(extractor_entities, list):
            for ent in extractor_entities:
                if not isinstance(ent, dict):
                    continue
                eid = ent.get("entity_id") or ent.get("id")
                if not eid:
                    continue
                name = _extract_name_from_entity_dict(ent)
                if name and not _is_placeholder_entity_name(name):
                    extractor_names[str(eid)] = name

        extractor_candidates = extractor_meta.get("candidate_relations", [])
        if isinstance(extractor_candidates, list):
            for rel in extractor_candidates:
                if not isinstance(rel, dict):
                    continue
                h_id = rel.get("head_entity_id") or rel.get("h") or rel.get("head")
                t_id = rel.get("tail_entity_id") or rel.get("t") or rel.get("tail")
                h_name = rel.get("head_entity_name") or rel.get("head_name") or rel.get("head_entity") or ""
                t_name = rel.get("tail_entity_name") or rel.get("tail_name") or rel.get("tail_entity") or ""
                if h_id and isinstance(h_name, str) and h_name.strip() and not _is_placeholder_entity_name(h_name):
                    extractor_names.setdefault(str(h_id), h_name.strip())
                if t_id and isinstance(t_name, str) and t_name.strip() and not _is_placeholder_entity_name(t_name):
                    extractor_names.setdefault(str(t_id), t_name.strip())

        if isinstance(extractor_decision.accepted_relations, list):
            for item in extractor_decision.accepted_relations:
                if not isinstance(item, str):
                    continue
                try:
                    rel = json.loads(item)
                except Exception:
                    continue
                if not isinstance(rel, dict):
                    continue
                h_id = rel.get("head_entity_id") or rel.get("h") or rel.get("head")
                t_id = rel.get("tail_entity_id") or rel.get("t") or rel.get("tail")
                h_name = rel.get("head_entity_name") or rel.get("head_name") or rel.get("head_entity") or ""
                t_name = rel.get("tail_entity_name") or rel.get("tail_name") or rel.get("tail_entity") or ""
                if h_id and isinstance(h_name, str) and h_name.strip() and not _is_placeholder_entity_name(h_name):
                    extractor_names.setdefault(str(h_id), h_name.strip())
                if t_id and isinstance(t_name, str) and t_name.strip() and not _is_placeholder_entity_name(t_name):
                    extractor_names.setdefault(str(t_id), t_name.strip())

        def _pick_first_string_value(payload: Dict[str, Any]) -> str:
            for _, v in payload.items():
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""

        def _clean_time_value(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, str):
                if not value.strip():
                    return None
                if re.search(r"[\u4e00-\u9fff]", value):
                    return None
            return value

        raw_entities = judge_data.get("entities", [])
        cleaned_entities: List[Dict[str, Any]] = []
        name_to_id: Dict[str, str] = {}

        if isinstance(raw_entities, list):
            for entity in raw_entities:
                if isinstance(entity, str):
                    entity_dict: Dict[str, Any] = {"surface_form": entity}
                elif isinstance(entity, dict):
                    entity_dict = dict(entity)
                else:
                    entity_dict = {"surface_form": str(entity)}

                entity_id = entity_dict.get("entity_id") or entity_dict.get("id") or f"ent_{uuid4().hex[:8]}"
                surface_form = (
                    entity_dict.get("surface_form")
                    or entity_dict.get("name")
                    or entity_dict.get("text")
                    or entity_dict.get("姓名")
                    or entity_dict.get("地域")
                    or _pick_first_string_value(entity_dict)
                    or "未知实体"
                )

                if _is_placeholder_entity_name(surface_form):
                    recovered = extractor_names.get(str(entity_id))
                    if recovered:
                        surface_form = recovered

                canonical_name = entity_dict.get("canonical_name") or surface_form
                entity_type = entity_dict.get("entity_type") or entity_dict.get("type") or "UNKNOWN"

                cleaned = {
                    "entity_id": str(entity_id),
                    "surface_form": str(surface_form),
                    "canonical_name": str(canonical_name),
                    "entity_type": str(entity_type),
                    "char_start": int(entity_dict.get("char_start", 0) or 0),
                    "char_end": int(entity_dict.get("char_end", 0) or 0),
                    "confidence": float(entity_dict.get("confidence", 0.9) or 0.9),
                }
                cleaned_entities.append(cleaned)

                if cleaned["surface_form"]:
                    name_to_id[cleaned["surface_form"]] = cleaned["entity_id"]
                if cleaned["canonical_name"]:
                    name_to_id[cleaned["canonical_name"]] = cleaned["entity_id"]

        raw_relations = judge_data.get("relations", [])
        cleaned_relations: List[Dict[str, Any]] = []

        if isinstance(raw_relations, list):
            for relation in raw_relations:
                if not isinstance(relation, dict):
                    continue

                rel = dict(relation)
                relation_id = rel.get("relation_id") or rel.get("id") or f"rel_{uuid4().hex[:8]}"

                head_val = (
                    rel.get("head_entity_id")
                    or rel.get("head_entity")
                    or rel.get("head")
                    or rel.get("source")
                    or rel.get("h")
                    or ""
                )
                tail_val = (
                    rel.get("tail_entity_id")
                    or rel.get("tail_entity")
                    or rel.get("tail")
                    or rel.get("target")
                    or rel.get("t")
                    or ""
                )
                if isinstance(head_val, str) and head_val in name_to_id:
                    head_val = name_to_id[head_val]
                if isinstance(tail_val, str) and tail_val in name_to_id:
                    tail_val = name_to_id[tail_val]

                relation_type = rel.get("relation_type") or rel.get("type") or rel.get("r") or "UNKNOWN"

                evidence_chunk_ids = rel.get("evidence_chunk_ids", [])
                if not isinstance(evidence_chunk_ids, list):
                    evidence_chunk_ids = []

                evidence_texts = rel.get("evidence_texts", [])
                if not isinstance(evidence_texts, list):
                    evidence_texts = []

                agent_votes = rel.get("agent_votes", {})
                if not isinstance(agent_votes, dict):
                    agent_votes = {}

                attributes = rel.get("attributes", {})
                if not isinstance(attributes, dict):
                    attributes = {}

                cleaned_relations.append(
                    {
                        "relation_id": str(relation_id),
                        "head_entity_id": str(head_val),
                        "tail_entity_id": str(tail_val),
                        "relation_type": str(relation_type),
                        "confidence": float(rel.get("confidence", 0.8) or 0.8),
                        "observed_at": _clean_time_value(rel.get("observed_at")),
                        "valid_from": _clean_time_value(rel.get("valid_from")),
                        "valid_to": _clean_time_value(rel.get("valid_to")),
                        "evidence_chunk_ids": evidence_chunk_ids,
                        "evidence_texts": evidence_texts,
                        "agent_votes": agent_votes,
                        "attributes": attributes,
                    }
                )

        judge_data["entities"] = cleaned_entities
        judge_data["relations"] = cleaned_relations
        return judge_data

    async def extract(
        self,
        document_id: str,
        chunks: Sequence[CleanedTextChunk],
        *,
        target_schemas: Sequence[str] | None = None,
    ) -> ExtractionResult:
        """执行完整的多智能体关系抽取主流程。"""
        logger.info("开始多智能体关系抽取，文档: %s", document_id)
        
        try:
            # Planner 阶段：任务规划
            planner_decision = await self.run_planner_agent(chunks)
            logger.info("Planner 阶段完成，规划关系类型: %d 种", 
                       len(planner_decision.metadata.get("suggested_relations", [])))
            
            # Extractor 阶段：候选抽取
            extractor_decision = await self.run_extractor_agent(chunks, planner_decision)
            logger.info("Extractor 阶段完成，生成候选关系: %d 个", 
                       len(extractor_decision.accepted_relations))
            
            # Critic 阶段：批判审查
            critic_decision = await self.run_critic_agent(chunks, extractor_decision)
            logger.info("Critic 阶段完成，驳回关系: %d 个", 
                       len(critic_decision.rejected_relations))
            
            # Judge 阶段：最终裁决
            final_result = await self.run_judge_agent(
                chunks,
                extractor_decision,
                critic_decision,
                target_schemas=target_schemas,
            )
            logger.info("Judge 阶段完成，最终关系: %d 个，实体: %d 个", 
                       len(final_result.relations), len(final_result.entities))
            
            return final_result
            
        except Exception as e:
            logger.error("多智能体关系抽取失败: %s", str(e), exc_info=True)
            raise

    async def run_planner_agent(self, chunks: Sequence[CleanedTextChunk]) -> AgentDecision:
        """执行 Planner Agent 的任务规划阶段。"""
        messages = await self.build_planner_messages(chunks)
        
        response = await self.qwen_client.chat(messages, temperature=0.1)

        planner_data = self._extract_json_from_response(response, "Planner")
        
        return AgentDecision(
            agent_role="planner",
            rationale=planner_data.get("rationale", ""),
            accepted_relations=[],
            rejected_relations=[],
            metadata=planner_data
        )

    async def run_extractor_agent(
        self,
        chunks: Sequence[CleanedTextChunk],
        planner_context: AgentDecision,
    ) -> AgentDecision:
        """执行 Extractor Agent 的候选抽取阶段。"""
        messages = await self.build_extractor_messages(chunks, planner_context)
        
        response = await self.qwen_client.chat(messages, temperature=0.3)

        extractor_data = self._extract_json_from_response(response, "Extractor")
        
        return AgentDecision(
            agent_role="extractor",
            rationale=extractor_data.get("rationale", ""),
            # 加上这行列表推导式，把大模型给的每一个字典都转成 JSON 字符串
            accepted_relations=[json.dumps(rel, ensure_ascii=False) for rel in extractor_data.get("candidate_relations", [])],
            rejected_relations=[],
            metadata=extractor_data
        )

    async def run_critic_agent(
        self,
        chunks: Sequence[CleanedTextChunk],
        extractor_context: AgentDecision,
    ) -> AgentDecision:
        """执行 Critic Agent 的批判与降噪阶段。"""
        messages = await self.build_critic_messages(chunks, extractor_context)
        
        response = await self.qwen_client.chat(messages, temperature=0.2)

        critic_data = self._extract_json_from_response(response, "Critic")
        
        # 【强制清洗 1】: 提取 accepted_relations 中的纯字符串 ID
        raw_accepted = critic_data.get("accepted_relations", [])
        cleaned_accepted = []
        for item in raw_accepted:
            if isinstance(item, dict) and "relation_id" in item:
                cleaned_accepted.append(str(item["relation_id"]))
            elif isinstance(item, str):
                cleaned_accepted.append(item)

        # 【强制清洗 2】: 提取 rejected_relations 中的纯字符串 ID
        raw_rejected = critic_data.get("rejected_relations", [])
        cleaned_rejected = []
        for item in raw_rejected:
            if isinstance(item, dict) and "relation_id" in item:
                cleaned_rejected.append(str(item["relation_id"]))
            elif isinstance(item, str):
                cleaned_rejected.append(item)

        # 覆盖原来的脏数据
        critic_data["accepted_relations"] = cleaned_accepted
        critic_data["rejected_relations"] = cleaned_rejected

        return AgentDecision(
            agent_role="critic",
            rationale=critic_data.get("rationale", ""),
            accepted_relations=critic_data.get("accepted_relations", []),
            rejected_relations=critic_data.get("rejected_relations", []),
            metadata=critic_data
        )

    async def run_judge_agent(
        self,
        chunks: Sequence[CleanedTextChunk],
        extractor_context: AgentDecision,
        critic_context: AgentDecision,
        *,
        target_schemas: Sequence[str] | None = None,
    ) -> ExtractionResult:
        """执行 Judge Agent 的最终裁决阶段。"""
        messages = await self.build_judge_messages(
            chunks,
            extractor_context,
            critic_context,
            target_schemas=target_schemas,
        )
        
        response = await self.qwen_client.chat(messages, temperature=0.1)
        
        # 提取 JSON 和 Mermaid 代码
        mermaid_match = re.search(r'```mermaid\s*(.*?)\s*```', response, re.DOTALL)

        judge_data = self._extract_json_from_response(response, "Judge")
        judge_data = self._align_and_clean_judge_output(judge_data, extractor_context)

        document_id = chunks[0].document_id if chunks else ""
        judge_data.setdefault("document_id", document_id)
        judge_data.setdefault("agent_trace", [extractor_context, critic_context])

        mermaid_code = mermaid_match.group(1).strip() if mermaid_match else ""
        if mermaid_code:
            metadata = judge_data.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.setdefault("mermaid_diagram", mermaid_code)
            judge_data["metadata"] = metadata

        return ExtractionResult(**judge_data)

    async def build_planner_messages(self, chunks: Sequence[CleanedTextChunk]) -> List[dict[str, str]]:
        """构建 Planner Agent 的提示消息。"""
        chunk_texts = "\n\n".join([
            f"文本块 {i+1} (ID: {chunk.chunk_id}):\n{chunk.cleaned_text}"
            for i, chunk in enumerate(chunks)
        ])
        
        return [
            {
                "role": "system",
                "content": """你是一名情报分析师（Planner Agent），负责从舆情文本中识别潜在的关系抽取机会。

你的任务：
1. 分析文本主题和核心实体类型
2. 识别可能存在的时序关系模式
3. 标注文本中的歧义点和噪声区域
4. 为后续抽取阶段提供关系类型建议

【语言纪律】：
- 严禁翻译、意译或改写原文中的实体与关系名称。
- `suggested_relations` 中给出的关系类型建议必须优先使用原文中出现过的英文字符串或任务既有英文关系标签。
- 如果无法确定英文关系标签，不要臆造中文关系名。

请以 JSON 格式回复，包含以下字段：
- rationale: 分析 rationale
- suggested_relations: 建议关注的关系类型列表
- key_entities: 核心实体类型识别
- ambiguity_spots: 歧义或噪声文本位置描述
- metadata: 其他元数据"""
            },
            {
                "role": "user",
                "content": f"""请分析以下舆情文本，制定关系抽取计划：

{chunk_texts}

请输出 JSON 格式的分析结果。"""
            }
        ]

    async def build_extractor_messages(self, chunks: Sequence[CleanedTextChunk], planner_context: AgentDecision) -> List[dict[str, str]]:
        """构建 Extractor Agent 的提示消息。"""
        chunk_texts = "\n\n".join([
            f"文本块 {i+1} (ID: {chunk.chunk_id}, 时间表达: {chunk.detected_time_expressions}):\n{chunk.cleaned_text}"
            for i, chunk in enumerate(chunks)
        ])
        
        planner_suggestions = planner_context.metadata.get("suggested_relations", [])
        
        return [
            {
                "role": "system",
                "content": """你是一名信息挖掘专家（Extractor Agent），负责从文本中抽取出带时间的候选关系四元组。

你的任务：
1. 识别文本中的实体提及（人物、组织、地点、事件等）
2. 提取实体之间的时序关系（关注时间属性）
3. 为每个关系标注时间信息（observed_at, valid_from, valid_to）
4. 记录关系证据的文本位置
5. 结合元数据（情感、地域等）丰富关系属性

【三条强制纪律】：
1. [语言纪律]
   - 严禁任何翻译、意译、同义改写或中英互译行为。
   - 所有实体名称（entities 中的 surface_form / canonical_name）必须 100% 使用原文中实际出现过的英文字符串。
   - 所有关系类型（relation_type）必须优先直接使用原文或 `Target Relation Types` 列表中的英文字符串。
   - 如果原文里没有对应英文表述，宁可不抽，也不要自行翻译或创造中文、双语或伪英文名称。
2. [高置信度-封闭抽取]
   - 你会收到一个 `Target Relation Types` 列表。
   - 只要文本证据能够支持，就必须优先从该列表中选择最合适的关系类型进行抽取。
   - 如果使用了 `Target Relation Types` 列表中的关系类型，confidence 必须严格设置为大于 0.8。
3. [低置信度-开放发现]
   - 只有当你发现文本中存在极其关键、但确实无法被 `Target Relation Types` 覆盖的隐藏/演化关系时，才允许自行命名新的英文关系类型。
   - 这类开放发现关系必须使用英文命名，且 confidence 必须严格设置为小于 0.5。
   - 对于任何不在目标列表中的关系，禁止给出大于等于 0.5 的置信度。

【极其重要的时间格式要求】：
- 所有的 observed_at, valid_from, valid_to 必须严格采用 ISO 标准格式（如 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS）。
- 严禁输出“11月19日”、“今年”等自然语言中文！
- 如果文本中只有月和日，请结合当前新闻的发布时间推断年份；如果实在无法确定，请直接填 null！
关系格式要求：
- 头实体 -> 关系类型 -> 尾实体
- 必须包含时间属性
- 必须包含置信度和证据

请以 JSON 格式回复，包含以下字段：
- rationale: 抽取 rationale
- candidate_relations: 候选关系列表，每个关系包含：
  - relation_id: 关系ID
  - head_entity_id: 头实体ID
  - tail_entity_id: 尾实体ID
  - relation_type: 关系类型
  - confidence: 置信度
  - observed_at: 观察时间
  - valid_from: 有效开始时间
  - valid_to: 有效结束时间
  - evidence_chunk_ids: 证据文本块ID列表
  - evidence_texts: 证据文本列表
  - attributes: 额外属性（如情感、地域等）
  - entities: 识别的实体列表
- 最高红线警告：
在输出 entities 列表时，surface_form 必须且只能是该实体在原文中真实出现过的英文名称片段！
绝对禁止将 surface_form 填写为 ent_00x 这种内部 ID，也绝对禁止把英文实体翻译成中文或改写成其他语言。
若原文中实体名称为英文缩写、全称或带标点形式，必须按原文保留。
"""
            },
            {
                "role": "user",
                "content": f"""请从以下文本中抽取时序关系：

{chunk_texts}

Target Relation Types: {planner_suggestions}

请严格执行以下输出策略：
1. 对于命中 `Target Relation Types` 的关系，必须优先抽取，且 confidence > 0.8。
2. 对于不在 `Target Relation Types` 中但你认为极其关键的隐藏关系，可以补充抽取，但关系类型必须用英文命名，且 confidence < 0.5。
3. 所有实体名和关系类型都必须直接保留原文中的英文字符串，禁止翻译。

请输出 JSON 格式的抽取结果。"""
            }
        ]

    async def build_critic_messages(self, chunks: Sequence[CleanedTextChunk], extractor_context: AgentDecision) -> List[dict[str, str]]:
        """构建 Critic Agent 的提示消息。"""
        candidate_relations = json.dumps(extractor_context.accepted_relations, ensure_ascii=False, indent=2)
        
        return [
            {
                "role": "system",
                "content": """你是一名反方审计员（Critic Agent），负责审查候选关系的质量和可靠性。

你的任务：
1. 检查每个关系的证据充分性
2. 识别可能的模型幻觉和伪关系
3. 发现时间表达冲突和逻辑矛盾
4. 为可疑关系标注置信度惩罚（confidence_penalty）
5. 提供详细的驳回理由

审查标准：
- 证据不足：关系缺乏直接文本证据支持
- 时间冲突：关系的时间属性与上下文矛盾
- 逻辑错误：关系的主客体方向或类型错误
- 幻觉风险：模型可能自行编造的关系

请以 JSON 格式回复，包含以下字段：
- rationale: 审查 rationale
- approved_relations: 通过审查的关系ID列表
- rejected_relations: 驳回的关系ID列表及原因
- confidence_penalties: 置信度惩罚详情
- metadata: 审查元数据"""
            },
            {
                "role": "user",
                "content": f"""请审查以下候选关系：

{candidate_relations}

请严格审查每个关系的可靠性，输出 JSON 格式的审查结果。
请注意：你的目标是纠正明显的错误，而不是过度挑剔。
如果关系在常理上说得通，请尽量予以保留（放入 accepted_relations）。"""
            }
        ]

    async def build_judge_messages(
        self,
        chunks: Sequence[CleanedTextChunk],
        extractor_context: AgentDecision,
        critic_context: AgentDecision,
        *,
        target_schemas: Sequence[str] | None = None,
    ) -> List[dict[str, str]]:
        """构建 Judge Agent 的提示消息。"""
        extractor_relations = json.dumps(extractor_context.accepted_relations, ensure_ascii=False, indent=2)
        critic_review = json.dumps({
            "approved": critic_context.accepted_relations,
            "rejected": critic_context.rejected_relations,
            "rationale": critic_context.rationale
        }, ensure_ascii=False, indent=2)
        schema_list = list(target_schemas or [])
        schema_text = json.dumps(schema_list, ensure_ascii=False, indent=2)
        
        return [
            {
                "role": "system",
                "content": """你是一个严格的图谱本体对齐裁决者 (Ontology Alignment Judge)。

你的任务：
1. 综合 Extractor 的候选关系和 Critic 的审查意见
2. 将 Extractor 产生的原始自然语言关系名 (relation_type) 归一化映射到给定的【标准关系类别库】(Target Schemas)
3. 对映射后的关系重新裁决置信度，并确保输出关系的 relation_type 尽可能落在标准库中
4. 生成 Mermaid 格式的知识图谱可视化代码
5. 确保输出格式符合 Pydantic 模型要求

【本体映射核心指令】：
1. Extractor 提取了候选关系及其原始关系名称（可能是开放域自然语言，例如 "participated_in"）。
2. 你必须对比给定的【标准关系类别库】(Target Schemas)：
   - 如果 Extractor 的 relation_type 在语义上与标准库中的某项等价或高度相关（例如 "participated_in" 与 "participant" 或 "conflict" 等），必须强制将 relation_type 映射为标准库中的英文词条。
   - 映射时必须优先选择最贴近的标准词条，禁止随意创造不在标准库中的新 relation_type。
   - 若出现多个可能映射，请选择最保守、最接近证据文本语义的一项。
3. 如果语义完全不沾边：
   - 允许保留原始 relation_type，但必须将 confidence 降级为小于 0.5。
   - 且不得将此类关系伪装成标准库关系。

【语言纪律】：
- 禁止任何翻译行为。实体与关系类型必须使用英文字符串。
- 若候选关系/实体存在中文、翻译或臆造痕迹，应优先剔除或纠正。

【极其重要的时间格式要求】：
- JSON 中的任何时间字段必须是标准的 YYYY-MM-DD 格式，遇到诸如“11月19日”这样的中文必须纠正或设为 null！

输出要求：
- 必须包含完整的 JSON 数据结构
- 必须包含 Mermaid 图谱代码（graph TD 格式）
- 实体和关系必须包含所有必需字段
- Mermaid 图谱要显示时间属性和关系类型

请以以下格式回复：
```json
{{
  "entities": [...],
  "relations": [...],
  "metadata": {{
    "judge_rationale": "最终裁决理由"
  }}
}}
```

```mermaid
graph TD
  实体1[实体1] -->|关系类型| 实体2[实体2]
  ...
```"""
            },
            {
                "role": "user",
                "content": f"""标准关系类别库 (Target Schemas)：
{schema_text}

请基于以下信息生成最终知识图谱，并严格执行本体映射：

Extractor 候选关系：
{extractor_relations}

Critic 审查意见：
{critic_review}

请输出包含 JSON 和 Mermaid 代码的完整回复。"""
            }
        ]

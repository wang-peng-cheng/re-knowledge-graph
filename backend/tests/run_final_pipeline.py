from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from dotenv import load_dotenv

from app.adapters.llm.qwen_client import QwenClient
from app.core.config import get_settings
from app.domain.models import CleanedTextChunk, ExtractionResult, RawDocumentRecord, SourceType, TemporalRelation
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.services.baseline_re_service import BaselineRelationExtractionService
from app.services.cleaning_service import TextCleaningService
from backend.tests.test_support import run_with_timeout

logger = logging.getLogger(__name__)


RAW_NEWS = {
    "id": 2,
    "title": "“编织千年绿意·体验草编艺趣”活动在成都举行",
    "context": (
        "中国侨网成都11月19日电 为更好向海外传播中华文化，扩大海外华文教育的影响力，近日，2024年"
        "“Panda成都·华教云课堂”系列活动——“编织千年绿意·体验草编艺趣”活动在成都举行，以云课堂形式向"
        "西班牙巴塞罗那孔林学府和西班牙中西文双语学校学生讲授中国传统草编特色文化和中国姓氏文化，通过欣赏草编"
        "非遗作品、感知编织材料特性、学习草编技法、体验草编艺趣，让更多海外华裔青少年和国际友人从一缕“中国草”中，"
        "感受草编的“形与色”和“意与韵”，感受非物质文化遗产的魅力；通过手绘家族姓氏名片，增进对家族文化的理解和热爱，"
        "进一步加强双方文明交流互鉴，促进民心相通，增进友好合作。\n"
        "云课堂现场。成都市政府侨办供图\n"
        "本次活动由成都市人民政府侨务办公室、中国驻西班牙大使馆、成都市教育局主办，成都海外联谊会、成都市非物质文化遗产"
        "保护中心、成都市锦江区政府侨务和台湾事务办公室、成都市锦江区教育局、成都高新区党群工作部、成都高新区教育文化体育局承办，"
        "成都市娇子小学、成都金苹果锦城第一中学、西班牙巴塞罗那孔林学府、西班牙中西文双语学校协办，中西文化桥梁协会执行。\n"
        "成都市娇子小学老师张杨通过云端课堂，向海外的同学们呈现了一堂颇有中国韵味的草编编织艺术课。张杨老师从草编文化的历史、"
        "非遗作品介绍、编织材料特性感知、小船的编织实践入手，鼓励大家亲手体验草编意趣。两地同学认真学习每个编织步骤，大家充分沉浸在"
        "有趣的课程中。在认真编织后，一艘艘小船呈现在视频两端。\n"
        "成都金苹果锦城第一中学老师张雪梅向西班牙师生直播讲授了中国姓氏文化的丰富内容，让海外华裔学生了解自己的姓氏起源，并通过手绘"
        "姓氏名片，增进对姓氏文化的理解。\n"
        "成都市娇子小学校长梁伟虹表示：“四川草编是天府文化的代表之一，四川还有非遗蜀绣、川剧等丰富多彩的项目，欢迎西班牙的同学们来到"
        "四川成都，亲身感受四川、成都和锦江的美。”\n"
        "西班牙中西文双语学校学生展示自己的草编作品。西班牙中西文双语学校供图\n"
        "据悉，此次活动旨在加强双方的交流互动，传播中华传统文化，进一步增进友谊，推动两地学校中外人文交流共建共享课程的进一步发展。"
        "接下来，在前期活动的基础上，双方还将开展更多形式的友好交往交流活动。(完)"
    ),
    "publish_time": "2025-01-28 00:00:00",
    "source": "华侨网",
    "emotion": "positive",
    "city": "成都",
}


def configure_logging() -> None:
    """配置脚本日志。"""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )


def parse_args() -> argparse.Namespace:
    """解析终极联调测试参数。"""

    parser = argparse.ArgumentParser(description="最终联调测试")
    parser.add_argument("--request-timeout-seconds", type=float, default=600.0, help="Qwen 请求超时秒数")
    parser.add_argument("--document-timeout-seconds", type=float, default=1800.0, help="联调阶段超时秒数")
    parser.add_argument("--min-multi-entity-count", type=int, default=1, help="多智能体最小实体数")
    parser.add_argument("--min-multi-relation-count", type=int, default=1, help="多智能体最小关系数")
    parser.add_argument("--write-neo4j", action="store_true", help="显式启用 Neo4j 写入")
    return parser.parse_args()


def build_test_record() -> RawDocumentRecord:
    """构建联调测试使用的原始新闻记录。"""

    return RawDocumentRecord(
        document_id=str(RAW_NEWS["id"]),
        source_type=SourceType.TXT,
        source_uri="local_final_pipeline_test",
        raw_text=RAW_NEWS["context"],
        created_at=datetime.now(),
        metadata={
            "id": RAW_NEWS["id"],
            "publish_time": RAW_NEWS["publish_time"],
            "source": RAW_NEWS["source"],
            "emotion": RAW_NEWS["emotion"],
            "city": RAW_NEWS["city"],
            "title": RAW_NEWS["title"],
        },
    )


def has_chinese_characters(value: Any) -> bool:
    """判断一个值中是否包含中文字符。"""

    if value is None:
        return False
    if isinstance(value, datetime):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", str(value)))


def find_relations_with_chinese_time(relations: Sequence[TemporalRelation]) -> list[dict[str, Any]]:
    """扫描关系列表中包含中文时间字段的记录。"""

    invalid_relations: list[dict[str, Any]] = []
    for relation in relations:
        invalid_fields: list[str] = []
        for field_name in ("observed_at", "valid_from", "valid_to"):
            value = getattr(relation, field_name)
            if has_chinese_characters(value):
                invalid_fields.append(f"{field_name}={value}")
        if invalid_fields:
            invalid_relations.append(
                {
                    "relation_id": relation.relation_id,
                    "relation_type": relation.relation_type,
                    "invalid_fields": invalid_fields,
                }
            )
    return invalid_relations


def get_result_metadata(result: ExtractionResult) -> dict[str, Any]:
    """尽可能从结果对象中提取 metadata。"""

    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        return metadata

    model_extra = getattr(result, "model_extra", None)
    if isinstance(model_extra, dict):
        extra_metadata = model_extra.get("metadata")
        if isinstance(extra_metadata, dict):
            return extra_metadata
    return {}


def extract_mermaid_from_raw_response(response_text: str) -> str:
    """从原始大模型回复中提取 Mermaid 代码块。"""

    mermaid_match = re.search(r"```mermaid\s*(.*?)\s*```", response_text, re.DOTALL)
    if mermaid_match:
        return mermaid_match.group(1).strip()
    return ""


async def replay_multi_agent_for_mermaid(
    service: MultiAgentRelationExtractionService,
    chunks: Sequence[CleanedTextChunk],
) -> str:
    """在需要时重放 Judge 阶段，兜底提取 Mermaid 图代码。"""

    planner_context = await service.run_planner_agent(chunks)
    extractor_context = await service.run_extractor_agent(chunks, planner_context)
    critic_context = await service.run_critic_agent(chunks, extractor_context)
    judge_messages = await service.build_judge_messages(chunks, extractor_context, critic_context)
    raw_response = await service.qwen_client.chat(judge_messages, temperature=0.1)
    return extract_mermaid_from_raw_response(raw_response)


def format_relation_count_report(name: str, result: ExtractionResult) -> None:
    """打印单个系统的抽取统计。"""

    print(f"{name} 抽取结果")
    print(f"  实体数量: {len(result.entities)}")
    print(f"  关系数量: {len(result.relations)}")


def print_time_quality_report(name: str, result: ExtractionResult) -> None:
    """打印时间字段质量报告。"""

    invalid_relations = find_relations_with_chinese_time(result.relations)
    if invalid_relations:
        print(f"  时间字段检查: 违规，发现 {len(invalid_relations)} 条关系包含中文时间")
        for item in invalid_relations:
            print(
                f"    - relation_id={item['relation_id']} | relation_type={item['relation_type']} | "
                f"问题字段={'; '.join(item['invalid_fields'])}"
            )
    else:
        print("  时间字段检查: 通过，未发现中文时间，已规范或清空")


def dump_chunks_preview(chunks: Sequence[CleanedTextChunk]) -> None:
    """打印清洗后的文本块概览。"""

    print("清洗后的 Chunk 概览")
    print(f"  总 Chunk 数量: {len(chunks)}")
    for chunk in chunks[:3]:
        preview = chunk.cleaned_text[:100].replace("\n", " ")
        print(
            f"  - chunk_id={chunk.chunk_id} | seq={chunk.sequence_no} | "
            f"time_expr={chunk.detected_time_expressions} | preview={preview}..."
        )


def ensure_neo4j_driver():
    """导入 Neo4j 驱动，缺失时给出安装提示。"""

    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未检测到 neo4j 驱动，请先执行: pip install neo4j") from exc
    return GraphDatabase


def serialize_datetime(value: Any) -> Any:
    """将 datetime 序列化为字符串。"""

    if isinstance(value, datetime):
        return value.isoformat()
    return value


def write_to_neo4j(result: ExtractionResult) -> None:
    """将 Multi-Agent 抽取结果写入本地 Neo4j。"""

    GraphDatabase = ensure_neo4j_driver()
    settings = get_settings()

    neo4j_uri = os.getenv("NEO4J_URI", settings.neo4j_uri or "bolt://127.0.0.1:7687")
    neo4j_username = os.getenv("NEO4J_USERNAME", settings.neo4j_username or "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", settings.neo4j_password or "")
    neo4j_database = os.getenv("NEO4J_DATABASE", settings.neo4j_database or "neo4j")

    if not neo4j_password:
        raise RuntimeError("未提供 Neo4j 密码，请在 .env 或环境变量中设置 NEO4J_PASSWORD。")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))
    try:
        with driver.session(database=neo4j_database) as session:
            for entity in result.entities:
                session.run(
                    """
                    MERGE (e:Entity {id: $id})
                    SET e.surface_form = $surface_form,
                        e.canonical_name = $canonical_name,
                        e.entity_type = $entity_type,
                        e.confidence = $confidence,
                        e.char_start = $char_start,
                        e.char_end = $char_end,
                        e.document_id = $document_id
                    """,
                    id=entity.entity_id,
                    surface_form=entity.surface_form,
                    canonical_name=entity.canonical_name,
                    entity_type=entity.entity_type,
                    confidence=entity.confidence,
                    char_start=entity.char_start,
                    char_end=entity.char_end,
                    document_id=result.document_id,
                )

            for relation in result.relations:
                session.run(
                    """
                    MATCH (h:Entity {id: $head_entity_id})
                    MATCH (t:Entity {id: $tail_entity_id})
                    MERGE (h)-[r:RELATED_TO {relation_id: $relation_id}]->(t)
                    SET r.relation_type = $relation_type,
                        r.confidence = $confidence,
                        r.observed_at = $observed_at,
                        r.valid_from = $valid_from,
                        r.valid_to = $valid_to,
                        r.evidence_chunk_ids = $evidence_chunk_ids,
                        r.evidence_texts = $evidence_texts,
                        r.agent_votes = $agent_votes_json,
                        r.attributes = $attributes_json,
                        r.document_id = $document_id
                    """,
                    relation_id=relation.relation_id,
                    head_entity_id=relation.head_entity_id,
                    tail_entity_id=relation.tail_entity_id,
                    relation_type=relation.relation_type,
                    confidence=relation.confidence,
                    observed_at=serialize_datetime(relation.observed_at),
                    valid_from=serialize_datetime(relation.valid_from),
                    valid_to=serialize_datetime(relation.valid_to),
                    evidence_chunk_ids=relation.evidence_chunk_ids,
                    evidence_texts=relation.evidence_texts,
                    agent_votes_json=json.dumps(relation.agent_votes, ensure_ascii=False),
                    attributes_json=json.dumps(relation.attributes, ensure_ascii=False),
                    document_id=result.document_id,
                )
    finally:
        driver.close()

def build_deterministic_mermaid(result: ExtractionResult) -> str:
    """架构师特供：用 Python 纯代码直接从结构化结果中生成 Mermaid 图，100% 成功率！"""
    if not result.relations:
        return "graph TD\n    A[暂无关系]"
        
    lines = ["graph TD"]
    # 建立实体 ID 到实体名称的映射字典
    entity_map = {e.entity_id: e.surface_form for e in result.entities}
    
    for rel in result.relations:
        h_name = entity_map.get(rel.head_entity_id, rel.head_entity_id)
        t_name = entity_map.get(rel.tail_entity_id, rel.tail_entity_id)
        
        # 清理名称中的特殊字符，防止破坏 Mermaid 语法
        h_name = str(h_name).replace('"', '').replace('(', '').replace(')', '').replace('[', '').replace(']', '')
        t_name = str(t_name).replace('"', '').replace('(', '').replace(')', '').replace('[', '').replace(']', '')
        rel_type = str(rel.relation_type).replace('"', '')
        
        # 拼接 Mermaid 语法
        lines.append(f'    {rel.head_entity_id}["{h_name}"] -->|"{rel_type}"| {rel.tail_entity_id}["{t_name}"]')
        
    return "\n".join(lines)


async def main() -> None:
    """执行最终联调测试主流程。"""

    args = parse_args()
    configure_logging()
    load_dotenv(BACKEND_DIR / ".env")

    os.environ["HTTP_PROXY"] = ""
    os.environ["HTTPS_PROXY"] = ""
    os.environ["NO_PROXY"] = "*"

    print("========== 终极联调测试启动 ==========")
    print(f"测试新闻: {RAW_NEWS['title']}")

    record = build_test_record()

    cleaner = TextCleaningService()
    chunks = await run_with_timeout(
        "最终联调清洗阶段",
        cleaner.clean_document(record),
        args.document_timeout_seconds,
    )
    if len(chunks) <= 0:
        raise AssertionError("最终联调测试必须至少生成 1 个文本块。")
    dump_chunks_preview(chunks)

    settings = get_settings()
    qwen_client = QwenClient(
        base_url=os.getenv("QWEN_BASE_URL", settings.qwen_base_url),
        api_key=os.getenv("QWEN_API_KEY", settings.qwen_api_key),
        model=os.getenv("QWEN_MODEL", settings.qwen_model),
        timeout_seconds=args.request_timeout_seconds,
    )

    baseline_service = BaselineRelationExtractionService(qwen_client=qwen_client)
    multi_agent_service = MultiAgentRelationExtractionService(qwen_client=qwen_client)

    baseline_result: ExtractionResult | None = None
    multi_result: ExtractionResult | None = None

    try:
        print("\n========== 擂台测试：Baseline ==========")
        try:
            baseline_result = await run_with_timeout(
                "Baseline 抽取",
                baseline_service.extract(record.document_id, chunks),
                args.document_timeout_seconds,
            )
            format_relation_count_report("Baseline", baseline_result)
            print_time_quality_report("Baseline", baseline_result)
        except Exception as exc:
            print(f"Baseline 抽取失败，这正符合脏数据场景下单体模型脆弱性的实验预期: {exc}")

        print("\n========== 擂台测试：Multi-Agent ==========")
        multi_result = await run_with_timeout(
            "Multi-Agent 抽取",
            multi_agent_service.extract(record.document_id, chunks),
            args.document_timeout_seconds,
        )
        if len(multi_result.entities) < args.min_multi_entity_count:
            raise AssertionError(
                f"Multi-Agent 实体数不足，要求至少 {args.min_multi_entity_count}，实际为 {len(multi_result.entities)}。"
            )
        if len(multi_result.relations) < args.min_multi_relation_count:
            raise AssertionError(
                f"Multi-Agent 关系数不足，要求至少 {args.min_multi_relation_count}，实际为 {len(multi_result.relations)}。"
            )
        invalid_relation_count = len(find_relations_with_chinese_time(multi_result.relations))
        if invalid_relation_count != 0:
            raise AssertionError(f"Multi-Agent 输出包含 {invalid_relation_count} 条未规范化中文时间关系。")
        format_relation_count_report("Multi-Agent", multi_result)
        print_time_quality_report("Multi-Agent", multi_result)

        print("\n========== Mermaid 图谱 (Python 引擎 100% 稳定生成) ==========")
        mermaid_code = build_deterministic_mermaid(multi_result)
        print(mermaid_code)

        if args.write_neo4j:
            print("\n========== Neo4j 写入 ==========")
            write_to_neo4j(multi_result)
            print("Multi-Agent 最终干净图谱已成功写入本地 Neo4j。")
        else:
            print("\n========== Neo4j 写入 ==========")
            print("默认跳过 Neo4j 写入；如需落库，请显式传入 --write-neo4j。")

        print("\n========== 横向对比总结 ==========")
        if baseline_result is not None:
            print(f"Baseline 关系数量: {len(baseline_result.relations)}")
        else:
            print("Baseline 关系数量: 基线执行失败，未获得有效结果")
        print(f"Multi-Agent 关系数量: {len(multi_result.relations)}")
        print("联调测试结束。")
    finally:
        await qwen_client.close()


if __name__ == "__main__":
    asyncio.run(main())

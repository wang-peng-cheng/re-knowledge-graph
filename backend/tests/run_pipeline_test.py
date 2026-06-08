from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
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
from app.domain.models import RawDocumentRecord, SourceType
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.services.cleaning_service import TextCleaningService
from backend.tests.test_support import run_with_timeout

load_dotenv(BACKEND_DIR / ".env")


def parse_args() -> argparse.Namespace:
    """解析端到端抽取测试参数。"""

    parser = argparse.ArgumentParser(description="端到端抽取测试流水线")
    parser.add_argument("--request-timeout-seconds", type=float, default=600.0, help="Qwen 请求超时秒数")
    parser.add_argument("--document-timeout-seconds", type=float, default=1800.0, help="端到端抽取超时秒数")
    parser.add_argument("--min-entity-count", type=int, default=1, help="最小实体数断言")
    parser.add_argument("--min-relation-count", type=int, default=1, help="最小关系数断言")
    return parser.parse_args()


async def main() -> None:
    """执行端到端抽取测试流水线。"""

    args = parse_args()
    print("启动端到端抽取测试流水线...")

    raw_json = {
        "id": 2,
        "title": "“编织千年绿意·体验草编艺趣”活动在成都举行",
        "context": "中国侨网成都11月19日电 为更好向海外传播中华文化，扩大海外华文教育的影响力，近日，2024年“Panda成都·华教云课堂”系列活动——“编织千年绿意·体验草编艺趣”活动在成都举行，以云课堂形式向西班牙巴塞罗那孔林学府和西班牙中西文双语学校学生讲授中国传统草编特色文化和中国姓氏文化，通过欣赏草编非遗作品、感知编织材料特性、学习草编技法、体验草编艺趣，让更多海外华裔青少年和国际友人从一缕“中国草”中，感受草编的“形与色”和“意与韵”，感受非物质文化遗产的魅力；通过手绘家族姓氏名片，增进对家族文化的理解和热爱，进一步加强双方文明交流互鉴，促进民心相通，增进友好合作。\n云课堂现场。成都市政府侨办供图\n本次活动由成都市人民政府侨务办公室、中国驻西班牙大使馆、成都市教育局主办，成都海外联谊会、成都市非物质文化遗产保护中心、成都市锦江区政府侨务和台湾事务办公室、成都市锦江区教育局、成都高新区党群工作部、成都高新区教育文化体育局承办，成都市娇子小学、成都金苹果锦城第一中学、西班牙巴塞罗那孔林学府、西班牙中西文双语学校协办，中西文化桥梁协会执行。\n成都市娇子小学老师张杨通过云端课堂，向海外的同学们呈现了一堂颇有中国韵味的草编编织艺术课。张杨老师从草编文化的历史、非遗作品介绍、编织材料特性感知、小船的编织实践入手，鼓励大家亲手体验草编意趣。两地同学认真学习每个编织步骤，大家充分沉浸在有趣的课程中。在认真编织后，一艘艘小船呈现在视频两端。\n成都金苹果锦城第一中学老师张雪梅向西班牙师生直播讲授了中国姓氏文化的丰富内容，让海外华裔学生了解自己的姓氏起源，并通过手绘姓氏名片，增进对姓氏文化的理解。\n成都市娇子小学校长梁伟虹表示：“四川草编是天府文化的代表之一，四川还有非遗蜀绣、川剧等丰富多彩的项目，欢迎西班牙的同学们来到四川成都，亲身感受四川、成都和锦江的美。”\n西班牙中西文双语学校学生展示自己的草编作品。西班牙中西文双语学校供图\n据悉，此次活动旨在加强双方的交流互动，传播中华传统文化，进一步增进友谊，推动两地学校中外人文交流共建共享课程的进一步发展。接下来，在前期活动的基础上，双方还将开展更多形式的友好交往交流活动。(完)",
        "publish_time": "2025-01-28 00:00:00",
        "source": "华侨网",
        "emotion": "positive",
        "city": "成都",
    }

    doc_record = RawDocumentRecord(
        document_id=str(raw_json["id"]),
        source_type=SourceType.TXT,
        source_uri="local_test",
        raw_text=raw_json["context"],
        created_at=datetime.now(),
        metadata={
            "publish_time": raw_json["publish_time"],
            "source": raw_json["source"],
            "emotion": raw_json["emotion"],
            "city": raw_json["city"],
        },
    )

    cleaner = TextCleaningService()
    chunks = await run_with_timeout(
        "清洗阶段",
        cleaner.clean_document(doc_record),
        args.document_timeout_seconds,
    )
    if len(chunks) <= 0:
        raise AssertionError("清洗阶段必须产出至少 1 个文本块。")
    print(f"清洗完成，共切分为 {len(chunks)} 个文本块。")

    base_url = os.getenv("QWEN_BASE_URL", "http://10.109.119.220:11434/v1")
    api_key = os.getenv("QWEN_API_KEY", "sk-123456")
    model_name = os.getenv("QWEN_MODEL", "qwen3:8b")
    qwen_client = QwenClient(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        timeout_seconds=args.request_timeout_seconds,
    )
    re_service = MultiAgentRelationExtractionService(qwen_client)

    try:
        extraction_result = await run_with_timeout(
            "多智能体抽取阶段",
            re_service.extract(doc_record.document_id, chunks),
            args.document_timeout_seconds,
        )
        entity_count = len(extraction_result.entities)
        relation_count = len(extraction_result.relations)
        if entity_count < args.min_entity_count:
            raise AssertionError(
                f"实体数量不足，要求至少 {args.min_entity_count}，实际为 {entity_count}。"
            )
        if relation_count < args.min_relation_count:
            raise AssertionError(
                f"关系数量不足，要求至少 {args.min_relation_count}，实际为 {relation_count}。"
            )

        mermaid_code = extraction_result.metadata.get("mermaid_diagram") if extraction_result.metadata else ""
        print("\n抽取成功。")
        print("=" * 50)
        print(f"实体数量: {entity_count}")
        print(f"关系数量: {relation_count}")
        print("-" * 40)
        if mermaid_code:
            print(mermaid_code)
        else:
            print(extraction_result.model_dump_json(indent=2))
        print("-" * 40)
    finally:
        await qwen_client.close()


if __name__ == "__main__":
    asyncio.run(main())

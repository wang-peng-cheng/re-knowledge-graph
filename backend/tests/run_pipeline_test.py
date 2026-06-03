import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# 禁用代理，防止 502
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

from app.adapters.llm.qwen_client import QwenClient
from app.services.cleaning_service import TextCleaningService
from app.services.agentic_re_service import MultiAgentRelationExtractionService
from app.domain.models import RawDocumentRecord, SourceType

load_dotenv()

async def main():
    print("🚀 启动端到端抽取测试流水线...")
    
    # 1. 准备测试数据 (提取自你之前的截图)
    raw_json = {
        "id": 2, 
        "title": "“编织千年绿意·体验草编艺趣”活动在成都举行", 
        "context": "中国侨网成都11月19日电 为更好向海外传播中华文化，扩大海外华文教育的影响力，近日，2024年“Panda成都·华教云课堂”系列活动——“编织千年绿意·体验草编艺趣”活动在成都举行，以云课堂形式向西班牙巴塞罗那孔林学府和西班牙中西文双语学校学生讲授中国传统草编特色文化和中国姓氏文化，通过欣赏草编非遗作品、感知编织材料特性、学习草编技法、体验草编艺趣，让更多海外华裔青少年和国际友人从一缕“中国草”中，感受草编的“形与色”和“意与韵”，感受非物质文化遗产的魅力；通过手绘家族姓氏名片，增进对家族文化的理解和热爱，进一步加强双方文明交流互鉴，促进民心相通，增进友好合作。\n云课堂现场。成都市政府侨办供图\n本次活动由成都市人民政府侨务办公室、中国驻西班牙大使馆、成都市教育局主办，成都海外联谊会、成都市非物质文化遗产保护中心、成都市锦江区政府侨务和台湾事务办公室、成都市锦江区教育局、成都高新区党群工作部、成都高新区教育文化体育局承办，成都市娇子小学、成都金苹果锦城第一中学、西班牙巴塞罗那孔林学府、西班牙中西文双语学校协办，中西文化桥梁协会执行。\n成都市娇子小学老师张杨通过云端课堂，向海外的同学们呈现了一堂颇有中国韵味的草编编织艺术课。张杨老师从草编文化的历史、非遗作品介绍、编织材料特性感知、小船的编织实践入手，鼓励大家亲手体验草编意趣。两地同学认真学习每个编织步骤，大家充分沉浸在有趣的课程中。在认真编织后，一艘艘小船呈现在视频两端。\n成都金苹果锦城第一中学老师张雪梅向西班牙师生直播讲授了中国姓氏文化的丰富内容，让海外华裔学生了解自己的姓氏起源，并通过手绘姓氏名片，增进对姓氏文化的理解。\n成都市娇子小学校长梁伟虹表示：“四川草编是天府文化的代表之一，四川还有非遗蜀绣、川剧等丰富多彩的项目，欢迎西班牙的同学们来到四川成都，亲身感受四川、成都和锦江的美。”\n西班牙中西文双语学校学生展示自己的草编作品。西班牙中西文双语学校供图\n据悉，此次活动旨在加强双方的交流互动，传播中华传统文化，进一步增进友谊，推动两地学校中外人文交流共建共享课程的进一步发展。接下来，在前期活动的基础上，双方还将开展更多形式的友好交往交流活动。(完)", 
        "publish_time": "2025-01-28 00:00:00", 
        "source": "华侨网", 
        "emotion": "positive", 
        "city": "成都"
    }

    print("\n📦 步骤 1: 构建 RawDocumentRecord 并挂载 Metadata...")
    doc_record = RawDocumentRecord(
        document_id=str(raw_json["id"]),
        source_type=SourceType.TXT,
        source_uri="local_test",
        raw_text=raw_json["context"],
        created_at=datetime.now(),
        # 这里就是我们强调的“元数据透传”！
        metadata={
            "publish_time": raw_json["publish_time"],
            "source": raw_json["source"],
            "emotion": raw_json["emotion"],
            "city": raw_json["city"]
        }
    )

    print("\n🧹 步骤 2: 执行清洗服务 (Cleaning Service)...")
    cleaner = TextCleaningService()
    # 注意：如果 cleaner 需要参数或者不支持 metadata，可能需要微调，但基于 Trae 的报告，应该是支持的
    try:
        # 这里假设 cleaner.clean_document 是同步方法，如果是异步请加 await
        if asyncio.iscoroutinefunction(cleaner.clean_document):
             chunks = await cleaner.clean_document(doc_record)
        else:
             chunks = cleaner.clean_document(doc_record)
        print(f"✅ 清洗完成，共切分为 {len(chunks)} 个文本块 (Chunk)。")
    except Exception as e:
        print(f"❌ 清洗阶段报错：{e}")
        return

    print("\n🧠 步骤 3: 初始化 Qwen 大模型客户端...")
    base_url = os.getenv("QWEN_BASE_URL", "http://10.109.119.220:11434/v1")
    api_key = os.getenv("QWEN_API_KEY", "sk-123456")
    model_name = os.getenv("QWEN_MODEL", "qwen-relation")
    
    qwen_client = QwenClient(base_url=base_url, api_key=api_key, model=model_name)
    
    print("\n⚖️ 步骤 4: 启动多智能体辩论流水线 (Multi-Agent Debate)...")
    print("   这大概需要 1-3 分钟，因为模型要经历 Planner -> Extractor -> Critic -> Judge 四轮思考...")
    re_service = MultiAgentRelationExtractionService(qwen_client)
    
    try:
        # 调用核心 extract 方法
        extraction_result = await re_service.extract(doc_record.document_id, chunks)
        
        print("\n🎉 抽取圆满成功！最终结果如下：")
        print("="*50)
        # 打印提取到的实体数量和关系数量
        print(f"🔹 提取实体数量: {len(extraction_result.entities)}")
        print(f"🔹 提取关系数量: {len(extraction_result.relations)}")
        
        # 尝试提取 Mermaid 代码 (兼容我们所有的暗号)
        mermaid_code = None
        if hasattr(extraction_result, 'metadata') and extraction_result.metadata:
            mermaid_code = (
                extraction_result.metadata.get('mermaid_diagram') or 
                extraction_result.metadata.get('mermaid_code') or 
                extraction_result.metadata.get('mermaid')
            )
        
        if not mermaid_code and hasattr(extraction_result, 'reasoning_trajectory'):
            # Judge 最后一步的轨迹里可能包含
            trajectory = extraction_result.reasoning_trajectory
            if trajectory and 'mermaid' in str(trajectory).lower():
               mermaid_code = "请在 extraction_result.reasoning_trajectory 中查找 Mermaid 代码"

        print("\n🎨 你的专属 Mermaid 可视化代码：")
        print("-" * 40)
        if mermaid_code:
            print(mermaid_code)
        else:
            print("⚠️ 哎呀，模型好像忘记生成 Mermaid 代码，或者放在了别的地方。")
            print("下面是完整的 JSON 输出，你可以手动查看：")
            print(extraction_result.model_dump_json(indent=2))
        print("-" * 40)
        
    except Exception as e:
         print(f"\n❌ 多智能体抽取阶段报错，请把报错发给导师：\n{e}")
    finally:
        await qwen_client.close()

if __name__ == "__main__":
    asyncio.run(main())
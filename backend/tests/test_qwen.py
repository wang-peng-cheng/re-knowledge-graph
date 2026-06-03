import os
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"  # 强制要求所有请求直连，不经过任何代理

import asyncio
from dotenv import load_dotenv
from app.adapters.llm.qwen_client import QwenClient

# 强制加载本地的 .env 密码本
load_dotenv()

async def main():
    print("🚀 正在初始化 Qwen 客户端...")
    
    # 从环境变量读取配置，如果没读到就用默认值兜底
    base_url = os.getenv("QWEN_BASE_URL", "http://10.109.118.166:11434/v1")
    api_key = os.getenv("QWEN_API_KEY", "sk-123456")
    model_name = os.getenv("QWEN_MODEL", "qwen") # 注意：这里要跟你内网的实际模型名一致
    
    # 适配 DeepSeek 写的标准初始化方式
    client = QwenClient(base_url=base_url, api_key=api_key, model=model_name)
    
    test_messages = [
        {"role": "system", "content": "你是一个严谨的 AI 助手。"},
        {"role": "user", "content": "请用一句话证明你已经连线成功，并报出你的模型名字。"}
    ]
    
    print(f"📡 正在向 {base_url} 发送请求...")
    try:
        # 调用 DeepSeek 写的 chat 方法
        response = await client.chat(test_messages)
        print("\n🎉 连接成功！Qwen 的回复是：")
        print("-" * 40)
        print(response)
        print("-" * 40)
    except Exception as e:
        print(f"\n❌ 连接失败，请检查实验室网络或把报错发给导师：\n{e}")
    finally:
        # 优雅地关闭连接
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
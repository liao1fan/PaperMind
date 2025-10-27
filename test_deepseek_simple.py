"""
简单测试 DeepSeek API 连接
"""

import asyncio
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel, Agent, Runner, set_default_openai_client

load_dotenv()

async def test_deepseek():
    print("测试 DeepSeek API 连接\n")

    # 创建客户端
    client = AsyncOpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )

    print(f"API Key: {os.getenv('DEEPSEEK_API_KEY')[:20]}...")
    print(f"Base URL: https://api.deepseek.com\n")

    # 设置默认客户端
    set_default_openai_client(client, use_for_tracing=False)

    # 创建模型
    model = OpenAIChatCompletionsModel(
        model="deepseek-chat",
        openai_client=client
    )

    print(f"模型对象: {model}\n")

    # 创建 Agent
    agent = Agent(
        name="Test Agent",
        instructions="你是一个测试助手。",
        model=model
    )

    print(f"Agent 创建成功\n")

    # 运行测试
    print("发送测试消息...\n")
    result = await Runner.run(
        starting_agent=agent,
        input="你好，请介绍一下你自己。",
        max_turns=1
    )

    print(f"响应: {result.final_output}\n")
    print("✅ 测试成功！")

if __name__ == "__main__":
    asyncio.run(test_deepseek())

"""
测试 init_model.py 模块

验证：
1. 模型初始化是否成功
2. tool_model 和 reason_model 是否可以在 Agent 中使用
3. Agent 是否能正常运行
"""

import asyncio
from agents import Agent, Runner
from init_model import init_models, get_tool_model, get_reason_model


async def test_tool_model():
    """测试轻量化工具模型"""
    print("\n" + "="*70)
    print("测试 Tool Model (轻量化模型)")
    print("="*70 + "\n")

    # 创建使用 tool_model 的 Agent
    agent = Agent(
        name="Tool Agent",
        instructions="你是一个轻量化助手，请简洁地回答问题。",
        model=get_tool_model()
    )

    # 运行测试
    result = await Runner.run(
        starting_agent=agent,
        input="请用一句话介绍你自己。",
        max_turns=1
    )

    print(f"Tool Model 响应: {result.final_output}\n")
    return result


async def test_reason_model():
    """测试复杂推理模型"""
    print("\n" + "="*70)
    print("测试 Reason Model (推理模型)")
    print("="*70 + "\n")

    # 创建使用 reason_model 的 Agent
    agent = Agent(
        name="Reason Agent",
        instructions="你是一个复杂推理助手，请详细分析并回答问题。",
        model=get_reason_model()
    )

    # 运行测试
    result = await Runner.run(
        starting_agent=agent,
        input="请写一首关于人工智能的俳句。",
        max_turns=1
    )

    print(f"Reason Model 响应: {result.final_output}\n")
    return result


async def test_with_tools():
    """测试带工具的 Agent"""
    print("\n" + "="*70)
    print("测试带工具的 Agent")
    print("="*70 + "\n")

    from agents import function_tool
    from typing import Annotated

    @function_tool
    def get_current_time() -> str:
        """获取当前时间"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 创建带工具的 Agent（使用 tool_model）
    agent = Agent(
        name="Tool-enabled Agent",
        instructions="你是一个助手，可以调用工具获取当前时间。",
        model=get_tool_model(),
        tools=[get_current_time]
    )

    # 运行测试
    result = await Runner.run(
        starting_agent=agent,
        input="现在几点了？",
        max_turns=3
    )

    print(f"带工具的 Agent 响应: {result.final_output}\n")
    return result


async def main():
    """主测试函数"""
    print("\n" + "="*70)
    print("🚀 开始测试 init_model.py")
    print("="*70 + "\n")

    # 1. 初始化模型
    print("步骤 1: 初始化模型...\n")
    factory = init_models()

    # 2. 测试 tool_model
    print("\n步骤 2: 测试 tool_model...")
    await test_tool_model()

    # 3. 测试 reason_model
    print("\n步骤 3: 测试 reason_model...")
    await test_reason_model()

    # 4. 测试带工具的 Agent
    print("\n步骤 4: 测试带工具的 Agent...")
    await test_with_tools()

    print("\n" + "="*70)
    print("✅ 所有测试完成！")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

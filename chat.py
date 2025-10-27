#!/usr/bin/env python3
"""
Paper Agent 对话机器人 - 重构版

使用新的架构：
- 主 Agent (paper_agent): 调度、链接识别、定时任务管理
- Sub-Agent (digest_agent): 论文整理（通过 handoff）

功能特点：
- 交互式对话界面
- 支持 MCP 工具调用（创建/管理定时任务）
- 支持 MCP Sampling（定时任务自动触发 Agent 执行）
- 支持多种链接类型（XHS、PDF、arXiv）
- 使用 handoff 机制实现 agent 协作

使用方法:
    python chat_new.py
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import Agent, Runner, set_default_openai_client
from agents.mcp import MCPServerStdio
from agents.tracing import set_tracing_disabled
from mcp.types import CreateMessageResult, TextContent

from paper_agents import paper_agent, init_paper_agents
from init_model import init_models

# 加载环境变量
load_dotenv()

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent


def create_sampling_callback(base_agent):
    """
    创建 MCP Sampling callback

    当 schedule-task-mcp 触发定时任务时，这个 callback 会被调用。
    它会使用基础 Agent（不包含 MCP 工具）来执行任务，避免递归调用。

    Args:
        base_agent: 基础 Agent 实例（包含核心工具，不包含 MCP 工具）

    Returns:
        async function: Sampling callback 函数
    """
    async def sampling_callback(context, params):
        """处理 MCP Sampling 请求"""
        # 从 params.messages 中提取任务描述
        agent_prompt = ""
        for message in params.messages:
            if message.role == "user":
                content = message.content
                if hasattr(content, 'text'):
                    agent_prompt = content.text
                elif hasattr(content, 'type') and content.type == 'text':
                    agent_prompt = content.text if hasattr(content, 'text') else str(content)
                break

        print(f"\n{'='*70}")
        print(f"🔔 定时任务触发！")
        print(f"{'='*70}")
        print(f"📝 任务: {agent_prompt}")
        print(f"🤖 执行中...")

        try:
            # 使用基础 Agent 执行任务（不包含 MCP 工具，避免递归）
            result = await Runner.run(
                starting_agent=base_agent,
                input=agent_prompt,
                max_turns=20  # 增加 turns，因为有 handoff
            )

            response_text = str(result.final_output) if hasattr(result, 'final_output') else str(result)

            print(f"\n✅ 任务执行完成！")
            print(f"结果: {response_text[:300]}...")
            print(f"{'='*70}\n")

            # 返回符合 MCP Sampling 规范的响应
            return CreateMessageResult(
                model=base_agent.model or "gpt-5-mini",
                role="assistant",
                content=TextContent(type="text", text=response_text),
                stopReason="endTurn"
            )

        except Exception as e:
            error_msg = f"执行失败: {str(e)}"
            print(f"\n❌ {error_msg}\n")

            # 即使失败也返回规范的响应
            return CreateMessageResult(
                model=base_agent.model or "gpt-5-mini",
                role="assistant",
                content=TextContent(type="text", text=f"⚠️ {error_msg}"),
                stopReason="endTurn"
            )

    return sampling_callback


class PaperChatBot:
    """Paper 对话机器人"""

    def __init__(self):
        self.mcp_server = None
        self.agent_with_mcp = None
        self.current_agent = None
        self.input_items = []

    async def start(self):
        """启动对话机器人"""
        # 设置代理
        proxy = os.getenv('http_proxy', 'http://127.0.0.1:7891')
        os.environ['http_proxy'] = proxy
        os.environ['https_proxy'] = proxy
        set_tracing_disabled(True)  # 禁用 tracing

        print("\n" + "="*70)
        print("📚 Paper Agent - 论文整理助手（重构版）")
        print("="*70)
        print("\n特性：")
        print("  ✅ 智能链接识别（XHS/PDF/arXiv）")
        print("  ✅ Agent 协作（主Agent调度 + Digest Agent整理）")
        print("  ✅ 定时任务支持（schedule-task-mcp）")
        print("  ✅ MCP Sampling（定时任务自动触发）")
        print("\n正在启动...\n")

        # 初始化模型（会自动设置默认客户端）
        factory = init_models()
        openai_client = factory.get_client()

        # 初始化 agents 全局变量
        init_paper_agents(openai_client)

        # 配置 schedule-task-mcp 环境变量
        schedule_env = {
            "SCHEDULE_TASK_TIMEZONE": os.getenv("SCHEDULE_TASK_TIMEZONE", "Asia/Shanghai"),
            "SCHEDULE_TASK_DB_PATH": os.getenv("SCHEDULE_TASK_DB_PATH", str(PROJECT_ROOT / "data" / "schedule_tasks.db")),
            "SCHEDULE_TASK_SAMPLING_TIMEOUT": os.getenv("SCHEDULE_TASK_SAMPLING_TIMEOUT", "300000"),
        }

        print(f"📂 定时任务数据库: {schedule_env['SCHEDULE_TASK_DB_PATH']}")

        # 创建 sampling callback（使用基础 Agent，不包含 MCP 工具）
        callback = create_sampling_callback(paper_agent)

        # 创建 MCP 服务器列表
        schedule_server = MCPServerStdio(
            name="schedule-task-mcp",
            params={
                "command": "npx",
                "args": ["-y", "schedule-task-mcp"],
                "env": schedule_env,
            },
            sampling_callback=callback,  # ✨ 启用 Sampling 支持
        )

        print(f"🔌 连接 MCP 服务器:")
        print(f"  - schedule-task-mcp (Sampling 已启用)")

        # 使用 async with 连接 MCP 服务器
        async with schedule_server as sched_srv:
            # 导入 digest_agent (从 src/services)
            from src.services.paper_digest import digest_agent, _init_digest_globals

            # ⚠️ 重要：必须重新初始化 digest_agent 的全局变量
            _init_digest_globals(openai_client)

            # 创建带 MCP 工具的主 Agent
            self.agent_with_mcp = Agent(
                name=paper_agent.name,
                instructions=paper_agent.instructions,
                model=paper_agent.model,
                tools=paper_agent.tools,
                handoffs=paper_agent.handoffs,  # ✨ 使用原始 handoff 到 digest_agent
                mcp_servers=[sched_srv],  # 主 Agent 使用 schedule-task-mcp
            )
            self.current_agent = self.agent_with_mcp
            self.input_items = []

            print(f"✅ 主 Agent 已创建: {self.agent_with_mcp.name}")
            print(f"✅ Sub-Agent 已注册: digest_agent (通过 handoff)")
            print(f"\n提示:")
            print(f"  - 输入小红书/PDF/arXiv链接，或直接描述需求")
            print(f"  - 支持定时任务（如：每天早上8点整理 xxx）")
            print(f"  - 输入 'exit' 或 'quit' 退出")
            print("\n" + "="*70 + "\n")

            # 进入对话循环
            await self.chat_loop()

    async def chat_loop(self):
        """对话循环"""
        while True:
            try:
                # 获取用户输入
                user_input = await self.get_user_input()

                # 处理特殊命令
                if user_input.lower() in ['exit', 'quit', 'q', '退出']:
                    print("\n👋 再见！\n")
                    break
                elif not user_input.strip():
                    continue

                # 调用 Agent 处理
                print(f"\n🤖 思考中...\n")
                response = await self.process_message(user_input)

                # 显示响应
                print(f"\n{'─'*70}")
                print(f"🤖 助手:")
                print(f"{'─'*70}\n")
                print(response)
                print(f"\n{'─'*70}\n")

            except KeyboardInterrupt:
                print("\n\n👋 再见！\n")
                break
            except Exception as e:
                print(f"\n❌ 错误: {e}\n")
                import traceback
                traceback.print_exc()

    async def get_user_input(self):
        """获取用户输入（异步方式）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_input)

    def _sync_input(self):
        """同步获取输入"""
        return input("💬 您: ")

    async def process_message(self, message: str):
        """处理用户消息"""
        try:
            # 添加本轮用户消息
            self.input_items.append({"role": "user", "content": message})

            # 使用 Runner 运行带 MCP 工具的 Agent，传入完整上下文
            result = await Runner.run(
                starting_agent=self.current_agent,
                input=self.input_items,
                max_turns=20  # 增加 turns，支持 handoff
            )

            # 更新当前 Agent 和上下文
            self.current_agent = result.last_agent
            self.input_items = result.to_input_list()

            # 提取响应
            response = result.final_output if hasattr(result, 'final_output') else str(result)
            return response

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            return f"抱歉，处理消息时遇到错误: {str(e)}\n\n详细信息:\n{error_detail}"


async def main():
    """主函数"""
    bot = PaperChatBot()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 再见！\n")
        sys.exit(0)

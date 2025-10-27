#!/usr/bin/env python3
"""
Paper Agent 对话机器人

使用新的架构：
- 主 Agent (paper_agent): 调度、链接识别
- Sub-Agent (digest_agent): 论文整理（通过 handoff）

功能特点：
- 交互式对话界面
- 支持多种链接类型（XHS、PDF、arXiv）
- 使用 handoff 机制实现 agent 协作

使用方法:
    python chat.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from agents import Runner
from agents.tracing import set_tracing_disabled

from paper_agents import paper_agent, init_paper_agents
from init_model import init_models

# 加载环境变量
load_dotenv()


class PaperChatBot:
    """Paper 对话机器人"""

    def __init__(self):
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
        print("📚 Paper Agent - 论文整理助手")
        print("="*70)
        print("\n特性：")
        print("  ✅ 智能链接识别（XHS/PDF/arXiv）")
        print("  ✅ Agent 协作（主Agent调度 + Digest Agent整理）")
        print("\n正在启动...\n")

        # 初始化模型（会自动设置默认客户端）
        factory = init_models()
        openai_client = factory.get_client()

        # 初始化 agents 全局变量
        init_paper_agents(openai_client)

        # 导入 digest_agent (从 src/services)
        from src.services.paper_digest import _init_digest_globals

        # ⚠️ 重要：必须重新初始化 digest_agent 的全局变量
        _init_digest_globals(openai_client)

        # 使用基础 paper_agent
        self.current_agent = paper_agent
        self.input_items = []

        print(f"✅ 主 Agent 已创建: {paper_agent.name}")
        print(f"✅ Sub-Agent 已注册: digest_agent (通过 handoff)")
        print(f"\n提示:")
        print(f"  - 输入小红书/PDF/arXiv链接，或直接描述需求")
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

            # 使用 Runner 运行 Agent，传入完整上下文
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

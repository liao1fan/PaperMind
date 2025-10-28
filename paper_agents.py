"""
Paper Agent 定义 - 重构版

主 Agent (paper_agent):
1. 识别链接类型（XHS/PDF/其他）
2. 使用 handoff 转交给 digest_agent 处理论文整理

Sub-Agent (digest_agent):
- 专注于论文下载、解析、整理、保存
"""

import os
import re
from pathlib import Path
from typing import Annotated
import json

from agents import Agent, function_tool, handoff

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 导入 digest_agent (从 src/services)
from src.services.paper_digest import digest_agent, _init_digest_globals

# 导入模型
from init_model import get_tool_model


# ============= 主 Agent 工具 =============

@function_tool
async def identify_link_type(
    url: Annotated[str, "用户提供的URL链接"]
) -> str:
    """
    识别链接类型

    参数:
        url: 用户提供的URL链接

    返回:
        JSON格式的识别结果
    """
    url = url.strip()

    # 识别小红书链接
    xhs_patterns = [
        r'xiaohongshu\.com',
        r'xhslink\.com',
    ]
    for pattern in xhs_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return json.dumps({
                "type": "xiaohongshu",
                "url": url,
                "message": "这是小红书帖子链接，将获取帖子内容并提取论文信息。"
            }, ensure_ascii=False, indent=2)

    # 识别 PDF 链接
    pdf_patterns = [
        r'\.pdf$',
        r'arxiv\.org/pdf',
        r'\.pdf\?',
    ]
    for pattern in pdf_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return json.dumps({
                "type": "pdf",
                "url": url,
                "message": "这是PDF文件链接，将直接下载PDF并分析。"
            }, ensure_ascii=False, indent=2)

    # 识别 arXiv abs 链接
    if re.search(r'arxiv\.org/abs', url, re.IGNORECASE):
        # 转换为 PDF 链接
        arxiv_id = re.search(r'abs/(\d+\.\d+)', url)
        if arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id.group(1)}.pdf"
            return json.dumps({
                "type": "arxiv",
                "url": pdf_url,
                "original_url": url,
                "message": f"这是arXiv论文链接，已转换为PDF链接: {pdf_url}"
            }, ensure_ascii=False, indent=2)

    # 识别学术期刊/会议网站链接
    academic_domains = [
        r'nature\.com',
        r'science\.org',
        r'sciencedirect\.com',
        r'ieee\.org',
        r'acm\.org',
        r'springer\.com',
        r'sciencemag\.org',
        r'pnas\.org',
        r'cell\.com',
        r'aaai\.org',
        r'openreview\.net',
        r'arxiv\.org',  # 其他 arxiv 格式
        r'biorxiv\.org',
        r'medrxiv\.org',
        r'doi\.org',
        r'researchgate\.net',
        r'semanticscholar\.org',
        r'google\.com/scholar',
    ]

    for pattern in academic_domains:
        if re.search(pattern, url, re.IGNORECASE):
            return json.dumps({
                "type": "academic_page",
                "url": url,
                "message": "这是学术期刊/会议网站链接，将尝试从页面中提取PDF链接或使用标题搜索论文。"
            }, ensure_ascii=False, indent=2)

    # 其他链接 - 仍然尝试处理
    return json.dumps({
        "type": "other",
        "url": url,
        "message": "这是其他类型的链接，将尝试提取论文信息并查找PDF。"
    }, ensure_ascii=False, indent=2)


# ============= Agent 定义 =============

# 主 Paper Agent
paper_agent = Agent(
    name="paper_agent",
    instructions="""你是一个专业的研究论文整理助手（Paper Agent）。

你的职责是：

1. **识别链接类型**
   - 使用 identify_link_type 识别用户提供的链接类型
   - 支持的类型：
     * 小红书链接（xiaohongshu）
     * PDF链接（直接的 .pdf 文件）
     * arXiv链接（arxiv.org）
     * 学术期刊/会议网站链接（academic_page）：Nature, Science, IEEE, ACM, Springer 等
     * 其他链接（other）：任何其他链接都会尝试处理

2. **转交给 Digest Agent 处理**
   - 使用 transfer_to_digest_agent 将论文整理任务交给专业的 digest_agent
   - 传递必要的信息：链接类型、URL、任何额外的上下文
   - ⚡ **并行处理**：当用户提供多个链接时，你可以并行调用 transfer_to_digest_agent 处理每个链接，无需等待前一个完成
   - **所有链接类型都应该尝试处理**：即使是 unknown 或 other 类型，也要转交给 digest_agent，让它尝试提取论文信息

⚠️ 重要提示：
- 你只负责识别和调度，不直接处理论文整理
- 论文整理（下载、解析、生成、保存）由 digest_agent 完成
- **不要拒绝任何链接**：即使无法精确识别类型，也要转交给 digest_agent 尝试处理

工作流程示例：

**单个链接**：
用户: "帮我整理这篇论文 https://www.nature.com/articles/xxx"
你:
  1. 调用 identify_link_type -> 识别为学术期刊链接
  2. 调用 transfer_to_digest_agent -> 转交给 digest_agent 处理

**多个链接（并行处理）**：
用户: "帮我整理这三篇论文：链接1、链接2、链接3"
你:
  1. 识别出3个链接
  2. 并行调用 transfer_to_digest_agent 3次（同时处理，不等待）
  3. 告诉用户正在并行处理3篇论文

请保持对话友好、专业。
""",
    model=get_tool_model(),
    tools=[
        identify_link_type,
    ],
    handoffs=[
        handoff(
            agent=digest_agent,
            tool_name_override="transfer_to_digest_agent",
            tool_description_override="""将论文整理任务转交给 Digest Agent。

当需要处理论文（下载PDF、提取信息、生成整理、保存到Notion）时使用此工具。

传递给 digest_agent 的信息应包括：
- 链接类型（xiaohongshu/pdf/arxiv）
- URL 链接
- 任何其他上下文信息

示例输入：
"请帮我整理这篇论文，这是小红书链接：https://www.xiaohongshu.com/explore/xxx"
或
"请处理这个PDF：https://arxiv.org/pdf/2505.10831.pdf，标题是：Creating General User Models from Computer Use"
"""
        )
    ]
)


# 初始化函数（供 chat.py 调用）
def init_paper_agents(openai_client):
    """
    初始化 paper agents 的全局变量

    Args:
        openai_client: OpenAI AsyncOpenAI 客户端
    """
    _init_digest_globals(openai_client)

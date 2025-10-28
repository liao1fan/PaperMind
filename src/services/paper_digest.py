#!/usr/bin/env python3
"""
Digest Agent Core - 论文整理核心 Agent（作为 sub-agent）

功能：
1. 接收多种输入源（XHS URL、PDF URL、PDF 本地路径）
2. 下载 PDF 并读取全文内容
3. 生成结构化论文整理
4. 保存到 Notion 数据库

作为 sub-agent 被主 paper_agent 调用
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated
import json
import httpx
import fitz  # PyMuPDF
import time

from agents import Agent, function_tool, Runner
from openai import AsyncOpenAI
from ..utils.logger import get_logger

# 导入模型
import sys
from pathlib import Path
# 添加项目根目录到 sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from init_model import get_tool_model, get_reason_model

# 初始化日志
logger = get_logger(__name__)

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # spec-paper-notion-agent/
DIGEST_ROOT = Path(__file__).resolve().parent  # src/services/
OUTPUT_DIR = PROJECT_ROOT / "paper_digest" / "outputs"  # 保持输出在原位置
PDF_DIR = PROJECT_ROOT / "paper_digest" / "pdfs"  # 保持PDF在原位置

# 确保目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

# 全局变量
_openai_client = None
_current_paper = {}


def _init_digest_globals(openai_client):
    """初始化全局变量"""
    global _openai_client
    _openai_client = openai_client


@function_tool
async def fetch_xiaohongshu_post(
    post_url: Annotated[str, "小红书帖子的完整URL"]
) -> str:
    """
    获取小红书帖子内容

    参数:
        post_url: 小红书帖子URL

    返回:
        JSON格式的帖子信息（包含 raw_content）
    """
    global _current_paper
    start_time = time.time()

    # 导入 xiaohongshu 服务
    from .xiaohongshu import XiaohongshuClient

    try:
        logger.info("🔍 开始获取小红书帖子")
        client = XiaohongshuClient(
            cookies=os.getenv("XHS_COOKIES"),
            openai_client=_openai_client  # ✨ 传递 OpenAI client 用于 LLM 解析
        )
        post = await client.fetch_post(post_url)

        _current_paper = {
            "post_id": post.post_id,
            "post_url": str(post.post_url),
            "blogger_name": post.blogger_name,
            "raw_content": post.raw_content,
        }

        elapsed = time.time() - start_time
        logger.info(
            "✅ 小红书帖子获取成功",
            post_id=post.post_id,
            content_length=len(post.raw_content),
            elapsed_time=f"{elapsed:.2f}s"
        )

        return json.dumps({
            "success": True,
            "post_id": post.post_id,
            "content": post.raw_content,
            "message": f"✅ 帖子内容获取成功！（耗时 {elapsed:.2f}s）"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 小红书帖子获取失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"获取帖子失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


async def _fetch_arxiv_journal_ref(arxiv_id: str) -> dict:
    """
    从 ArXiv API 获取论文的 journal-ref（实际发表的期刊/会议）

    参数:
        arxiv_id: ArXiv ID（格式如 2410.04618）

    返回:
        包含 journal_ref 和其他元数据的字典
    """
    try:
        import urllib.parse
        import re

        logger.info("🔍 从 ArXiv 查询论文的实际发表信息", arxiv_id=arxiv_id)

        # ArXiv API 查询（使用 HTTPS，支持自动重定向）
        api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"

        proxy = os.getenv('http_proxy')
        mounts = None
        if proxy:
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=proxy),
            }

        async with httpx.AsyncClient(timeout=30.0, mounts=mounts) as client:
            response = await client.get(api_url)
            response.raise_for_status()

            # 解析 XML 响应
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            # 查找论文条目
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('atom:entry', ns)

            if entries:
                entry = entries[0]

                # 获取 journal-ref（发表期刊/会议）
                journal_ref_elem = entry.find('{http://arxiv.org/schemas/atom}journal-ref')
                journal_ref = journal_ref_elem.text if journal_ref_elem is not None else None

                # 获取 comments（也可能包含发表信息，如 "ACL 2025"）
                comments_elem = entry.find('{http://arxiv.org/schemas/atom}comment')
                comments = comments_elem.text if comments_elem is not None else None

                # 获取发布日期
                published_elem = entry.find('atom:published', ns)
                published = published_elem.text if published_elem is not None else None

                # 获取作者
                authors = []
                for author_elem in entry.findall('atom:author', ns):
                    name_elem = author_elem.find('atom:name', ns)
                    if name_elem is not None:
                        authors.append(name_elem.text)

                result = {
                    "journal_ref": journal_ref,
                    "comments": comments,
                    "published_date": published[:10] if published else None,  # 提取日期部分
                    "authors": authors
                }

                # 优先级：journal-ref > comments > 无
                if journal_ref:
                    logger.info(
                        "✅ ArXiv 查询成功，找到实际发表信息（来自 journal-ref）",
                        arxiv_id=arxiv_id,
                        journal_ref=journal_ref[:100],
                        published_date=published[:10] if published else None
                    )
                elif comments:
                    # 从 comments 中提取发表会议/期刊信息
                    logger.info(
                        "✅ ArXiv 查询成功，在 comments 中找到发表信息",
                        arxiv_id=arxiv_id,
                        comments=comments[:100]
                    )
                else:
                    logger.info(
                        "ℹ️ ArXiv 上该论文未记录最终发表信息（可能是预印本）",
                        arxiv_id=arxiv_id
                    )

                return result

        logger.warning(f"⚠️ ArXiv API 未返回论文数据", arxiv_id=arxiv_id)
        return {"journal_ref": None}

    except Exception as e:
        logger.warning(f"⚠️ ArXiv 查询失败: {e}，继续使用 PDF 元数据中的信息")
        return {"journal_ref": None}


@function_tool
async def extract_paper_metadata(
    xiaohongshu_content: Annotated[str, "小红书帖子内容（可选）"] = "",
    pdf_content: Annotated[str, "PDF的文本内容"] = "",
    pdf_metadata: Annotated[str, "PDF的元数据（JSON格式）"] = ""
) -> str:
    """
    从 PDF 和小红书内容中提取所有论文信息（一次 LLM 调用）

    参数:
        xiaohongshu_content: 小红书帖子内容（可选）
        pdf_content: PDF 文本内容
        pdf_metadata: PDF 元数据 (JSON格式)

    返回:
        JSON格式的完整论文信息，包括：
        - title: 论文英文标题
        - authors: 作者列表（数组）
        - publication_date: 发表日期（YYYY-MM-DD）
        - venue: 期刊/会议名称
        - abstract: 摘要
        - affiliations: 机构
        - keywords: 关键词列表（数组）
        - doi: DOI
        - arxiv_id: ArXiv ID
        - project_page: 项目主页
        - other_resources: 其他资源
    """
    global _openai_client, _current_paper
    start_time = time.time()

    try:
        logger.info("📚 开始提取论文元数据（LLM 调用 1/2）")
        prompt = f"""你是论文信息提取专家。请从以下内容中提取完整的论文信息。

# PDF 元数据
{pdf_metadata}

# PDF 内容（前5000字）
{pdf_content[:5000] if pdf_content else "[未提供]"}

# 小红书内容（参考）
{xiaohongshu_content[:2000] if xiaohongshu_content else "[未提供]"}

请提取以下信息，必须返回 JSON 格式：

{{
    "title": "论文英文标题（必填）",
    "authors": ["作者1", "作者2"],
    "publication_date": "YYYY-MM-DD（如果只有年份，使用 YYYY-01-01）",
    "venue": "期刊/会议名称",
    "abstract": "英文摘要",
    "affiliations": "Stanford University; MIT",
    "keywords": ["keyword1", "keyword2", "tag1"],
    "doi": "10.1234/example（如果有）",
    "arxiv_id": "2410.xxxxx（如果是 arXiv 论文）",
    "project_page": "项目主页链接（如果有）",
    "other_resources": "代码仓库、数据集等（可用分号分隔）"
}}

⚠️ 要求：
1. title 必须提取，其他字段没有信息可以设为 null
2. publication_date 必须是完整的 YYYY-MM-DD 格式
3. authors 和 keywords 必须是数组格式
4. 其他字段可以是字符串或数组，设置为可用的格式
5. 如果信息不足，使用 null 值
"""

        # 使用 Agent 替代直接的 LLM 调用
        metadata_extraction_agent = Agent(
            name="metadata_extraction_agent",
            instructions="你是专业的论文信息提取专家。你必须准确完整地提取论文的所有元数据。请严格按照用户的要求，以 JSON 格式返回提取的信息。",
            model=get_tool_model(),
        )

        result = await Runner.run(
            starting_agent=metadata_extraction_agent,
            input=prompt,
            max_turns=1
        )

        # 提取Agent返回的文本内容
        response_text = result.final_output if hasattr(result, 'final_output') else str(result)

        # 尝试解析 JSON（可能包含在 markdown 代码块中）
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        extracted_info = json.loads(response_text)

        # 验证必填字段
        if not extracted_info.get("title"):
            extracted_info["title"] = "Unknown Paper"

        _current_paper.update(extracted_info)

        # 🔍 如果有 ArXiv ID，从 ArXiv API 获取准确的 journal-ref 和 comments（真实发表信息）
        arxiv_id = extracted_info.get("arxiv_id")
        if arxiv_id:
            arxiv_data = await _fetch_arxiv_journal_ref(arxiv_id)
            if arxiv_data.get("journal_ref"):
                # 优先使用 ArXiv 的 journal-ref（最准确的发表信息）
                extracted_info["venue"] = arxiv_data["journal_ref"]
                logger.info(
                    "🎯 使用 ArXiv journal-ref 作为 venue（准确的发表信息）",
                    venue=arxiv_data["journal_ref"][:100]
                )
                _current_paper["venue"] = arxiv_data["journal_ref"]
            elif arxiv_data.get("comments"):
                # 如果没有 journal-ref，检查 comments 字段（可能包含 "ACL 2025" 这样的信息）
                extracted_info["venue"] = arxiv_data["comments"]
                logger.info(
                    "🎯 使用 ArXiv comments 中的信息作为 venue",
                    comments=arxiv_data["comments"][:100]
                )
                _current_paper["venue"] = arxiv_data["comments"]
            elif arxiv_data.get("published_date"):
                # 如果没有 journal-ref 和 comments，至少用 ArXiv 上的发布日期
                if not extracted_info.get("publication_date") or extracted_info["publication_date"] == "null":
                    extracted_info["publication_date"] = arxiv_data["published_date"]
                    logger.info(
                        "📅 使用 ArXiv 发布日期作为 publication_date",
                        publication_date=arxiv_data["published_date"]
                    )

        # 如果 PDF 已下载但标题不一致，重新整理文件
        old_pdf_path = _current_paper.get("pdf_path")
        correct_title = extracted_info.get("title")

        if old_pdf_path and correct_title and Path(old_pdf_path).exists():
            old_path = Path(old_pdf_path)
            expected_path = _get_paper_pdf_path(correct_title)

            # 如果路径不同，说明下载时使用的是错误的标题
            if old_path != expected_path:
                try:
                    logger.info(
                        "📁 检测到标题不一致，重新整理 PDF 文件",
                        old_path=str(old_path),
                        new_path=str(expected_path)
                    )

                    # 创建新目录
                    expected_path.parent.mkdir(parents=True, exist_ok=True)

                    # 移动 PDF 文件
                    import shutil
                    shutil.move(str(old_path), str(expected_path))

                    # 删除旧目录（如果为空）
                    try:
                        if old_path.parent != expected_path.parent:
                            old_path.parent.rmdir()
                    except:
                        pass  # 目录不为空，忽略

                    # 更新全局变量中的路径
                    _current_paper["pdf_path"] = str(expected_path)

                    logger.info("✅ PDF 文件已重新整理到正确路径")

                except Exception as e:
                    logger.warning(f"重新整理 PDF 文件失败: {e}，继续使用原路径")

        elapsed = time.time() - start_time
        logger.info(
            "✅ 论文元数据提取成功",
            title=extracted_info.get("title", "Unknown"),
            authors_count=len(extracted_info.get("authors", [])),
            keywords_count=len(extracted_info.get("keywords", [])),
            elapsed_time=f"{elapsed:.2f}s"
        )

        # 📋 在日志中显示所有提取的元数据，方便用户提前判断
        logger.info(
            "🔍 提取完成，完整元数据如下：",
            title=extracted_info.get("title"),
            authors=extracted_info.get("authors"),
            publication_date=extracted_info.get("publication_date"),
            venue=extracted_info.get("venue")[:100] if extracted_info.get("venue") else None,
            affiliations=extracted_info.get("affiliations")[:100] if extracted_info.get("affiliations") else None,
            abstract=extracted_info.get("abstract")[:100] if extracted_info.get("abstract") else None,
            keywords=extracted_info.get("keywords"),
            doi=extracted_info.get("doi"),
            arxiv_id=extracted_info.get("arxiv_id"),
            project_page=extracted_info.get("project_page"),
            other_resources=extracted_info.get("other_resources")[:100] if extracted_info.get("other_resources") else None
        )

        return json.dumps({
            "success": True,
            **extracted_info,
            "message": f"✅ 论文信息提取成功（标题 + 元数据）！（耗时 {elapsed:.2f}s）"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 论文元数据提取失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"提取失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@function_tool
async def search_arxiv_pdf(
    paper_title: Annotated[str, "论文标题"]
) -> str:
    """
    在 arXiv 搜索论文 PDF 链接

    参数:
        paper_title: 论文标题

    返回:
        JSON格式的PDF链接信息
    """
    start_time = time.time()
    try:
        import urllib.parse

        logger.info("🔎 开始在 arXiv 搜索论文", paper_title=paper_title[:100])

        # arXiv API 搜索（使用 HTTPS）
        query = urllib.parse.quote(paper_title)
        api_url = f"https://export.arxiv.org/api/query?search_query=ti:{query}&max_results=3"

        proxy = os.getenv('http_proxy')
        mounts = None
        if proxy:
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=proxy),
            }

        async with httpx.AsyncClient(timeout=30.0, mounts=mounts) as client:
            response = await client.get(api_url)
            response.raise_for_status()

            # 解析 XML 响应
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            # 查找第一个匹配的论文
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('atom:entry', ns)

            if entries:
                entry = entries[0]
                # 获取 arXiv ID
                arxiv_id_elem = entry.find('atom:id', ns)
                if arxiv_id_elem is not None:
                    arxiv_id_full = arxiv_id_elem.text
                    # 提取 ID 部分（例如：http://arxiv.org/abs/2410.04618 -> 2410.04618）
                    arxiv_id = arxiv_id_full.split('/abs/')[-1]
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

                    # 获取标题确认
                    title_elem = entry.find('atom:title', ns)
                    found_title = title_elem.text.strip() if title_elem is not None else "Unknown"

                    elapsed = time.time() - start_time
                    logger.info(
                        "✅ arXiv 搜索成功",
                        arxiv_id=arxiv_id,
                        found_title=found_title[:100],
                        elapsed_time=f"{elapsed:.2f}s"
                    )

                    return json.dumps({
                        "success": True,
                        "pdf_url": pdf_url,
                        "arxiv_id": arxiv_id,
                        "arxiv_abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                        "found_title": found_title,
                        "message": f"✅ 在 arXiv 找到论文！（耗时 {elapsed:.2f}s）\nPDF: {pdf_url}\narXiv ID: {arxiv_id}"
                    }, ensure_ascii=False, indent=2)

        # 未找到
        elapsed = time.time() - start_time
        logger.warning(
            "⚠️ arXiv 未找到论文",
            paper_title=paper_title[:100],
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"在 arXiv 未找到论文《{paper_title}》。可能不是 arXiv 论文，或标题不完全匹配。"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ arXiv 搜索失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"arXiv 搜索失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@function_tool
async def extract_paper_info_from_webpage(
    webpage_url: Annotated[str, "学术论文网页的URL"]
) -> str:
    """
    从学术期刊/会议网页提取论文信息（标题、作者等）并尝试查找PDF链接

    支持的网站：Nature, Science, IEEE, ACM, Springer 等主流学术期刊和会议

    参数:
        webpage_url: 学术论文网页的URL

    返回:
        JSON格式的论文信息（包含标题和可能的PDF链接）
    """
    start_time = time.time()

    try:
        logger.info("🔍 开始从网页提取论文信息", url=webpage_url[:100])

        proxy = os.getenv('http_proxy')
        mounts = None
        if proxy:
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=proxy),
            }

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            mounts=mounts,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        ) as client:
            response = await client.get(webpage_url)
            response.raise_for_status()

            html_content = response.text

            # 使用 BeautifulSoup 解析 HTML（如果可用）
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'html.parser')

                # 提取标题
                title = None
                title_selectors = [
                    'h1.c-article-title',  # Nature
                    'h1[class*="article-title"]',
                    'h1[class*="ArticleTitle"]',
                    'meta[name="citation_title"]',
                    'meta[property="og:title"]',
                    'title',
                ]

                for selector in title_selectors:
                    if selector.startswith('meta'):
                        elem = soup.find('meta', attrs={'name': selector.split('[name="')[1].rstrip('"]')}) or \
                               soup.find('meta', attrs={'property': selector.split('[property="')[1].rstrip('"]')})
                        if elem and elem.get('content'):
                            title = elem.get('content')
                            break
                    else:
                        elem = soup.select_one(selector)
                        if elem:
                            title = elem.get_text(strip=True)
                            break

                # 提取PDF链接
                pdf_url = None
                pdf_patterns = [
                    r'href="([^"]*\.pdf)"',
                    r'data-track-action="download pdf"[^>]*href="([^"]*)"',
                    r'href="([^"]*/pdf/[^"]*)"',
                ]

                for pattern in pdf_patterns:
                    import re
                    matches = re.findall(pattern, html_content, re.IGNORECASE)
                    if matches:
                        pdf_url = matches[0]
                        # 处理相对URL
                        if pdf_url.startswith('/'):
                            from urllib.parse import urljoin
                            pdf_url = urljoin(webpage_url, pdf_url)
                        break

                elapsed = time.time() - start_time

                if title:
                    logger.info(
                        "✅ 网页信息提取成功",
                        title=title[:100],
                        has_pdf=bool(pdf_url),
                        elapsed_time=f"{elapsed:.2f}s"
                    )

                    return json.dumps({
                        "success": True,
                        "title": title,
                        "pdf_url": pdf_url,
                        "webpage_url": webpage_url,
                        "message": f"✅ 提取到论文标题：{title[:100]}" +
                                 (f"\n找到PDF链接：{pdf_url}" if pdf_url else "\n未找到直接PDF链接，将使用标题搜索")
                    }, ensure_ascii=False, indent=2)
                else:
                    return json.dumps({
                        "success": False,
                        "error": "无法从网页提取论文标题"
                    }, ensure_ascii=False, indent=2)

            except ImportError:
                # BeautifulSoup 不可用，使用简单的正则提取
                import re
                title_match = re.search(r'<title>([^<]+)</title>', html_content, re.IGNORECASE)
                title = title_match.group(1) if title_match else None

                pdf_match = re.search(r'href="([^"]*\.pdf)"', html_content, re.IGNORECASE)
                pdf_url = pdf_match.group(1) if pdf_match else None

                if title:
                    return json.dumps({
                        "success": True,
                        "title": title,
                        "pdf_url": pdf_url,
                        "webpage_url": webpage_url,
                        "message": f"✅ 提取到论文信息（基础模式）"
                    }, ensure_ascii=False, indent=2)
                else:
                    return json.dumps({
                        "success": False,
                        "error": "无法提取论文信息"
                    }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 网页信息提取失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"网页提取失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@function_tool
async def download_pdf_from_url(
    pdf_url: Annotated[str, "PDF文件的URL"],
    paper_title: Annotated[str, "论文标题（用于命名文件）"] = "paper"
) -> str:
    """
    下载 PDF 并读取全部内容

    参数:
        pdf_url: PDF 文件的 URL
        paper_title: 论文标题

    返回:
        包含 PDF 内容和元数据的 JSON
    """
    global _current_paper
    start_time = time.time()

    try:
        logger.info("📥 开始下载 PDF", pdf_url=pdf_url[:100], paper_title=paper_title[:50])

        # 使用新的目录结构：paper_digest/pdfs/{Paper_Title}/paper.pdf
        local_path = _get_paper_pdf_path(paper_title)

        # 下载 PDF
        proxy = os.getenv('http_proxy')
        mounts = None
        if proxy:
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=proxy),
            }

        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            mounts=mounts
        ) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()

            with open(local_path, 'wb') as f:
                f.write(response.content)

        # 读取 PDF 内容
        logger.info("📖 开始读取 PDF 内容")
        pdf_content, pdf_metadata = _read_pdf_file(str(local_path))

        _current_paper["pdf_path"] = str(local_path)
        _current_paper["pdf_url"] = pdf_url
        _current_paper["pdf_content"] = pdf_content
        _current_paper["pdf_metadata"] = pdf_metadata

        elapsed = time.time() - start_time
        logger.info(
            "✅ PDF 下载并读取成功",
            file_size=f"{len(response.content) / 1024 / 1024:.2f}MB",
            pages=pdf_metadata.get("pages", 0),
            content_length=len(pdf_content),
            elapsed_time=f"{elapsed:.2f}s"
        )

        return json.dumps({
            "success": True,
            "local_path": str(local_path),
            "pdf_url": pdf_url,
            "pdf_content": pdf_content[:5000],  # 返回前5000字符预览
            "pdf_metadata": json.dumps(pdf_metadata, ensure_ascii=False),
            "message": f"✅ PDF 下载并读取成功！文件: {local_path}（耗时 {elapsed:.2f}s）"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ PDF 下载失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"处理失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@function_tool
async def read_local_pdf(
    pdf_path: Annotated[str, "PDF文件的本地路径"]
) -> str:
    """
    读取本地 PDF 文件内容

    参数:
        pdf_path: PDF 文件的本地路径

    返回:
        包含 PDF 内容和元数据的 JSON
    """
    global _current_paper
    start_time = time.time()

    try:
        logger.info("📖 开始读取本地 PDF", pdf_path=pdf_path)

        pdf_content, pdf_metadata = _read_pdf_file(pdf_path)

        _current_paper["pdf_path"] = pdf_path
        _current_paper["pdf_content"] = pdf_content
        _current_paper["pdf_metadata"] = pdf_metadata

        elapsed = time.time() - start_time
        file_size = os.path.getsize(pdf_path) / 1024 / 1024 if os.path.exists(pdf_path) else 0
        logger.info(
            "✅ 本地 PDF 读取成功",
            pdf_path=pdf_path,
            file_size=f"{file_size:.2f}MB",
            pages=pdf_metadata.get("pages", 0),
            content_length=len(pdf_content),
            elapsed_time=f"{elapsed:.2f}s"
        )

        return json.dumps({
            "success": True,
            "pdf_path": pdf_path,
            "pdf_content": pdf_content[:5000],
            "pdf_metadata": json.dumps(pdf_metadata, ensure_ascii=False),
            "message": f"✅ PDF 读取成功！文件: {pdf_path}（耗时 {elapsed:.2f}s）"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 本地 PDF 读取失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"读取失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


def _get_paper_directory(paper_title: str) -> Path:
    """
    为每篇论文创建独立的目录

    目录结构：
    paper_digest/pdfs/
    ├── Paper_Title_1/
    │   ├── Paper_Title_1.pdf
    │   └── extracted_images/
    ├── Paper_Title_2/
    │   ├── Paper_Title_2.pdf
    │   └── extracted_images/

    Args:
        paper_title: 论文标题（完整标题，不截断）

    Returns:
        论文目录的 Path 对象
    """
    # 清理标题中的特殊字符，但保留完整长度
    safe_title = paper_title.replace('/', '_').replace(':', '_').replace('?', '_').replace('\\', '_').strip()
    # 限制最大长度为 150 字符，避免文件系统限制（通常 255）
    safe_title = safe_title[:150]
    paper_dir = PDF_DIR / safe_title
    paper_dir.mkdir(parents=True, exist_ok=True)

    return paper_dir


def _get_paper_pdf_path(paper_title: str) -> Path:
    """获取论文 PDF 的保存路径

    返回格式: paper_digest/pdfs/{Paper_Title}/{Paper_Title}.pdf

    Args:
        paper_title: 论文标题（完整标题）
    """
    paper_dir = _get_paper_directory(paper_title)
    # 清理文件名（移除特殊字符），使用与目录相同的名称
    safe_filename = paper_title.replace('/', '_').replace(':', '_').replace('?', '_').replace('\\', '_').strip()
    safe_filename = safe_filename[:150]  # 与目录名保持一致
    return paper_dir / f"{safe_filename}.pdf"


def _get_paper_images_dir(paper_title: str) -> Path:
    """获取论文图片提取目录的路径"""
    paper_dir = _get_paper_directory(paper_title)
    images_dir = paper_dir / "extracted_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _read_pdf_file(pdf_path: str):
    """读取 PDF 文件内容和元数据（内部函数）"""
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    # 提取元数据
    metadata = doc.metadata
    metadata_dict = {
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "subject": metadata.get("subject", ""),
        "keywords": metadata.get("keywords", ""),
        "creator": metadata.get("creator", ""),
        "producer": metadata.get("producer", ""),
        "creationDate": metadata.get("creationDate", ""),
        "modDate": metadata.get("modDate", ""),
        "pages": total_pages,
    }

    # 分批读取全部内容（每次10页）
    PAGES_PER_BATCH = 10
    all_pdf_text = []
    current_page = 0

    while current_page < total_pages:
        end_page = min(current_page + PAGES_PER_BATCH, total_pages)
        batch_text = ""

        for page_num in range(current_page, end_page):
            page = doc[page_num]
            batch_text += f"\n\n--- Page {page_num + 1} ---\n\n"
            batch_text += page.get_text()

        all_pdf_text.append(batch_text)
        current_page = end_page

    doc.close()

    # 合并所有内容
    full_pdf_content = "".join(all_pdf_text)

    # 截断到合理长度（~50000字符）
    MAX_CHARS = 50000
    if len(full_pdf_content) > MAX_CHARS:
        pdf_content = full_pdf_content[:MAX_CHARS] + "\n\n[内容已截断，后续内容略]"
    else:
        pdf_content = full_pdf_content

    return pdf_content, metadata_dict


def _auto_insert_images(
    markdown_content: str,
    extracted_images: list,
    relative_image_path: str
) -> str:
    """
    自动将图片插入到 Markdown 的适当位置

    改进策略：
    1. 检查 Markdown 是否已经包含图片引用（如果有，只插入缺失的）
    2. 更智能的章节匹配：
       - 分析 caption 和图片编号
       - Figure 1-2 通常是方法/架构图 → 方法章节
       - Table 和后续 Figures 通常是实验结果 → 实验章节
       - 特殊 Figures（training, ablation）→ 相应章节
    3. 按编号顺序插入，确保不遗漏

    Args:
        markdown_content: 原始 Markdown 内容
        extracted_images: 提取的图片列表
        relative_image_path: 图片相对路径

    Returns:
        插入图片后的 Markdown 内容
    """
    import re

    # 检查已插入的图片
    existing_images = set()
    for match in re.finditer(r'<img src="[^"]*?/([^/"]+)"', markdown_content):
        existing_images.add(match.group(1))

    # 过滤出需要插入的图片
    images_to_insert = [img for img in extracted_images if img['filename'] not in existing_images]

    if not images_to_insert:
        logger.info("所有图片已插入，无需处理")
        return markdown_content

    logger.info(f"需要插入 {len(images_to_insert)} 张图片")

    # 按 Figure/Table 编号排序
    def sort_key(img):
        fig_type = img.get('fig_type', 'Figure')
        fig_name = img.get('fig_name', '0')
        try:
            num = int(fig_name)
        except:
            num = 999
        # Table 优先级低于 Figure
        return (0 if fig_type == 'Figure' else 1, num)

    images_to_insert.sort(key=sort_key)

    # 智能分组：根据内容和编号
    method_images = []
    experiment_images = []
    other_images = []

    for img in images_to_insert:
        caption = img.get('caption', '').lower()
        fig_type = img.get('fig_type', 'Figure')
        fig_name = img.get('fig_name', '0')

        try:
            fig_num = int(fig_name)
        except:
            fig_num = 999

        # 分类规则
        if fig_type == 'Figure' and fig_num <= 2:
            # Figure 1-2 通常是方法/架构图
            method_images.append(img)
        elif 'method' in caption or 'architecture' in caption or 'framework' in caption or 'mechanism' in caption or 'optimization' in caption:
            method_images.append(img)
        elif 'performance' in caption or 'result' in caption or 'comparison' in caption or 'experiment' in caption or 'training' in caption or fig_type == 'Table':
            experiment_images.append(img)
        else:
            other_images.append(img)

    # 生成图片 HTML
    def create_image_html(images):
        html = "\n\n"
        for img in images:
            fig_type = img.get('fig_type', 'Figure')
            fig_name = img.get('fig_name', '')
            filename = img['filename']
            caption = img.get('caption', '')
            html += f'''<figure>
  <img src="{relative_image_path}/{filename}" alt="{fig_type} {fig_name}">
  <figcaption>{caption}</figcaption>
</figure>

'''
        return html

    modified_content = markdown_content

    # 插入方法相关图片到 "方法实现细节" 章节
    if method_images:
        method_pattern = r'(##\s*⚙️\s*方法实现细节.*?)((?=\n##)|$)'
        if re.search(method_pattern, modified_content, re.DOTALL):
            images_html = create_image_html(method_images)
            def replacer(match):
                section_content = match.group(1)
                next_section = match.group(2)
                return section_content + images_html + next_section
            modified_content = re.sub(method_pattern, replacer, modified_content, flags=re.DOTALL, count=1)
            logger.info(f"插入 {len(method_images)} 张图片到方法章节")
        else:
            # 如果没有"方法实现细节"，尝试"本文方法"
            method_pattern2 = r'(##\s*💡\s*本文方法.*?)((?=\n##)|$)'
            if re.search(method_pattern2, modified_content, re.DOTALL):
                images_html = create_image_html(method_images)
                def replacer(match):
                    section_content = match.group(1)
                    next_section = match.group(2)
                    return section_content + images_html + next_section
                modified_content = re.sub(method_pattern2, replacer, modified_content, flags=re.DOTALL, count=1)
                logger.info(f"插入 {len(method_images)} 张图片到本文方法章节")
            else:
                experiment_images.extend(method_images)  # 放到实验章节

    # 插入实验相关图片到 "实验与结果" 章节
    if experiment_images:
        result_pattern = r'(##\s*📊\s*实验与结果.*?)((?=\n##)|$)'
        if re.search(result_pattern, modified_content, re.DOTALL):
            images_html = create_image_html(experiment_images)
            def replacer(match):
                section_content = match.group(1)
                next_section = match.group(2)
                return section_content + images_html + next_section
            modified_content = re.sub(result_pattern, replacer, modified_content, flags=re.DOTALL, count=1)
            logger.info(f"插入 {len(experiment_images)} 张图片到实验章节")
        else:
            # 如果没有实验章节，添加到文档末尾
            images_html = create_image_html(experiment_images)
            modified_content += "\n\n---\n\n## 📊 Figures & Tables\n\n" + images_html
            logger.info(f"插入 {len(experiment_images)} 张图片到文档末尾")

    # 其他图片插入到文档末尾
    if other_images:
        images_html = create_image_html(other_images)
        # 检查是否已有 "Figures & Tables" 章节
        if "## 📊 Figures & Tables" in modified_content:
            # 追加到该章节
            modified_content = modified_content.replace(
                "## 📊 Figures & Tables\n\n",
                f"## 📊 Figures & Tables\n\n{images_html}"
            )
        else:
            modified_content += "\n\n---\n\n## 📊 Other Figures\n\n" + images_html
        logger.info(f"插入 {len(other_images)} 张其他图片")

    return modified_content






@function_tool
async def generate_paper_digest(
    xiaohongshu_content: Annotated[str, "小红书帖子内容"] = "",
    paper_title: Annotated[str, "论文标题"] = "",
    pdf_content: Annotated[str, "PDF全文内容"] = "",
    authors: Annotated[str, "作者列表（JSON数组字符串）"] = "[]",
    publication_date: Annotated[str, "发表日期（YYYY-MM-DD）"] = "",
    venue: Annotated[str, "期刊/会议名称"] = "",
    abstract: Annotated[str, "摘要"] = "",
    affiliations: Annotated[str, "机构"] = "",
    keywords: Annotated[str, "关键词列表（JSON数组字符串）"] = "[]",
    project_page: Annotated[str, "项目主页"] = "",
    other_resources: Annotated[str, "其他资源"] = "",
    pdf_path: Annotated[str, "PDF文件路径（用于提取图片，可选）"] = "",
) -> str:
    """
    生成结构化论文整理

    参数:
        xiaohongshu_content: 小红书帖子内容
        paper_title: 论文标题
        pdf_content: PDF 全文内容
        authors: 作者列表
        publication_date: 发表日期
        venue: 期刊/会议
        abstract: 摘要
        affiliations: 机构
        keywords: 关键词
        project_page: 项目主页
        other_resources: 其他资源

    返回:
        Markdown格式的论文整理
    """
    global _openai_client, _current_paper
    start_time = time.time()

    # 读取模板
    template_path = Path(__file__).parent / "digest_template.md"
    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    # 提取 PDF 中的图片（如果提供了 PDF 路径）
    images_info = ""

    # 优先使用传入的 pdf_path，如果为空则从全局变量获取
    effective_pdf_path = pdf_path
    if not effective_pdf_path or not Path(effective_pdf_path).exists():
        effective_pdf_path = _current_paper.get("pdf_path", "")
        if effective_pdf_path:
            logger.info("📄 使用全局变量中的 PDF 路径", pdf_path=effective_pdf_path[:100])

    if effective_pdf_path and Path(effective_pdf_path).exists():
        try:
            logger.info("🖼️  开始提取 PDF 中的 Figures/Tables", pdf_path=effective_pdf_path[:100])
            from .pdf_figure_extractor_v2 import PDFFigureExtractorV2

            # 将图片保存到论文特定目录：paper_digest/pdfs/{Paper_Title}/extracted_images/
            images_dir = _get_paper_images_dir(paper_title)

            extractor = PDFFigureExtractorV2(str(images_dir))
            images, blocks = extractor.extract(effective_pdf_path)

            if images:
                # V2 提取器已经提供了完整的 Figures/Tables，不需要再选择
                # 直接使用所有提取的图片（已按重要性排序）

                # 格式化图片信息供 LLM 使用（详细版，包含完整 caption）
                images_list = "\n".join([
                    f"【{img['fig_type']} {img['fig_name']}】\n" +
                    f"  文件名: {img['filename']}\n" +
                    f"  Caption: {img.get('caption', '(无caption)') or '(无caption)'}\n" +
                    f"  页码: 第 {img['page']} 页"
                    for img in images
                ])

                # 为LLM生成图片编号参考（方便后续引用）
                fig_references = "\n".join([
                    f"- {img['fig_type']} {img['fig_name']}: {img.get('caption', '')[:80]}..."
                    for img in images[:20]  # 列出前20个图片
                ])

                # 计算相对路径（从 outputs/ 到 pdfs/{Paper_Title}/extracted_images/）
                safe_title = paper_title.replace('/', '_').replace(':', '_').replace('?', '_').replace('\\', '_').strip()[:150]
                relative_image_path = f"../pdfs/{safe_title}/extracted_images"

                # 统计提取来源
                pdffigures2_count = sum(1 for img in images if img.get('source') == 'pdffigures2')
                python_count = sum(1 for img in images if img.get('source') == 'python_fallback')

                images_info = f"""
# 论文 Figures/Tables（共 {len(images)} 个，已提取）

提取来源：
- PDFFigures2: {pdffigures2_count} 个 📊
- Python Fallback: {python_count} 个 🐍

## 图片列表（包含完整 Caption）

{images_list}

---

## 🎯 图片插入要求（非常重要！）

你**必须**根据每张图片的 **Caption 内容**智能决定插入位置，而不是简单地全部堆到一个章节。

### 插入格式（⚠️ 必须统一使用 HTML <figure> 标签，包含英文原文和中文翻译）
```html
<figure>
  <img src="{relative_image_path}/{{filename}}" alt="{{fig_type}} {{fig_name}}">
  <figcaption>
    <strong>{{fig_type}} {{fig_name}}</strong>：{{完整caption英文原文}}
    （中文：{{caption中文翻译}}）
  </figcaption>
</figure>
```

**重要提示：**
- ❌ 不要使用 Markdown 图片语法 `![alt](path)`
- ✅ 必须使用上面的 HTML `<figure>` 标签格式
- ✅ 确保路径完整：`{relative_image_path}/{{filename}}`
- ✅ **Caption 必须包含英文原文和中文翻译**，格式：英文原文（中文：中文翻译）

### 智能选择与插入策略（基于重要性评分）

⚠️ **重要：不要插入所有图片！根据图片的重要性评分，只插入高价值的图片。**

#### 评分标准（满分10分，≥7分的图片才插入）：

**评分维度**：
1. **核心方法理解** (0-4分)
   - 4分：核心架构图、算法流程图、方法示意图
   - 3分：方法应用示例、关键组件图、**背景/动机示例图**
   - 2分：辅助示意图
   - 0-1分：边缘性示例

2. **实验价值** (0-4分)
   - 4分：主要性能对比表、核心实验结果
   - 3分：关键消融实验、重要对比图
   - 2分：次要实验结果、**背景示例的说明价值**
   - 0-1分：训练曲线、行为统计、细节图

3. **信息密度** (0-2分)
   - 2分：一张图包含大量关键信息、**背景示例能直观说明问题**
   - 1分：信息量中等
   - 0分：信息可以用文字简单说明

#### 典型评分示例：

- **背景/动机示例**: 核心方法(3分) + 实验价值(2分) + 信息密度(2分) = **7分** ✅
- 架构/算法图: 核心方法(4分) + 实验价值(1分) + 信息密度(2分) = **7分** ✅
- 主要性能对比表: 核心方法(1分) + 实验价值(4分) + 信息密度(2分) = **7分** ✅
- 行为统计表: 核心方法(0分) + 实验价值(2分) + 信息密度(1分) = **3分** ❌
- 训练曲线/示例: 通常 3-5分 ❌

⚠️ **特别提示**：背景/动机示例图通常出现在论文开头，对理解问题非常有帮助，应该优先插入！

#### 插入位置要求：

1. **背景类图片** → 插入到"🎯 研究背景与动机"章节
   - 紧跟问题背景或研究动机说明
   - 帮助读者直观理解要解决的问题

2. **方法类图片** → 插入到"💡 本文方法"或"⚙️ 方法实现细节"章节
   - 紧跟相关文字说明，不要单独成段
   - 帮助读者理解核心算法/架构

3. **实验类图片** → 插入到"📊 实验与结果"章节
   - 放在实验设置和主要结果说明之后
   - 只插入最核心的性能对比表/图

### 📍 图片文件路径
{images_dir}

### ⚠️ 插入要求

#### 1. 图片选择与位置
- **根据评分选择**：只插入评分 ≥7 分的图片
- 其他图片用文字总结
- 必须使用完整路径：`{relative_image_path}/{{filename}}`
- 图片紧跟相关文字，不要堆在章节末尾

#### 2. Caption 翻译与格式（**非常重要**）
- **Caption 必须同时包含英文原文和中文翻译**
- 格式示例：
  ```
  Figure 1: Overview of the proposed method framework.
  （中文：提出的方法框架概览。）
  ```
- 中文翻译要准确传达英文原意，保留专有名词原文
- 中文翻译应该是专业、学术的风格

#### 3. 图片引用与自然插入（**非常重要**）
- **在每张图片前面添加自然的引用语句**，让图片的插入更顺畅
- **⚠️ 引用语句必须明确指出具体的图表编号**，例如：
  * "从图1中可以看出，..."
  * "如图2所示，..."
  * "表1展示了..."
  * "由图3可以看出..."
  * "图4描述了..."
  * "从表2的数据可以看出..."
  * "对比图5，我们可以发现..."
- **❌ 禁止使用笼统的表述**，例如：
  * ❌ "从图示可以看出..."
  * ❌ "如图所示..."
  * ❌ "从图中可以看出..."
  * ❌ "下图展示了..."
- 引用语句中的图表编号必须与实际插入的 Figure/Table 编号一致
- 引用语句应该与前面的文本自然衔接，形成完整的段落逻辑
"""

                logger.info(
                    "✅ Figures/Tables 提取完成",
                    total=len(images),
                    pdffigures2=pdffigures2_count,
                    python_fallback=python_count,
                    images_dir=str(images_dir)
                )
                # 保存图片信息到全局变量供后续使用
                _current_paper["extracted_images"] = images
                _current_paper["images_dir"] = str(images_dir)
            else:
                logger.info("ℹ️  PDF 中未找到可提取的 Figures/Tables")

        except Exception as e:
            logger.warning(f"提取 PDF 图片失败，继续生成没有图片的 Markdown: {e}")
            # 继续不中断，只记录警告

    try:
        logger.info("✍️ 开始生成论文整理（LLM 调用 2/2）", paper_title=paper_title[:100])
        prompt = f"""
你是论文整理专家。请根据以下信息，按照模板生成高质量的论文整理。

# 论文基本信息
- **标题**: {paper_title}
- **作者**: {authors}
- **机构**: {affiliations}
- **发表时间**: {publication_date}
- **期刊/会议**: {venue}
- **关键词**: {keywords}
- **项目页**: {project_page if project_page else "[无]"}
- **其他资源**: {other_resources if other_resources else "[无]"}

# 小红书内容（参考）
{xiaohongshu_content}

# 论文摘要
{abstract if abstract else "[未提取到摘要]"}

# PDF 全文内容（重点参考）
{pdf_content[:20000] if pdf_content else "[未提供PDF内容]"}

{images_info}

# 整理模板
{template_content}

# 要求（⚠️ 严格执行）
1. **必须严格按照模板结构**，包含所有章节
2. **优先使用 PDF 全文内容**，其次参考小红书内容
3. **内容精简高效**：
   - 关键概念用列表/表格表示，避免过长段落
   - 每个章节控制在 3-5 个自然段落
   - 详细内容用概述 + 要点的方式呈现
   - 避免重复冗余的说明
4. **详细填充以下章节**：
   - 文章背景与基本观点
   - 现有解决方案的思路与问题
   - 本文提出的思想与方法
   - 方法实现细节
   - 方法有效性证明（实验）
   - 局限性与未来方向
5. **如果信息不足**，明确标注 "[信息不足]"
6. **保持学术性和专业性**
7. **使用 Markdown 格式**，充分利用标题、列表、表格等结构化元素
8. **基本信息必须准确填写**（包括完整日期、标签、项目页、其他资源）
9. **输出长度控制**：确保最终 Markdown 整理转换为 Notion blocks 后不超过 100 个块（通常 5000-8000 字符可保证）
10. **图片精选插入与引用**（如果提供了图片信息）：
    - ⚠️ **根据重要性评分（≥7分）决定是否插入图片**，不要插入所有图片
    - 其他图片（评分<7分）用**文字总结**即可
    - 使用提供的 HTML figure 标签格式，**Caption 必须包含英文原文和中文翻译**
    - 图片应该插入到相关文字说明的附近，而不是单独堆在章节末尾
    - **⚠️ 在图片前面必须插入明确的引用语句**，必须包含具体的图表编号：
      * ✅ "从图1中可以看出，..."（正确：明确图号）
      * ✅ "如图2所示，..."（正确：明确图号）
      * ✅ "表1展示了..."（正确：明确表号）
      * ❌ "从图示可以看出..."（错误：没有明确编号）
      * ❌ "如图所示..."（错误：笼统表述）
    - 引用语句中的编号必须与实际插入的 Figure/Table 编号一致
    - 保持笔记精简，避免图片过多影响阅读体验

请输出精简高效的论文整理（Markdown格式，包含智能插入的图片和自然图片引用）：
"""
#         prompt = f"""
# 你是论文整理专家。请根据以下信息，**在不改变模板结构的前提下**，生成高质量、专业且信息保真的论文整理（Markdown）。目标：兼顾精炼与**专有名词/术语的完整保留**。

# # 论文基本信息
# - **标题**: {paper_title}
# - **作者**: {authors}
# - **机构**: {affiliations}
# - **发表时间**: {publication_date}
# - **期刊/会议**: {venue}
# - **关键词**: {keywords}
# - **项目页**: {project_page if project_page else "[无]"}
# - **其他资源**: {other_resources if other_resources else "[无]"}

# # 小红书内容（参考）
# {xiaohongshu_content}

# # 论文摘要
# {abstract if abstract else "[未提取到摘要]"}

# # PDF 全文内容（重点参考）
# {pdf_content[:20000] if pdf_content else "[未提供PDF内容]"}

# {images_info}

# # 整理模板
# {template_content}

# # 要求（⚠️ 严格执行）
# 1. **结构与信息源**
#    - **严格按照模板结构与层级**输出；若某章节信息不足，保留标题并标注“[信息不足]”。
#    - **信息优先级**：PDF全文 > 摘要 > 小红书；冲突处标“[信息冲突]”，不得臆造。
#    - **不新增一级标题**；可在合适的小节内用表格/列表呈现补充要点。

# 2. **术语与名词保留（关键强化）**
#    - **保留专有名词、模型名、方法名、算法名、数据集名、指标名**（如 ViT、Swin, ResNet-50, COCO, PSNR/SSIM、BLEU、FID、mIoU 等）**原文大小写与拼写**。
#    - **首次出现**给出“**英文全称（缩写）+ 中文释义**”（如需）；后续统一使用同一缩写，不随意变体。
#    - 在模板允许的小节内，优先呈现一张**“术语与符号表（精简版）”**（不单独新增一级标题），字段建议：  
#      | 名称/符号(原文) | 中文 | 类型(模型/数据集/指标/变量) | 定义/含义 | 单位/默认值 | 备注 |
#    - **不得将专有名词泛化或替换为通俗表述**；缺失定义时标注“[信息不足]”。

# 3. **数学与公式（保真但克制）**
#    - 关键公式**保留 LaTeX 形式**（$...$ 或 $$...$$），**不篡改符号与下标/上标**；若推导缺失，给出**用途一句话概述**。
#    - 选择**最关键的 ≤5 个**公式；其余以要点概述，避免冗长推导。
#    - 变量/参数在“术语与符号表”中对齐含义与单位。

# 4. **内容精简高效（但信息不丢失）**
#    - **能用表格/要点不写长段**：概念对比、模块组成、数据与指标、消融项统一**表格优先**。
#    - 每章节**3–5 段**为上限；采用“**概述一句话 + 2–6 个要点**”结构；避免重复冗余。
#    - 重点补足以下章节（若模板对应章节名称不同，按语义对应）：
#      - 文章背景与基本观点（Problem/Gaps/Assumptions）
#      - 现有解决方案的思路与问题（方法族对比+已知局限）
#      - 本文提出的思想与方法（总体框架/模块、创新点清单）
#      - 方法实现细节（训练流程、关键超参、损失函数、数据设置/预处理、复杂度/开销）  
#      - 方法有效性证明（实验设计：数据集/划分、Baselines、指标、SOTA 对比、消融与显著性）  
#      - 局限性与外推边界（适用场景/失败模式/未来方向）
#    - 数值**附单位与设置**（如输入分辨率、batch size、学习率、训练轮次、显存/设备）。

# 5. **图片精选插入**
#    - 若提供了图片信息，**仅当重要性评分 ≥ 7 分**时插入；评分 <7 以文字总结。
#    - 使用提供的 **HTML <figure> 标签与原始 Caption**；图片**靠近相关文字段落**插入，避免堆放在文末。
#    - 图中术语与图名**保持原文**；若需翻译，采用“中文（英文原文）”。

# 6. **准确性与可复现性**
#    - 数据集（名称/版本/划分）、评测协议、指标定义**尽量明确**；无法确认时标“[信息不足]”。
#    - SOTA/对比结果建议用表格，含：方法、设置（如分辨率/预训练）、指标均值±方差（若提供）、提升幅度。
#    - 训练/推理开销（FLOPs、Params、吞吐/延迟、显存）若有，归纳为一张**资源开销表**；无则“[信息不足]”。

# 7. **格式与长度**
#    - **Markdown** 输出（可含表格与行内/块级公式）；不输出额外解释或自检清单。
#    - **基本信息必须准确**（日期尽量 YYYY-MM-DD；项目页/其他资源仅填已提供）。
#    - **长度控制**：保证最终导入 Notion 后**不超过 100 个块**（通常 **5,000–8,000 字符**可达成）。

# 8. **边界与合规**
#    - 不新增外部链接/引用；不杜撰数据或实验。
#    - 对于缺失或相互矛盾的信息，**显式标注**“[信息不足]”/“[信息冲突]”。

# 请输出**精炼但信息保真的论文整理**（Markdown 格式，包含必要表格与按规则筛选的图片）。
# """
        # 使用 Agent 替代直接的 LLM 调用
        digest_generation_agent = Agent(
            name="digest_generation_agent",
            instructions="你是专业的论文整理专家，擅长结构化整理学术论文。你必须详细、完整地填充论文整理模板的所有章节。",
            model=get_tool_model(),
        )

        result = await Runner.run(
            starting_agent=digest_generation_agent,
            input=prompt,
            max_turns=1
        )

        # 提取Agent返回的文本内容
        digest_content = result.final_output if hasattr(result, 'final_output') else str(result)

        # 🔧 清理 LLM 输出：移除外层的 markdown 代码围栏（如果存在）
        # DeepSeek 等模型可能会在输出外层包裹 ```markdown ... ```
        digest_content = digest_content.strip()
        if digest_content.startswith("```markdown"):
            # 移除开头的 ```markdown
            digest_content = digest_content[len("```markdown"):].lstrip('\n')
        elif digest_content.startswith("```"):
            # 移除开头的 ```
            digest_content = digest_content[3:].lstrip('\n')

        # 移除结尾的 ```（如果存在）
        if digest_content.endswith("```"):
            digest_content = digest_content[:-3].rstrip('\n')

        # 🔧 备用方案：仅在 LLM 完全没有插入图片时才自动插入核心图片
        # 注意：现在的策略是 LLM 只插入 2-3 张核心图片，所以不需要补充所有遗漏的图片
        if images_info and _current_paper.get("extracted_images"):
            original_image_count = digest_content.count('<figure>')

            # 只有当 LLM 完全没有插入图片时，才使用备用方案
            if original_image_count == 0:
                logger.warning("⚠️  LLM 完全没有插入图片，启用备用方案")
                digest_content = _auto_insert_images(
                    digest_content,
                    _current_paper["extracted_images"],
                    relative_image_path
                )
                final_image_count = digest_content.count('<figure>')
                logger.info(f"✅ 备用方案已插入 {final_image_count} 张核心图片")
            else:
                logger.info(f"✅ LLM 已插入 {original_image_count} 张图片，无需备用方案")

        # 保存到文件
        safe_title = paper_title.replace('/', '_').replace(':', '_').replace('?', '_').replace('\\', '_').strip() if paper_title else "paper"
        # 限制最大长度为 150 字符，避免文件系统限制
        safe_title = safe_title[:150]
        output_file = OUTPUT_DIR / f"{safe_title}.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(digest_content)

        _current_paper["digest_content"] = digest_content
        _current_paper["digest_file"] = str(output_file)

        elapsed = time.time() - start_time
        logger.info(
            "✅ 论文整理生成成功",
            paper_title=paper_title[:100],
            content_length=len(digest_content),
            output_file=str(output_file),
            elapsed_time=f"{elapsed:.2f}s"
        )

        return json.dumps({
            "success": True,
            "output_file": str(output_file),
            "digest_content": digest_content,
            "message": f"✅ 论文整理生成成功！文件: {output_file}（耗时 {elapsed:.2f}s）"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 论文整理生成失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"生成失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@function_tool
async def save_digest_to_notion(
    paper_title: Annotated[str, "论文标题"],
    digest_content: Annotated[str, "论文整理内容（Markdown格式）"],
    source_url: Annotated[str, "来源URL"] = "",
    pdf_url: Annotated[str, "PDF链接"] = "",
    authors: Annotated[str, "作者列表（JSON数组字符串或逗号分隔）"] = "",
    affiliations: Annotated[str, "机构"] = "",
    publication_date: Annotated[str, "发表日期（YYYY-MM-DD格式）"] = "",
    venue: Annotated[str, "期刊/会议名称"] = "",
    abstract: Annotated[str, "摘要"] = "",
    keywords: Annotated[str, "关键词（JSON数组字符串或逗号分隔）"] = "",
    doi: Annotated[str, "DOI"] = "",
    arxiv_id: Annotated[str, "ArXiv ID"] = "",
    project_page: Annotated[str, "项目主页"] = "",
    other_resources: Annotated[str, "其他资源（代码仓库、数据集等）"] = "",
) -> str:
    """
    将论文整理保存到 Notion

    参数:
        paper_title: 论文标题
        digest_content: 论文整理内容
        source_url: 来源链接
        pdf_url: PDF链接
        authors: 作者
        affiliations: 机构
        publication_date: 发表日期
        venue: 期刊/会议
        abstract: 摘要
        keywords: 关键词
        doi: DOI
        arxiv_id: ArXiv ID
        project_page: 项目主页
        other_resources: 其他资源

    返回:
        保存结果
    """
    from notion_client import AsyncClient
    start_time = time.time()

    try:
        logger.info("💾 开始保存论文整理到 Notion", paper_title=paper_title[:100])
        client = AsyncClient(auth=os.getenv('NOTION_INTEGRATION_SECRET'))

        # 构建 properties
        properties = {
            "Name": {
                "title": [{"text": {"content": paper_title[:2000]}}]
            }
        }

        # Authors - 处理 JSON 数组或逗号分隔字符串
        if authors:
            try:
                authors_list = json.loads(authors) if authors.startswith('[') else [a.strip() for a in authors.split(',')]
                authors_str = ", ".join(authors_list)
                properties["Authors"] = {"rich_text": [{"text": {"content": authors_str[:2000]}}]}
            except:
                properties["Authors"] = {"rich_text": [{"text": {"content": authors[:2000]}}]}

        if affiliations:
            properties["Affiliations"] = {"rich_text": [{"text": {"content": affiliations[:2000]}}]}
        if venue:
            properties["Venue"] = {"rich_text": [{"text": {"content": venue[:2000]}}]}
            logger.info(
                "✅ Venue 字段已设置",
                venue=venue[:100]
            )

        # Abstract - 使用中文摘要（从 digest_content 提取）
        if abstract:
            chinese_abstract = _extract_chinese_abstract(digest_content)
            if chinese_abstract:
                properties["Abstract"] = {"rich_text": [{"text": {"content": chinese_abstract[:2000]}}]}

        # Keywords - multi_select 类型
        if keywords:
            try:
                keywords_list = json.loads(keywords) if keywords.startswith('[') else [k.strip() for k in keywords.split(',')]
                properties["Keywords"] = {"multi_select": [{"name": kw} for kw in keywords_list[:10]]}  # Notion 限制
            except:
                pass

        # ArXiv ID
        if arxiv_id:
            properties["ArXiv ID"] = {"rich_text": [{"text": {"content": arxiv_id[:2000]}}]}

        # Publication Date - date 类型
        if publication_date:
            try:
                # 验证日期格式 YYYY-MM-DD
                if len(publication_date) == 10 and publication_date[4] == '-' and publication_date[7] == '-':
                    properties["Publication Date"] = {"date": {"start": publication_date}}
            except:
                pass

        # Other Resources - rich_text 类型
        if other_resources:
            properties["Other Resources"] = {"rich_text": [{"text": {"content": other_resources[:2000]}}]}

        # PDF Link - url 类型
        if pdf_url:
            properties["PDF Link"] = {"url": pdf_url}

        # Source URL (小红书链接) - url 类型
        if source_url:
            properties["Source URL"] = {"url": source_url}

        # 转换 Markdown 为 Notion blocks（包含图片处理）
        blocks = await _markdown_to_notion_blocks_with_images(digest_content)

        # Notion API 限制：单次创建页面最多 100 个 children blocks
        # 如果超过 100 个，进行切片处理
        if len(blocks) > 100:
            logger.warning(
                f"⚠️  Blocks 超过 100 个限制 ({len(blocks)}，已截断到 100)",
                original_count=len(blocks),
                truncated_count=100
            )
            blocks = blocks[:100]

        response = await client.pages.create(
            parent={"database_id": os.getenv('NOTION_DATABASE_ID')},
            properties=properties,
            children=blocks,
        )

        page_id = response["id"]
        page_url = f"https://notion.so/{page_id.replace('-', '')}"

        await client.aclose()

        elapsed = time.time() - start_time
        logger.info(
            "✅ 论文整理已保存到 Notion",
            paper_title=paper_title[:100],
            page_id=page_id,
            page_url=page_url,
            properties_count=len(properties),
            blocks_count=len(blocks),
            elapsed_time=f"{elapsed:.2f}s"
        )

        return json.dumps({
            "success": True,
            "page_id": page_id,
            "page_url": page_url,
            "message": f"✅ 论文整理已保存到 Notion！（耗时 {elapsed:.2f}s）\n\n查看链接: {page_url}"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "❌ 保存到 Notion 失败",
            error=str(e),
            elapsed_time=f"{elapsed:.2f}s"
        )
        return json.dumps({
            "success": False,
            "error": f"保存失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


def _extract_chinese_abstract(digest_content: str) -> str:
    """从生成的中文论文整理中提取摘要部分"""
    import re

    patterns = [
        r'##\s*📝\s*摘要\s*\(.*?\)\s*\n+(.*?)(?=\n##|\n---|\Z)',
        r'##\s*摘要\s*\(.*?\)\s*\n+(.*?)(?=\n##|\n---|\Z)',
        r'##\s*摘要\s*\n+(.*?)(?=\n##|\n---|\Z)',
    ]

    for pattern in patterns:
        match = re.search(pattern, digest_content, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # Clean markdown formatting
            abstract = re.sub(r'\*\*(.+?)\*\*', r'\1', abstract)
            abstract = re.sub(r'\*(.+?)\*', r'\1', abstract)
            abstract = ' '.join(abstract.split())
            return abstract[:2000]

    # Fallback: 使用前200字符
    return digest_content[:200].replace('#', '').strip()


async def _markdown_to_notion_blocks_with_images(markdown_text: str) -> list:
    """
    将 Markdown 转换为 Notion API blocks（包含图片处理）

    1. 从全局变量中获取已提取的图片信息
    2. 从 Markdown 中提取图片引用和创建 image blocks
    3. 将文本 blocks 和图片 blocks 交错排列
    4. 保持原始 Markdown 的结构顺序

    Args:
        markdown_text: Markdown 文本（可能包含 HTML figure 标签）

    Returns:
        Notion API blocks 列表（包含文本和图片 blocks）
    """
    global _current_paper

    try:
        from .notion_markdown_converter import markdown_to_notion_blocks
        from .notion_image_uploader import (
            create_image_blocks_from_markdown,
            interleave_blocks_with_images,
            NotionImageUploader
        )

        # 第一步：获取已提取的图片信息（如果有）
        extracted_images = _current_paper.get("extracted_images", [])
        images_dir = _current_paper.get("images_dir", "")

        if not extracted_images or not images_dir:
            # 没有提取到图片，直接转换 Markdown
            logger.info("未找到已提取的图片，仅转换 Markdown")
            text_blocks = markdown_to_notion_blocks(markdown_text)
            return text_blocks

        # 检查 images_dir 是否存在，如果不存在则检查备选路径
        images_path = Path(images_dir)
        if not images_path.exists():
            # 尝试从 digest_content 推断图片目录（后向兼容性）
            logger.warning(f"图片目录不存在: {images_dir}，尝试查找...")

            # 尝试多个备选路径
            alt_dirs = [
                # 新的论文特定目录结构（优先）
                _get_paper_images_dir(_current_paper.get("title", "unknown")),
                # 旧的通用提取图片目录（后向兼容）
                PROJECT_ROOT / "paper_digest" / "pdfs" / "extracted_images",
            ]

            for alt_dir in alt_dirs:
                if alt_dir.exists():
                    images_dir = str(alt_dir)
                    images_path = alt_dir
                    logger.info(f"找到备选图片目录: {images_dir}")
                    break
            else:
                logger.warning("未找到图片目录，将仅转换 Markdown")
                text_blocks = markdown_to_notion_blocks(markdown_text)
                return text_blocks

        # 第二步：创建图片文件名到 file_upload_id 的映射
        # ⚠️ 注意：在实际使用中，需要使用 Notion API 上传图片
        # 当前实现使用外部 URL（如果有）或提示需要上传
        image_upload_map = {}
        failed_images = []

        notion_integration_secret = os.getenv('NOTION_INTEGRATION_SECRET')
        if notion_integration_secret and images_dir:
            try:
                logger.info("开始上传提取的图片到 Notion")
                uploader = NotionImageUploader(notion_integration_secret)

                # 准备图片文件列表
                images_to_upload = [
                    str(Path(images_dir) / img['filename'])
                    for img in extracted_images
                    if Path(images_dir, img['filename']).exists()
                ]

                if images_to_upload:
                    # 批量上传图片
                    upload_map, failed = await uploader.upload_images_batch(images_to_upload)
                    image_upload_map = upload_map
                    failed_images = failed

                    logger.info(
                        "✅ 图片上传完成",
                        uploaded_count=len(upload_map),
                        failed_count=len(failed)
                    )
                else:
                    logger.warning("未找到本地提取的图片文件")

            except Exception as e:
                logger.warning(f"Notion 图片上传失败: {e}")
                # 降级处理：不使用图片（Notion 不支持 file:// URL）
                pass

        # 使用 V2 版本: 直接从 Markdown 转为 Notion blocks (包含图片)
        from .notion_image_uploader_v2 import markdown_to_notion_blocks_with_images

        final_blocks = markdown_to_notion_blocks_with_images(
            markdown_text,
            image_upload_map,
            images_dir
        )

        logger.info(
            "Markdown 转 Notion blocks 完成",
            total_blocks=len(final_blocks),
            upload_map_size=len(image_upload_map)
        )

        return final_blocks

    except Exception as e:
        logger.error(f"Markdown 转换（含图片）失败: {e}")
        import traceback
        traceback.print_exc()
        # 降级处理：仅返回文本 blocks
        try:
            from .notion_markdown_converter import markdown_to_notion_blocks
            return markdown_to_notion_blocks(markdown_text)
        except:
            return []


def _markdown_to_notion_blocks(markdown_text: str) -> list:
    """
    将 Markdown 转换为 Notion API blocks

    使用 mistletoe 解析 Markdown 并转换为 Notion blocks
    支持：加粗、斜体、删除线、内联代码、嵌套列表等

    Args:
        markdown_text: Markdown 文本

    Returns:
        Notion API blocks 列表
    """
    try:
        # 使用相对导入
        from .notion_markdown_converter import markdown_to_notion_blocks

        blocks = markdown_to_notion_blocks(markdown_text)
        return blocks
    except Exception as e:
        # 如果转换失败，记录错误并返回空列表
        import traceback
        print(f"Markdown转换失败: {e}")
        traceback.print_exc()
        return []


# Digest Agent 定义
digest_agent = Agent(
    name="digest_agent",
    instructions="""你是论文深度整理专家（Digest Agent）。⚡ 仅需 2 次 LLM 调用，大幅加速！

你的职责是接收论文相关信息，完成以下任务：

## 执行流程（仅需 2 次 LLM 调用！）

**第一阶段：获取 PDF 并提取所有元数据**
1. **获取论文内容**
   - 如果提供了小红书 URL，使用 fetch_xiaohongshu_post 获取内容
   - 如果提供了 PDF URL，使用 download_pdf_from_url 下载
   - 如果提供了本地 PDF 路径，使用 read_local_pdf 读取
   - **如果提供了学术网页链接**（academic_page 或 other 类型），使用 extract_paper_info_from_webpage 提取论文信息

2. **搜索论文 PDF**（如果没有提供 PDF URL）
   - 如果从网页提取到了标题但没有PDF，使用标题在 search_arxiv_pdf 搜索
   - 如果网页提取失败，尝试使用 search_arxiv_pdf 搜索（需要先推测标题）
   - 从搜索结果中获取 PDF URL 和 arXiv ID

3. **⚡ 一次 LLM 调用提取所有元数据**（替代旧的两个单独调用）
   - 使用 extract_paper_metadata **一次调用同时提取**：
     * 论文标题（title）
     * 作者（authors）
     * 发表日期（publication_date，YYYY-MM-DD）
     * 期刊/会议（venue）
     * 摘要（abstract）
     * 机构（affiliations）
     * 关键词（keywords）
     * DOI
     * ArXiv ID
     * 项目页（project_page）
     * 其他资源（other_resources）
   - ⚠️ 必须传入 xiaohongshu_content、pdf_content、pdf_metadata

**第二阶段：生成论文整理并保存**
4. **⚡ 一次 LLM 调用生成完整论文整理**
   - 使用 generate_paper_digest 生成结构化的中文论文整理
   - 传入所有提取的元数据
   - 必须包含所有模板章节，内容详细

5. **保存到 Notion**
   - 使用 save_digest_to_notion 保存整理内容和所有元数据
   - ⚠️ **必须传递 extract_paper_metadata 返回的所有字段**：
     * paper_title - 论文标题
     * digest_content - 生成的论文整理内容
     * source_url - 小红书 URL（如果有）
     * pdf_url - PDF 链接
     * authors - 作者列表（JSON 数组字符串）
     * affiliations - 机构
     * publication_date - 完整发表日期（YYYY-MM-DD）
     * venue - 期刊/会议名称
     * abstract - 英文摘要
     * keywords - 关键词列表（JSON 数组字符串）
     * doi - DOI（如果有）
     * arxiv_id - ArXiv ID（如果有）
     * project_page - 项目主页（如果有）
     * other_resources - 其他资源（如果有）

⚠️ 关键要求：
- ✅ **只进行 2 次 LLM 调用**（extract_paper_metadata 一次，generate_paper_digest 一次）
- ✅ 不再使用已删除的函数
- ✅ 必须严格按照顺序执行
- ✅ 每个步骤都要检查结果是否成功
- ✅ 元信息必须准确且完整
- ✅ 调用 save_digest_to_notion 时传递所有字段（特别是 authors 和 keywords 要转为 JSON 数组字符串）
- ❌ 如果某个步骤失败，报告错误并停止

你专注于论文整理工作。
""",
    model=get_reason_model(),
    tools=[
        fetch_xiaohongshu_post,
        extract_paper_info_from_webpage,  # ✨ 新增：从学术网页提取信息
        search_arxiv_pdf,
        download_pdf_from_url,
        read_local_pdf,
        extract_paper_metadata,  # ✨ 新的合并函数（替代旧的两个）
        generate_paper_digest,
        save_digest_to_notion,
    ]
)

"""Xiaohongshu client for post fetching and parsing."""

import asyncio
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..models.post import Post
from ..utils.logger import get_logger
from ..utils.retry import exponential_backoff
from agents import Agent, Runner

# 导入模型
import sys
from pathlib import Path
# 添加项目根目录到 sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from init_model import get_tool_model

logger = get_logger(__name__)


class XiaohongshuError(Exception):
    """Base exception for Xiaohongshu client errors."""
    pass


class AuthenticationError(XiaohongshuError):
    """Raised when authentication fails (cookies expired)."""
    pass


class PostNotFoundError(XiaohongshuError):
    """Raised when post is not found or has been deleted."""
    pass


class RateLimitError(XiaohongshuError):
    """Raised when rate limit is exceeded."""
    pass


class FetchError(XiaohongshuError):
    """Raised when fetching post fails."""
    pass


class RateLimiter:
    """
    Simple rate limiter for HTTP requests.

    Implements token bucket algorithm with request tracking.
    """

    def __init__(self, max_requests: int = 10, period: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per period
            period: Time period in seconds
        """
        self.max_requests = max_requests
        self.period = period
        self.requests: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Acquire permission to make a request.

        Blocks if rate limit would be exceeded.
        """
        async with self._lock:
            now = datetime.now().timestamp()

            # Remove requests outside the current window
            self.requests = [req for req in self.requests if now - req < self.period]

            if len(self.requests) >= self.max_requests:
                # Calculate wait time
                oldest_request = min(self.requests)
                wait_time = self.period - (now - oldest_request)

                if wait_time > 0:
                    logger.warning(
                        "Rate limit reached, waiting",
                        wait_seconds=wait_time,
                        requests_in_window=len(self.requests),
                    )
                    await asyncio.sleep(wait_time)
                    # Recalculate after waiting
                    now = datetime.now().timestamp()
                    self.requests = [req for req in self.requests if now - req < self.period]

            # Record this request
            self.requests.append(now)


class XiaohongshuClient:
    """
    Client for fetching Xiaohongshu posts.

    Uses cookie-based authentication and HTTP requests to fetch
    post content and parse it from HTML.
    """

    def __init__(
        self,
        cookies: str,
        rate_limiter: Optional[RateLimiter] = None,
        timeout: int = 30,
        openai_client=None,  # 新增：用于 Agent 解析
    ):
        """
        Initialize Xiaohongshu client.

        Args:
            cookies: Browser session cookies string
            rate_limiter: Optional rate limiter instance
            timeout: Request timeout in seconds
            openai_client: OpenAI client for LLM-based HTML parsing
        """
        self.cookies = self._parse_cookies(cookies)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.timeout = timeout
        self.openai_client = openai_client

        # Initialize HTTP client
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.xiaohongshu.com/",
            },
            cookies=self.cookies,
        )

    def _parse_cookies(self, cookies_str: str) -> dict[str, str]:
        """
        Parse cookie string into dictionary.

        Args:
            cookies_str: Cookie string from browser

        Returns:
            Dictionary of cookie name-value pairs
        """
        cookies = {}
        for cookie in cookies_str.split(";"):
            cookie = cookie.strip()
            if "=" in cookie:
                name, value = cookie.split("=", 1)
                cookies[name.strip()] = value.strip()
        return cookies

    async def validate_cookies(self) -> bool:
        """
        Validate that cookies are still valid.

        Returns:
            True if cookies are valid, False otherwise
        """
        try:
            response = await self.client.get("https://www.xiaohongshu.com/")

            # Check if redirected to login page
            if "login" in str(response.url):
                return False

            # Check response content for login indicators
            if "登录" in response.text or "login" in response.text.lower():
                return False

            return response.status_code == 200
        except Exception as e:
            logger.error("Cookie validation failed", error=str(e))
            return False

    @exponential_backoff(max_tries=3, exceptions=(httpx.HTTPError,))
    async def fetch_post(self, post_url: str) -> Post:
        """
        Fetch a Xiaohongshu post by URL.

        Args:
            post_url: Full URL to the post

        Returns:
            Post object with fetched content

        Raises:
            AuthenticationError: If cookies are expired
            PostNotFoundError: If post not found
            FetchError: If fetching fails
        """
        # Rate limiting
        await self.rate_limiter.acquire()

        logger.info("Fetching Xiaohongshu post", url=post_url)

        try:
            # Extract post ID from URL
            post_id = self._extract_post_id(post_url)

            # Fetch the page
            response = await self.client.get(post_url)

            # Check for authentication errors
            if "login" in str(response.url):
                raise AuthenticationError("Cookies expired - redirected to login page")

            # Check for 404
            if response.status_code == 404:
                raise PostNotFoundError(f"Post not found: {post_url}")

            # Check for other errors
            response.raise_for_status()

            # Parse the response
            post_data = await self._parse_response(response.text, post_url, post_id)

            logger.info(
                "Post fetched successfully",
                post_id=post_id,
                content_length=len(post_data.get("raw_content", "")),
            )

            return Post(**post_data)

        except (AuthenticationError, PostNotFoundError):
            raise
        except httpx.HTTPError as e:
            raise FetchError(f"HTTP error fetching post: {e}")
        except Exception as e:
            raise FetchError(f"Error fetching post: {e}")

    def _extract_post_id(self, url: str) -> str:
        """
        Extract post ID from Xiaohongshu URL.

        Args:
            url: Xiaohongshu post URL

        Returns:
            Post ID

        Raises:
            ValueError: If URL is invalid
        """
        # Pattern for explore URLs: /explore/{post_id}
        # Pattern for discovery URLs: /discovery/item/{post_id}
        patterns = [
            r"/explore/([a-f0-9]{24})",
            r"/discovery/item/([a-f0-9]{24})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        raise ValueError(f"Could not extract post ID from URL: {url}")

    async def _parse_response(self, html: str, post_url: str, post_id: str) -> dict:
        """
        Parse HTML response to extract post data.

        Uses LLM-based extraction for robust parsing.

        Args:
            html: HTML content
            post_url: Original post URL
            post_id: Post ID

        Returns:
            Dictionary with post data
        """
        soup = BeautifulSoup(html, "lxml")

        # Use LLM-based parsing directly
        return await self._parse_html_fallback(soup, post_url, post_id)

    async def _parse_html_fallback(
        self, soup: BeautifulSoup, post_url: str, post_id: str
    ) -> dict:
        """
        Parse HTML content using LLM-based extraction.

        Uses GPT-5-mini to intelligently extract post content from HTML,
        avoiding brittle regex patterns.

        Args:
            soup: BeautifulSoup object
            post_url: Original post URL
            post_id: Post ID

        Returns:
            Dictionary with post data
        """
        logger.info("Using LLM-based HTML parsing", post_id=post_id)

        # Get clean text from HTML
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        html_text = soup.get_text(separator="\n", strip=True)

        # Extract images
        img_elements = soup.select("img[src]")
        images = [img["src"] for img in img_elements if img.get("src", "").startswith("http")]

        # If no OpenAI client, fall back to basic extraction
        if not self.openai_client:
            logger.warning("No OpenAI client available, using basic extraction")
            return {
                "post_id": post_id,
                "post_url": post_url,
                "blogger_name": "未知博主",
                "blogger_id": "unknown",
                "raw_content": html_text or "Failed to extract content",
                "published_date": None,
                "images": images[:10],
            }

        # Use LLM to extract structured content
        try:
            import json

            # 使用 Agent 替代直接的 LLM 调用
            html_extraction_agent = Agent(
                name="html_extraction_agent",
                instructions="""你是小红书内容提取专家。从HTML文本中提取以下信息：
1. 博主昵称（blogger_name）
2. 帖子正文内容（raw_content）- 完整的帖子文字内容

请以JSON格式返回，格式如下：
{
  "blogger_name": "博主昵称",
  "raw_content": "完整的帖子内容"
}

如果无法找到某个字段，请使用默认值：
- blogger_name: "未知博主"
- raw_content: 提取所有看起来像正文的文字内容
""",
                model=get_tool_model(),
            )

            result = await Runner.run(
                starting_agent=html_extraction_agent,
                input=f"请从以下HTML文本中提取小红书帖子信息：\n\n{html_text[:4000]}",
                max_turns=1
            )

            result_text = result.final_output if hasattr(result, 'final_output') else str(result)
            result_text = result_text.strip()

            # Parse JSON from response
            # Try to extract JSON from markdown code block if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            extracted = json.loads(result_text)

            logger.info("LLM extraction successful", post_id=post_id)

            return {
                "post_id": post_id,
                "post_url": post_url,
                "blogger_name": extracted.get("blogger_name", "未知博主"),
                "blogger_id": "unknown",
                "raw_content": extracted.get("raw_content", html_text or "Failed to extract content"),
                "published_date": None,
                "images": images[:10],
            }

        except Exception as e:
            logger.error("LLM extraction failed, using basic fallback", error=str(e), post_id=post_id)
            return {
                "post_id": post_id,
                "post_url": post_url,
                "blogger_name": "未知博主",
                "blogger_id": "unknown",
                "raw_content": html_text or "Failed to extract content",
                "published_date": None,
                "images": images[:10],
            }

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

"""
Notion 图片上传模块

功能：
1. 上传图片文件到 Notion
2. 生成 image blocks
3. 处理图片引用和转换
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import httpx

logger = logging.getLogger(__name__)


class NotionImageUploader:
    """Notion 图片上传器"""

    def __init__(self, notion_token: str):
        """
        初始化上传器

        Args:
            notion_token: Notion API token
        """
        self.notion_token = notion_token
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    async def upload_image(
        self,
        image_path: str,
        image_filename: Optional[str] = None
    ) -> Dict[str, str]:
        """
        上传单张图片到 Notion

        Args:
            image_path: 本地图片路径
            image_filename: 图片文件名（如果为 None 则使用原文件名）

        Returns:
            {
                "file_upload_id": "...",
                "status": "uploaded",
                "filename": "..."
            }
        """
        image_path = Path(image_path)

        if not image_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {image_path}")

        if image_filename is None:
            image_filename = image_path.name

        # 确定 content_type
        ext_to_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".heic": "image/heic",
            ".webp": "image/webp",
        }

        ext = image_path.suffix.lower()
        content_type = ext_to_mime.get(ext, "image/png")

        file_size = image_path.stat().st_size
        logger.info(f"📤 开始上传图片: {image_filename} ({file_size} bytes)")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: 创建 file upload 对象
                logger.debug("Step 1: 创建 file upload 对象")
                create_response = await client.post(
                    f"{self.base_url}/file_uploads",
                    headers=self.headers,
                    json={
                        "filename": image_filename,
                        "content_type": content_type,
                    }
                )
                create_response.raise_for_status()
                upload_data = create_response.json()

                file_upload_id = upload_data.get("id")
                if not file_upload_id:
                    raise ValueError("创建 file upload 失败：未获得 ID")

                logger.debug(f"File upload ID: {file_upload_id}")

                # Step 2: 上传文件内容
                logger.debug("Step 2: 上传文件内容")
                with open(image_path, "rb") as f:
                    send_response = await client.post(
                        f"{self.base_url}/file_uploads/{file_upload_id}/send",
                        headers={
                            "Authorization": f"Bearer {self.notion_token}",
                            "Notion-Version": "2022-06-28",
                        },
                        files={"file": (image_filename, f, content_type)}
                    )
                    send_response.raise_for_status()

                logger.debug("文件内容上传成功")

                # Step 3: 获取最终状态
                logger.debug("Step 3: 获取最终状态")
                status_response = await client.get(
                    f"{self.base_url}/file_uploads/{file_upload_id}",
                    headers=self.headers
                )
                status_response.raise_for_status()
                final_data = status_response.json()

                status = final_data.get("status", "unknown")
                logger.info(f"✅ 图片上传成功: {image_filename} (ID: {file_upload_id}, status: {status})")

                return {
                    "file_upload_id": file_upload_id,
                    "status": status,
                    "filename": image_filename,
                }

        except Exception as e:
            logger.error(f"❌ 图片上传失败: {e}")
            raise

    async def upload_images_batch(
        self,
        image_paths: List[str]
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        批量上传图片

        Args:
            image_paths: 图片文件路径列表

        Returns:
            (upload_map, failed_paths)
            - upload_map: {filename: file_upload_id}
            - failed_paths: 上传失败的路径列表
        """
        upload_map = {}
        failed_paths = []

        logger.info(f"📤 开始批量上传 {len(image_paths)} 张图片")

        for image_path in image_paths:
            try:
                result = await self.upload_image(image_path)
                upload_map[result["filename"]] = result["file_upload_id"]
            except Exception as e:
                logger.warning(f"⚠️  图片上传失败: {image_path}: {e}")
                failed_paths.append(image_path)

        logger.info(f"✅ 批量上传完成: 成功 {len(upload_map)}, 失败 {len(failed_paths)}")

        return upload_map, failed_paths

    @staticmethod
    def create_image_block(
        file_upload_id: str,
        caption: str = "",
        alt_text: str = ""
    ) -> Dict:
        """
        创建 Notion image block

        Args:
            file_upload_id: Notion 文件上传 ID
            caption: 图片说明文字（可选）
            alt_text: 图片描述文字（可选）

        Returns:
            Notion image block 字典
        """
        block = {
            "type": "image",
            "image": {
                "type": "file_upload",
                "file_upload": {
                    "id": file_upload_id
                },
            }
        }

        # 添加 caption（如果提供）
        if caption:
            block["image"]["caption"] = [
                {
                    "type": "text",
                    "text": {"content": caption[:1000]},  # Notion 限制
                    "annotations": {
                        "bold": False,
                        "italic": True,
                        "strikethrough": False,
                        "underline": False,
                        "code": False,
                        "color": "default"
                    }
                }
            ]

        return block

    @staticmethod
    def create_external_image_block(
        image_url: str,
        caption: str = "",
        alt_text: str = ""
    ) -> Dict:
        """
        创建使用外部 URL 的 image block（不需要上传）

        Args:
            image_url: 图片的公开 URL
            caption: 图片说明文字（可选）
            alt_text: 图片描述文字（可选）

        Returns:
            Notion image block 字典
        """
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {
                    "url": image_url
                },
            }
        }

        # 添加 caption
        if caption:
            block["image"]["caption"] = [
                {
                    "type": "text",
                    "text": {"content": caption[:1000]},
                    "annotations": {
                        "bold": False,
                        "italic": True,
                        "strikethrough": False,
                        "underline": False,
                        "code": False,
                        "color": "default"
                    }
                }
            ]

        return block


def create_image_blocks_from_markdown(
    markdown_content: str,
    image_upload_map: Dict[str, str],
    images_dir: Optional[str] = None
) -> Tuple[str, List[Dict]]:
    """
    从 Markdown 中提取图片引用并创建 Notion image blocks

    新策略：用占位符替换图片，保持精确的顺序信息
    支持两种格式：
    1. HTML <figure> 标签
    2. Markdown ![alt](path) 语法

    Args:
        markdown_content: Markdown 文本
        image_upload_map: {filename: file_upload_id} 映射
        images_dir: 本地图片目录（用于生成备用 URL）

    Returns:
        (cleaned_markdown, image_blocks)
        - cleaned_markdown: 图片替换为占位符的 Markdown
        - image_blocks: Notion image blocks 列表（按顺序）
    """
    import re

    image_blocks = []
    processed_markdown = markdown_content

    # 收集所有图片引用（按出现顺序）
    all_image_refs = []

    # 模式1：HTML figure 标签
    # 支持多种路径格式：./images/xxx, ../pdfs/{title}/extracted_images/xxx
    figure_pattern = r'<figure>\s*<img[^>]*src="[^"]*?/([^/"]+)"[^>]*alt="([^"]*)"[^>]*>\s*<figcaption>([\s\S]*?)</figcaption>\s*</figure>'

    for match in re.finditer(figure_pattern, markdown_content, re.IGNORECASE):
        all_image_refs.append({
            'type': 'figure',
            'start': match.start(),
            'end': match.end(),
            'filename': match.group(1),
            'alt_text': match.group(2).strip(),
            'caption': (match.group(3) or "").strip()
        })

    # 模式2：Markdown 图片语法 ![alt](path)
    # 匹配：![...](attachment:xxx:filename.png) 或 ![...](path/to/filename.png)
    md_image_pattern = r'!\[([^\]]*)\]\((?:attachment:[^:]+:)?([^)]+)\)'

    for match in re.finditer(md_image_pattern, markdown_content):
        path = match.group(2).strip()
        # 提取文件名
        filename = Path(path).name
        alt_caption = match.group(1).strip()

        all_image_refs.append({
            'type': 'markdown',
            'start': match.start(),
            'end': match.end(),
            'filename': filename,
            'alt_text': alt_caption[:100],  # 前100字符作为 alt
            'caption': alt_caption  # 完整文本作为 caption
        })

    # 按位置排序
    all_image_refs.sort(key=lambda x: x['start'])

    # 从后往前处理，避免位置偏移
    matches = all_image_refs

    # 从后往前替换，避免位置偏移
    for idx, img_ref in enumerate(reversed(matches)):
        image_idx = len(matches) - 1 - idx  # 真实的图片索引

        filename = img_ref['filename']
        alt_text = img_ref['alt_text']
        caption = img_ref['caption']
        start_pos = img_ref['start']
        end_pos = img_ref['end']

        # 获取对应的 file_upload_id
        file_upload_id = image_upload_map.get(filename)

        if file_upload_id:
            # 创建 image block
            block = NotionImageUploader.create_image_block(
                file_upload_id=file_upload_id,
                caption=caption,
                alt_text=alt_text
            )
            # 在列表开头插入（因为是倒序处理）
            image_blocks.insert(0, block)

            # 用占位符替换图片标签
            placeholder = f"%%IMAGE_PLACEHOLDER_{image_idx}%%"
            processed_markdown = (
                processed_markdown[:start_pos] +
                placeholder +
                processed_markdown[end_pos:]
            )

            logger.debug(f"✅ 图片 {filename} ({img_ref['type']}) → 占位符 {placeholder}")
        else:
            # 如果不在映射中，检查是否可以使用 file:// URL
            if images_dir:
                local_image_path = Path(images_dir) / filename
                if local_image_path.exists():
                    # 使用本地文件路径作为备选
                    file_url = f"file://{local_image_path.absolute()}"
                    block = NotionImageUploader.create_external_image_block(
                        image_url=file_url,
                        caption=caption,
                        alt_text=alt_text
                    )
                    image_blocks.insert(0, block)

                    placeholder = f"%%IMAGE_PLACEHOLDER_{image_idx}%%"
                    processed_markdown = (
                        processed_markdown[:start_pos] +
                        placeholder +
                        processed_markdown[end_pos:]
                    )

                    logger.debug(f"✅ 使用本地文件 URL: {filename} ({img_ref['type']}) → {placeholder}")
                else:
                    logger.warning(f"⚠️  图片文件不存在: {local_image_path}")
                    # 移除图片标签
                    processed_markdown = (
                        processed_markdown[:start_pos] +
                        processed_markdown[end_pos:]
                    )
            else:
                logger.warning(f"⚠️  图片不在上传映射中: {filename}")
                # 移除图片标签
                processed_markdown = (
                    processed_markdown[:start_pos] +
                    processed_markdown[end_pos:]
                )

    return processed_markdown, image_blocks


def interleave_blocks_with_images(
    text_blocks: List[Dict],
    image_blocks: List[Dict],
    markdown_content: str,
) -> List[Dict]:
    """
    将文本 blocks 和图片 blocks 交错排列，严格按照 Markdown 中的顺序

    新策略：通过占位符精确定位每个图片的位置

    Args:
        text_blocks: 文本 blocks（来自 Markdown 转换，包含占位符）
        image_blocks: 图片 blocks（按顺序）
        markdown_content: 原始 Markdown 文本（未使用，保留参数兼容性）

    Returns:
        混合排列的 blocks 列表
    """
    import re

    result = []
    image_idx = 0

    for block in text_blocks:
        # 检查这个 block 是否包含图片占位符
        block_text = _extract_text_from_block(block)

        if block_text:
            # 查找占位符：%%IMAGE_PLACEHOLDER_N%%
            placeholder_match = re.match(r'%%IMAGE_PLACEHOLDER_(\d+)%%', block_text.strip())

            if placeholder_match:
                # 这是一个占位符 block，替换为对应的图片 block
                placeholder_idx = int(placeholder_match.group(1))

                if placeholder_idx < len(image_blocks):
                    result.append(image_blocks[placeholder_idx])
                    logger.debug(f"✅ 占位符 {placeholder_idx} → 图片 block")
                else:
                    logger.warning(f"⚠️  占位符索引 {placeholder_idx} 超出图片列表范围")
                    # 保留占位符 block（不应该发生）
                    result.append(block)
            else:
                # 普通文本 block
                result.append(block)
        else:
            # 非文本 block（如 divider、code 等）
            result.append(block)

    logger.info(f"✅ 图片与文本交错完成，共 {len(result)} 个 blocks")

    return result


def _extract_text_from_block(block: Dict) -> Optional[str]:
    """
    从 Notion block 中提取纯文本内容

    Args:
        block: Notion block 字典

    Returns:
        提取的文本，如果无法提取则返回 None
    """
    block_type = block.get("type")

    if not block_type:
        return None

    # 段落、标题等
    if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "quote", "callout", "toggle"]:
        rich_text = block.get(block_type, {}).get("rich_text", [])
        if rich_text and len(rich_text) > 0:
            return rich_text[0].get("text", {}).get("content", "")

    # 列表项
    elif block_type in ["bulleted_list_item", "numbered_list_item", "to_do"]:
        rich_text = block.get(block_type, {}).get("rich_text", [])
        if rich_text and len(rich_text) > 0:
            return rich_text[0].get("text", {}).get("content", "")

    # 代码块
    elif block_type == "code":
        rich_text = block.get("code", {}).get("rich_text", [])
        if rich_text and len(rich_text) > 0:
            return rich_text[0].get("text", {}).get("content", "")

    return None

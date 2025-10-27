"""
Notion 图片处理 V2 - 直接从 Markdown 转 Notion blocks

不使用占位符,直接在转换过程中插入图片 blocks
"""

import re
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def markdown_to_notion_blocks_with_images(
    markdown_content: str,
    image_upload_map: Dict[str, str],
    images_dir: Optional[str] = None
) -> List[Dict]:
    """
    将 Markdown 直接转为 Notion blocks (包含图片)

    策略:
    1. 按行分割 Markdown
    2. 逐行处理,遇到图片标签则插入 image block
    3. 其他内容用 mistletoe 转换

    Args:
        markdown_content: Markdown 文本
        image_upload_map: {filename: file_upload_id}
        images_dir: 图片目录

    Returns:
        Notion blocks 列表
    """
    from .notion_markdown_converter import markdown_to_notion_blocks
    from .notion_image_uploader import NotionImageUploader

    # 模式:匹配 HTML figure 标签
    figure_pattern = r'<figure>\s*<img[^>]*src="[^"]*?/([^/"]+)"[^>]*alt="([^"]*)"\s*[^>]*>\s*<figcaption>([\s\S]*?)</figcaption>\s*</figure>'

    # 分段处理: 将 markdown 按图片标签分割
    segments = []
    last_end = 0

    for match in re.finditer(figure_pattern, markdown_content, re.IGNORECASE):
        # 添加图片前的文本段
        if match.start() > last_end:
            text_segment = markdown_content[last_end:match.start()]
            if text_segment.strip():
                segments.append({
                    'type': 'text',
                    'content': text_segment
                })

        # 添加图片段
        filename = match.group(1)
        alt_text = match.group(2).strip()
        caption = (match.group(3) or "").strip()

        segments.append({
            'type': 'image',
            'filename': filename,
            'alt_text': alt_text,
            'caption': caption
        })

        last_end = match.end()

    # 添加最后一段文本
    if last_end < len(markdown_content):
        text_segment = markdown_content[last_end:]
        if text_segment.strip():
            segments.append({
                'type': 'text',
                'content': text_segment
            })

    # 转换为 Notion blocks
    blocks = []

    for segment in segments:
        if segment['type'] == 'text':
            # 文本段 - 用 mistletoe 转换
            text_blocks = markdown_to_notion_blocks(segment['content'])
            blocks.extend(text_blocks)

        elif segment['type'] == 'image':
            # 图片段 - 创建 image block
            filename = segment['filename']
            file_upload_id = image_upload_map.get(filename)

            if file_upload_id:
                block = NotionImageUploader.create_image_block(
                    file_upload_id=file_upload_id,
                    caption=segment['caption'],
                    alt_text=segment['alt_text']
                )
                blocks.append(block)
                logger.debug(f"✅ 插入图片 block: {filename}")
            else:
                # 图片未上传，跳过（Notion 不支持 file:// URL）
                logger.warning(f"⚠️  图片未上传，已跳过: {filename}")

    logger.info(f"✅ Markdown 转 Notion blocks 完成, 共 {len(blocks)} 个 blocks")

    return blocks

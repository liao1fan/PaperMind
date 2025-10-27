"""
智能图片选择模块

功能：
1. 评估论文中每张图片的重要性
2. 根据 caption 和文章内容选择关键图片
3. 返回精选的图片列表（通常 3-8 张最重要的图片）
"""

import logging
from typing import List, Dict, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class ImageSelector:
    """图片重要性评分和选择器"""

    # 重要性关键词
    CRITICAL_KEYWORDS = {
        # 系统架构相关
        'architecture': 3.0,
        'framework': 3.0,
        'model': 2.8,
        'system': 2.8,
        'pipeline': 2.8,
        'workflow': 2.8,

        # 核心方法相关
        'method': 2.5,
        'approach': 2.5,
        'algorithm': 2.5,
        'mechanism': 2.5,
        'design': 2.3,

        # 结果相关
        'result': 2.0,
        'comparison': 2.0,
        'performance': 2.0,
        'experiment': 2.0,
        'evaluation': 2.0,
        'metrics': 1.8,

        # 流程相关
        'process': 1.5,
        'step': 1.3,
        'example': 1.2,
        'case': 1.2,

        # 低优先级
        'chart': 0.8,
        'graph': 0.8,
        'table': 0.8,
        'figure': 0.5,  # 没有更多信息时
    }

    def __init__(self, max_images: int = 6):
        """
        初始化图片选择器

        Args:
            max_images: 最多选择多少张图片（默认 6 张）
        """
        self.max_images = max_images

    def score_image(self, image: Dict) -> float:
        """
        为单张图片评分（综合考虑：caption、图片大小、页码位置）

        Args:
            image: 图片信息字典，包含：
                - caption: 图片说明
                - filename: 文件名
                - page: 页码
                - width/height: 尺寸

        Returns:
            重要性评分 (0-10)
        """
        caption = image.get('caption', '').lower()
        filename = image.get('filename', '').lower()
        width = image.get('width', 0)
        height = image.get('height', 0)

        score = 0.0

        # 优先级 1：图片大小（大图通常更重要）
        if width and height:
            area = width * height
            if area > 1000000:  # 非常大的图 (>1000x1000)
                score += 3.0
            elif area > 500000:  # 大图 (>700x700)
                score += 2.5
            elif area > 300000:  # 中大图
                score += 1.5
            elif area > 100000:  # 中等图
                score += 0.5
            else:
                # 小图片（通常是装饰或不重要的）
                score += 0.1

        # 优先级 2：Caption 内容分析
        if caption:
            score += 0.5  # 有 caption 的基础分

            # 根据 caption 中的关键词加分
            has_critical_keyword = False
            for keyword, weight in self.CRITICAL_KEYWORDS.items():
                if keyword in caption:
                    score += weight
                    has_critical_keyword = True
                    break  # 每张图片只算一个最高权重关键词

            # 根据 caption 长度评估详细程度
            caption_length = len(caption)
            if caption_length > 60:  # 长 caption = 重要内容
                score += 1.0
            elif caption_length > 40:
                score += 0.7
            elif caption_length > 20:
                score += 0.3

        # 优先级 3：页码位置
        page = image.get('page', 999)
        total_pages = image.get('total_pages', 20)

        # 论文早期通常有重要的概述和架构图
        if page <= total_pages * 0.2:  # 前 20%
            score += 1.5
        elif page <= total_pages * 0.35:  # 前 35%（通常是方法章节）
            score += 1.0
        elif page <= total_pages * 0.6:  # 中间（方法和结果）
            score += 0.5

        # 优先级 4：防止重复采样
        # 同一页面的多张小图片（可能是网格式布局）降低评分
        if area < 100000 and caption == "":  # 小图且无 caption
            score *= 0.5  # 减半

        return min(score, 10.0)  # 最高分 10 分

    def select_images(self, images: List[Dict]) -> Tuple[List[Dict], List[float]]:
        """
        从图片列表中选择最重要的图片

        Args:
            images: 所有提取的图片列表

        Returns:
            (选中的图片列表, 对应的评分列表)
        """
        if not images:
            logger.info("📷 没有找到任何图片")
            return [], []

        logger.info(f"📷 开始评分 {len(images)} 张图片...")

        # 为每张图片评分
        scored_images = []
        for i, img in enumerate(images):
            score = self.score_image(img)
            scored_images.append((img, score))
            logger.debug(f"  图片 {i+1}: {img.get('filename', 'unknown')} -> 评分 {score:.2f}")

        # 按评分排序（从高到低）
        scored_images.sort(key=lambda x: x[1], reverse=True)

        # 选择前 N 张
        selected = scored_images[:self.max_images]

        # 按原始顺序重新排列（保持在论文中的顺序）
        selected_dict = {img['filename']: score for img, score in selected}
        selected_in_order = [
            img for img in images
            if img['filename'] in selected_dict
        ]

        selected_scores = [selected_dict[img['filename']] for img in selected_in_order]

        logger.info(
            f"✅ 选择了 {len(selected_in_order)} 张关键图片",
            total_images=len(images),
            selected_count=len(selected_in_order),
            top_3_scores=[f"{score:.2f}" for score, _ in sorted([(s, i) for i, s in enumerate(selected_scores)], reverse=True)[:3]]
        )

        return selected_in_order, selected_scores

    def filter_and_select(
        self,
        images: List[Dict],
        digest_content: str = "",
        max_images: int = None
    ) -> List[Dict]:
        """
        综合评分和内容匹配来选择图片

        Args:
            images: 所有提取的图片
            digest_content: 生成的论文整理内容（用于上下文匹配）
            max_images: 最多选择多少张（覆盖初始化时的值）

        Returns:
            选中的图片列表（按原始顺序）
        """
        if max_images:
            self.max_images = max_images

        # 增加总页数信息（如果有的话）
        total_pages = max(img.get('page', 0) for img in images) if images else 20
        for img in images:
            img['total_pages'] = total_pages

        selected, scores = self.select_images(images)

        # 如果有 digest_content，可以进行进一步的匹配
        # （当前版本使用简单评分，后续可以加入 LLM 匹配）

        return selected


def select_important_images(
    images: List[Dict],
    digest_content: str = "",
    max_images: int = 6
) -> List[Dict]:
    """
    便捷函数：直接选择重要图片

    Args:
        images: 提取的所有图片
        digest_content: 论文整理内容（可选）
        max_images: 最多选择多少张

    Returns:
        选中的重要图片列表
    """
    selector = ImageSelector(max_images=max_images)
    return selector.filter_and_select(images, digest_content, max_images)

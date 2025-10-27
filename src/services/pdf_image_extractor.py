"""
PDF 图片和 Caption 提取模块

功能：
1. 从 PDF 中提取所有图片（保留原始格式）
2. 识别图片位置和关联的 caption
3. 保存图片文件，返回结构化元数据
4. 维护原始 block 顺序用于 Markdown 生成
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import logging

# 尝试导入 PIL 用于图片处理
try:
    from PIL import Image, ImageDraw, ImageChops
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger(__name__)


class PDFImageExtractor:
    """PDF 图片提取器"""

    def __init__(self, output_dir: str = "./paper_digest/images"):
        """
        初始化提取器

        Args:
            output_dir: 图片保存目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.processed_xrefs = set()  # 跟踪已处理的图片 xref，避免重复

    def extract(self, pdf_path: str) -> Tuple[List[Dict], List[Dict]]:
        """
        完整提取：图片文件 + block 顺序信息

        Args:
            pdf_path: PDF 文件路径

        Returns:
            images: 图片元数据列表
                [
                    {
                        "filename": "page1_img0.png",
                        "local_path": "/path/to/page1_img0.png",
                        "page": 1,
                        "xref": 5,
                        "width": 800,
                        "height": 600,
                        "format": "png",
                        "caption": "Figure 1: ...",
                        "bbox": (100, 200, 900, 800)
                    },
                    ...
                ]
            blocks: 按顺序保存的所有 block（文本+图片）
                [
                    {"type": "text", "page": 1, "bbox": (0, 0, 800, 100), "content": "..."},
                    {"type": "image", "page": 1, "bbox": (100, 200, 900, 800), "image_ref": "page1_img0.png"},
                    ...
                ]
        """
        doc = fitz.open(pdf_path)
        all_images = []
        all_blocks = []
        self.processed_xrefs.clear()

        try:
            for page_num in range(len(doc)):
                page = doc[page_num]

                # 获取页面结构化内容
                page_dict = page.get_text("dict")
                page_blocks = page_dict.get("blocks", [])

                # 1. 先扫描一遍找到所有图片，用于 caption 查找
                image_info_map = {}  # xref -> {bbox, ...}
                for block in page_blocks:
                    if block["type"] == 1:  # 图片块
                        xref = block.get("xref")
                        if xref:
                            image_info_map[xref] = block.get("bbox")

                # 2. 遍历所有 block，维护顺序
                for block in page_blocks:
                    bbox = block.get("bbox")

                    if block["type"] == 0:  # 文本块
                        text = self._extract_text_from_block(block)
                        if text.strip():  # 只保存非空文本
                            all_blocks.append({
                                "type": "text",
                                "page": page_num + 1,
                                "bbox": bbox,
                                "content": text
                            })

                    elif block["type"] == 1:  # 图片块
                        # 直接从 block 中获取图片数据
                        if "image" not in block:
                            continue

                        xref = block.get("xref")
                        # 跟踪 xref 避免重复，如果没有 xref 则用索引跟踪
                        block_id = xref if xref else f"page{page_num}_idx{len(all_images)}"
                        if block_id in self.processed_xrefs:
                            continue

                        self.processed_xrefs.add(block_id)

                        # 先查找 caption（在提取图片之前）
                        caption = self._find_caption_for_image(
                            page_blocks,
                            block,
                            page_dict.get("width"),
                            page_dict.get("height")
                        )

                        # 从 block 直接提取图片文件，传递 PDF 文档对象以正确处理颜色空间和 caption
                        img_info = self._extract_image_from_block(block, page_num, doc, caption)
                        if not img_info:
                            continue

                        img_info["caption"] = caption

                        all_images.append(img_info)

                        # 添加到 block 序列
                        all_blocks.append({
                            "type": "image",
                            "page": page_num + 1,
                            "bbox": bbox,
                            "image_ref": img_info["filename"],  # 用于关联
                            "caption": caption
                        })

        finally:
            doc.close()

        logger.info(
            f"✅ PDF 图片提取完成 - 提取 {len(all_images)} 张图片, {len(all_blocks)} 个 blocks"
        )

        return all_images, all_blocks

    def _extract_text_from_block(self, block: Dict) -> str:
        """从文本块提取内容"""
        lines = []
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span.get("text", "")
            if line_text.strip():
                lines.append(line_text.strip())
        return "\n".join(lines)

    def _extract_image_from_block(self, block: Dict, page_num: int, pdf_doc=None, caption: str = "") -> Dict:
        """
        从 block 直接提取单张图片文件，并修复颜色空间问题

        Args:
            block: PyMuPDF 的图片 block 字典
            page_num: 页码（0-indexed）
            pdf_doc: PDF 文档对象，用于正确提取图片
            caption: 图片的 caption（用于生成智能文件名）

        Returns:
            图片元数据字典，如果失败返回 None
        """
        try:
            if "image" not in block:
                return None

            xref = block.get("xref", 0)
            image_ext = block.get("ext", "png")
            width = block.get("width", 0)
            height = block.get("height", 0)

            # 使用 Pixmap 正确提取图片，自动处理颜色空间转换
            image_bytes = None

            if pdf_doc and xref:
                try:
                    # 使用 Pixmap 方法，正确处理 CMYK 等颜色空间
                    pix = fitz.Pixmap(pdf_doc, xref)

                    # 如果是 CMYK 颜色空间，转换为 RGB
                    if pix.n - pix.alpha > 3:  # CMYK: n=4 (或 n=5 with alpha)
                        logger.debug(f"图片是 CMYK 颜色空间 (n={pix.n}), 转换为 RGB")
                        pix = fitz.Pixmap(fitz.csRGB, pix)

                    # 如果有 alpha 通道但不需要，移除它
                    if pix.alpha:
                        logger.debug(f"移除 Alpha 通道")
                        pix = fitz.Pixmap(fitz.csRGB, pix)  # 这会移除 alpha

                    # 转换为 PNG 格式的字节数据
                    image_bytes = pix.tobytes("png")
                    image_ext = "png"  # 统一使用 PNG 格式

                    logger.debug(f"使用 Pixmap 方法提取图片: xref={xref}, colorspace={pix.colorspace}, n={pix.n}")

                    # ⚠️ 关键修复：检测并修复黑色背景（检查四角颜色）
                    if HAS_PIL:
                        image_bytes = self._fix_black_background_by_corners(image_bytes)

                except Exception as e:
                    logger.warning(f"Pixmap 提取失败: {e}，尝试备用方法")
                    try:
                        # 备用：使用 extract_image
                        image_data = pdf_doc.extract_image(xref)
                        if image_data:
                            image_bytes = image_data["image"]
                            if "ext" in image_data:
                                image_ext = image_data["ext"]
                            logger.debug(f"使用 extract_image 备用方法")
                    except Exception as e2:
                        logger.debug(f"extract_image 也失败: {e2}")
                        image_bytes = None

            # 如果上述方法都失败，使用 block 中的图片数据
            if image_bytes is None:
                image_bytes = block["image"]
                logger.debug(f"使用 block 数据提取图片: xref={xref}")

            # 生成智能文件名（基于 caption）
            smart_filename = self._generate_smart_filename(page_num + 1, xref, caption, image_ext)

            # 保存图片文件
            image_path = self.output_dir / smart_filename

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            logger.info(f"✅ 图片已保存: {smart_filename}")

            return {
                "filename": smart_filename,
                "local_path": str(image_path),
                "page": page_num + 1,
                "xref": xref,
                "width": width,
                "height": height,
                "format": image_ext,
                "bbox": block.get("bbox"),
            }

        except Exception as e:
            logger.error(f"提取图片失败: {e}")
            return None

    @staticmethod
    def _generate_smart_filename(page_num: int, xref: int, caption: str, image_ext: str) -> str:
        """
        生成智能的图片文件名（基于 caption 提取关键词）

        命名规则：
        - 如果有 caption 包含 "Figure" 或 "图"：figure{num}_{简要描述}.ext
        - 如果有 caption 包含 "Table" 或 "表"：table{num}_{简要描述}.ext
        - 否则：image{page}_{xref}.ext

        Args:
            page_num: 页码
            xref: 图片 xref
            caption: 图片 caption
            image_ext: 图片格式

        Returns:
            生成的文件名
        """
        import re

        # 清理 caption
        caption_lower = caption.lower().strip()

        # 如果没有 caption，使用默认命名
        if not caption:
            return f"image_page{page_num}_{xref}.{image_ext}"

        try:
            # 识别图片类型和序号
            figure_match = re.search(r'figure\s+(\d+)', caption_lower)
            table_match = re.search(r'table\s+(\d+)', caption_lower)
            fig_match = re.search(r'fig\.?\s+(\d+)', caption_lower)

            prefix = None
            figure_num = None

            if figure_match or fig_match:
                prefix = "figure"
                figure_num = figure_match.group(1) if figure_match else fig_match.group(1)
            elif table_match:
                prefix = "table"
                figure_num = table_match.group(1)
            else:
                # 如果只有 "图" 或 "表"
                if '图' in caption_lower or 'figure' in caption_lower:
                    prefix = "figure"
                elif '表' in caption_lower or 'table' in caption_lower:
                    prefix = "table"

            if not prefix:
                # 没有识别到类型，使用默认
                return f"image_page{page_num}_{xref}.{image_ext}"

            # 提取简要描述（不超过 30 个字符）
            # 移除序号，提取描述部分
            description = re.sub(r'(figure|fig\.|table|图|表)\s*\d*[\s:：]*', '', caption_lower, flags=re.IGNORECASE)
            description = description.strip()

            # 清理特殊字符
            description = re.sub(r'[^a-z0-9\s\u4e00-\u9fff]', '', description)
            description = re.sub(r'\s+', '_', description)
            description = description[:30]  # 限制长度

            if figure_num:
                if description:
                    return f"{prefix}{figure_num}_{description}.{image_ext}"
                else:
                    return f"{prefix}{figure_num}.{image_ext}"
            else:
                if description:
                    return f"{prefix}_{description}.{image_ext}"
                else:
                    return f"{prefix}_page{page_num}_{xref}.{image_ext}"

        except Exception as e:
            logger.debug(f"生成智能文件名失败: {e}, 使用默认命名")
            return f"image_page{page_num}_{xref}.{image_ext}"

    @staticmethod
    def _fix_black_background_by_corners(image_bytes: bytes) -> bytes:
        """
        通过检测四个角的颜色来判断是否需要反转图片（黑色背景 → 白色背景）

        Args:
            image_bytes: 图片字节数据

        Returns:
            修复后的图片字节数据（如果不需要修复则返回原始数据）
        """
        if not HAS_PIL:
            return image_bytes

        try:
            from io import BytesIO
            import numpy as np

            # 打开图片
            img = Image.open(BytesIO(image_bytes)).convert('RGB')
            img_array = np.array(img)
            h, w = img_array.shape[:2]

            # 采样四个角（每个角取 10x10 像素区域）
            sample_size = min(10, h // 10, w // 10)  # 动态调整采样大小
            if sample_size < 3:
                # 图片太小，不检测
                return image_bytes

            corners = {
                '左上': img_array[0:sample_size, 0:sample_size],
                '右上': img_array[0:sample_size, w-sample_size:w],
                '左下': img_array[h-sample_size:h, 0:sample_size],
                '右下': img_array[h-sample_size:h, w-sample_size:w]
            }

            # 检查所有角是否都是黑色（RGB < 50）
            black_corners = 0
            for name, corner in corners.items():
                avg_color = corner.mean(axis=(0, 1))
                r, g, b = avg_color
                if r < 50 and g < 50 and b < 50:
                    black_corners += 1

            # 如果至少 3 个角是黑色，判定为黑色背景，需要反转
            if black_corners >= 3:
                logger.info(f"🔧 检测到黑色背景（{black_corners}/4 个角是黑色），进行颜色反转...")

                # 反转颜色
                inverted = ImageChops.invert(img)

                # 验证反转后的结果
                inv_array = np.array(inverted)
                inv_corners = {
                    '左上': inv_array[0:sample_size, 0:sample_size],
                    '右上': inv_array[0:sample_size, w-sample_size:w],
                    '左下': inv_array[h-sample_size:h, 0:sample_size],
                    '右下': inv_array[h-sample_size:h, w-sample_size:w]
                }

                white_corners = 0
                for corner in inv_corners.values():
                    avg_color = corner.mean(axis=(0, 1))
                    if avg_color.mean() > 200:  # 反转后应该是白色
                        white_corners += 1

                if white_corners >= 3:
                    logger.info(f"✅ 颜色反转成功！背景已从黑色变为白色")
                    output = BytesIO()
                    inverted.save(output, format='PNG')
                    return output.getvalue()
                else:
                    logger.warning(f"⚠️  反转后背景仍不是白色，保持原始图片")
                    return image_bytes
            else:
                logger.debug(f"背景正常（{black_corners}/4 个角是黑色），无需反转")
                return image_bytes

        except Exception as e:
            logger.warning(f"背景检测失败: {e}，使用原始图片")
            return image_bytes

    @staticmethod
    def _fix_black_background_at_source(image_bytes: bytes, image_ext: str, image_data: Dict = None) -> Tuple[bytes, bool]:
        """
        在源头修复黑色背景问题（更深层的颜色空间处理）

        当 PDF 中的某些图片提取出来是全黑时，可能是：
        1. CMYK 颜色空间需要转换为 RGB
        2. Alpha 通道被反转或忽略
        3. 图片使用了特殊的索引颜色或颜色表
        4. 颜色空间编码不匹配

        Args:
            image_bytes: 图片原始数据
            image_ext: 图片格式
            image_data: PyMuPDF extract_image 返回的完整数据（包含颜色空间信息）

        Returns:
            (修复后的图片字节数据, 是否进行了修复)
        """
        if not HAS_PIL:
            return image_bytes, False

        try:
            from io import BytesIO
            import numpy as np

            # 打开图片
            img = Image.open(BytesIO(image_bytes))
            original_mode = img.mode

            logger.debug(f"图片模式: {original_mode}, 大小: {img.size}")

            # 检查是否是全黑或几乎全黑
            img_rgb = img.convert('RGB')
            img_array = np.array(img_rgb)
            avg_brightness = img_array.mean()

            # 如果平均亮度太低（接近黑色），尝试修复
            if avg_brightness < 30:
                logger.warning(f"检测到全黑图片 (亮度={avg_brightness:.1f}), 尝试修复颜色空间...")

                # 策略 1: CMYK → RGB 转换
                if original_mode == 'CMYK':
                    try:
                        logger.info("尝试 CMYK → RGB 转换...")
                        img_rgb = img.convert('RGB')
                        img_array = np.array(img_rgb)
                        new_brightness = img_array.mean()
                        if new_brightness > 100:
                            logger.info(f"✅ CMYK 转换成功 (亮度从 {avg_brightness:.1f} → {new_brightness:.1f})")
                            output = BytesIO()
                            img_rgb.save(output, format=image_ext.upper())
                            return output.getvalue(), True
                    except Exception as e:
                        logger.debug(f"CMYK 转换失败: {e}")

                # 策略 2: 反转颜色（可能是 Alpha 通道或颜色反转）
                try:
                    logger.info("尝试颜色反转...")
                    inverted = ImageChops.invert(img_rgb)
                    inverted_array = np.array(inverted)
                    inverted_brightness = inverted_array.mean()

                    if inverted_brightness > 100:
                        logger.info(f"✅ 颜色反转成功 (亮度从 {avg_brightness:.1f} → {inverted_brightness:.1f})")
                        output = BytesIO()
                        inverted.save(output, format=image_ext.upper())
                        return output.getvalue(), True
                except Exception as e:
                    logger.debug(f"颜色反转失败: {e}")

                # 策略 3: 提取 Alpha 通道
                if original_mode in ['RGBA', 'LA', 'PA']:
                    try:
                        logger.info(f"尝试从 {original_mode} 中提取 Alpha 通道...")
                        if original_mode == 'RGBA':
                            alpha = img.split()[3]
                        elif original_mode == 'LA':
                            alpha = img.split()[1]
                        elif original_mode == 'PA':
                            # 先转换为 RGBA
                            img_rgba = img.convert('RGBA')
                            alpha = img_rgba.split()[3]

                        alpha_array = np.array(alpha)
                        alpha_brightness = alpha_array.mean()

                        if alpha_brightness > 100:
                            logger.info(f"✅ Alpha 通道亮度足够 ({alpha_brightness:.1f}), 使用作为主图")
                            alpha_rgb = Image.new('RGB', alpha.size, 'white')
                            alpha_rgb.paste(alpha)
                            output = BytesIO()
                            alpha_rgb.save(output, format=image_ext.upper())
                            return output.getvalue(), True
                    except Exception as e:
                        logger.debug(f"Alpha 通道提取失败: {e}")

                # 策略 4: 色域自适应调整（灵活处理各种情况）
                try:
                    logger.info("尝试色域自适应调整...")
                    img_data_array = np.array(img_rgb).astype(float)

                    # 计算每个通道的亮度
                    r_mean, g_mean, b_mean = img_data_array[:, :, 0].mean(), img_data_array[:, :, 1].mean(), img_data_array[:, :, 2].mean()
                    logger.debug(f"RGB 均值: R={r_mean:.1f}, G={g_mean:.1f}, B={b_mean:.1f}")

                    # 如果任何通道的值都很低，尝试反向的 CMYK 处理
                    if r_mean < 50 and g_mean < 50 and b_mean < 50:
                        # 尝试类似 CMYK 反转的逻辑
                        adjusted = 255 - img_data_array
                        adjusted = np.clip(adjusted, 0, 255).astype(np.uint8)
                        adjusted_img = Image.fromarray(adjusted, 'RGB')
                        adjusted_array = np.array(adjusted_img)
                        adjusted_brightness = adjusted_array.mean()

                        if adjusted_brightness > 150:
                            logger.info(f"✅ 色域调整成功 (亮度从 {avg_brightness:.1f} → {adjusted_brightness:.1f})")
                            output = BytesIO()
                            adjusted_img.save(output, format=image_ext.upper())
                            return output.getvalue(), True
                except Exception as e:
                    logger.debug(f"色域调整失败: {e}")

            return image_bytes, False

        except Exception as e:
            logger.warning(f"图片颜色修复失败: {e}, 使用原始数据")
            return image_bytes, False

    @staticmethod
    def _fix_black_background_image(image_bytes: bytes, image_ext: str) -> bytes:
        """
        修复全黑背景的图片（PDF 颜色空间问题）

        【注意】这是旧版本，已被 _fix_black_background_at_source 替代
        保留用于后向兼容性

        Args:
            image_bytes: 图片原始数据
            image_ext: 图片格式

        Returns:
            修复后的图片字节数据（如果修复失败则返回原始数据）
        """
        fixed_bytes, _ = PDFImageExtractor._fix_black_background_at_source(image_bytes, image_ext)
        return fixed_bytes

    def _find_caption_for_image(
        self,
        blocks: List[Dict],
        image_block: Dict,
        page_width: float = 595,  # A4 默认宽度
        page_height: float = 842   # A4 默认高度
    ) -> str:
        """
        查找图片的 caption（启发式方法）

        启发式规则：
        1. Caption 通常在图片正下方
        2. 垂直距离 < 50 像素
        3. 包含 "Figure", "Fig.", "图", "Table", "表" 等关键词
        4. 水平对齐：至少 50% 重叠
        """
        img_bbox = image_block.get("bbox", (0, 0, 0, 0))
        img_x0, img_y0, img_x1, img_y1 = img_bbox

        caption_candidates = []

        for block in blocks:
            if block["type"] != 0:  # 不是文本块
                continue

            text_bbox = block.get("bbox", (0, 0, 0, 0))
            text_x0, text_y0, text_x1, text_y1 = text_bbox

            # 检查文本是否在图片正下方
            is_below = text_y0 >= img_y1
            vertical_distance = text_y0 - img_y1 if is_below else float('inf')

            # 距离阈值：50 像素
            if not is_below or vertical_distance > 50:
                continue

            # 检查水平对齐（至少 50% 重叠）
            horizontal_overlap = min(img_x1, text_x1) - max(img_x0, text_x0)
            image_width = img_x1 - img_x0
            overlap_ratio = horizontal_overlap / image_width if image_width > 0 else 0

            if overlap_ratio < 0.5:
                continue

            # 提取文本内容（需要从 lines/spans 结构中提取）
            text = self._extract_text_from_block(block)
            if not text.strip():
                continue

            # 检查是否包含 caption 关键词
            text_lower = text.lower()
            caption_keywords = ["figure", "fig.", "图", "table", "表", "图表"]

            has_keyword = any(kw in text_lower for kw in caption_keywords)
            if not has_keyword:
                continue

            # 是一个候选 caption
            caption_candidates.append({
                "text": text,
                "distance": vertical_distance,
                "overlap_ratio": overlap_ratio,
            })

        # 选择最佳候选（距离最近的）
        if caption_candidates:
            best_caption = min(caption_candidates, key=lambda x: x["distance"])
            return best_caption["text"].strip()

        return ""

    def to_json(self, images: List[Dict], output_file: str = None) -> str:
        """
        将提取的图片信息保存为 JSON

        Args:
            images: 图片元数据列表
            output_file: 输出文件路径，如果为 None，输出到 output_dir/images.json

        Returns:
            JSON 字符串
        """
        if output_file is None:
            output_file = self.output_dir / "images.json"

        output_file = Path(output_file)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(images, f, ensure_ascii=False, indent=2)

        logger.info(f"图片元数据已保存到: {output_file}")

        return json.dumps(images, ensure_ascii=False, indent=2)


# ========== 便捷函数 ==========

def extract_pdf_images(pdf_path: str, output_dir: str = None) -> Tuple[List[Dict], List[Dict]]:
    """
    便捷函数：一行代码提取 PDF 图片

    Args:
        pdf_path: PDF 文件路径
        output_dir: 图片保存目录，如果为 None 使用默认值

    Returns:
        (images, blocks)
    """
    if output_dir is None:
        output_dir = "./paper_digest/images"

    extractor = PDFImageExtractor(output_dir)
    return extractor.extract(pdf_path)

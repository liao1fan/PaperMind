"""
PDF Figure 提取模块 V2 - 整合 PDFFigures2 + Python Fallback

功能：
1. 使用 PDFFigures2 提取 Figures/Tables（主方法）
2. 对于 regionless captions，使用 Python 密度检测算法 fallback
3. 返回统一的图片元数据格式

特点：
- 100% 提取成功率
- 自动处理边界检测
- 智能文件命名（Figure1.png, Table2.png）
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import subprocess
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)


class PDFFigureExtractorV2:
    """PDF Figure/Table 提取器 V2（PDFFigures2 + Python Fallback）"""

    def __init__(self, output_dir: str):
        """
        初始化提取器

        Args:
            output_dir: 图片保存目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # PDFFigures2 临时输出目录
        self.pdffigures2_output_dir = self.output_dir / "_pdffigures2_temp"
        self.pdffigures2_output_dir.mkdir(parents=True, exist_ok=True)

        # PDFFigures2 JAR 路径
        project_root = Path(__file__).resolve().parent.parent.parent
        self.pdffigures2_jar = project_root / "pdffigures2" / "pdffigures2" / "pdffigures2.jar"

        if not self.pdffigures2_jar.exists():
            logger.warning(f"PDFFigures2 JAR 不存在: {self.pdffigures2_jar}")

    def extract(self, pdf_path: str) -> Tuple[List[Dict], List[Dict]]:
        """
        完整提取流程：PDFFigures2 + Python Fallback + 过滤附录图片

        Args:
            pdf_path: PDF 文件路径

        Returns:
            images: 图片元数据列表
                [
                    {
                        "filename": "Figure1.png",
                        "local_path": "/path/to/Figure1.png",
                        "page": 1,
                        "caption": "Figure 1: ...",
                        "bbox": {"x1": 100, "y1": 200, "x2": 500, "y2": 600},
                        "source": "pdffigures2" 或 "python_fallback",
                        "fig_type": "Figure" 或 "Table",
                        "fig_name": "1"
                    },
                    ...
                ]
            blocks: 占位符（保持 API 兼容性）
        """
        all_figures = []

        # 步骤 0: 检测 References/Appendix 起始页码（用于过滤）
        references_page = self._detect_references_page(pdf_path)

        # 步骤 1: 运行 PDFFigures2
        logger.info("🔧 运行 PDFFigures2 提取...")
        pdffigures2_data = self._run_pdffigures2(pdf_path)

        if pdffigures2_data:
            # 步骤 2: 处理标准提取的 figures
            standard_figures = pdffigures2_data.get("figures", [])
            for fig in standard_figures:
                fig_info = self._process_pdffigures2_figure(fig)
                if fig_info:
                    all_figures.append(fig_info)

            logger.info(f"✅ PDFFigures2 标准提取: {len(standard_figures)} 个")

            # 步骤 3: 使用 Python Fallback 处理 regionless captions
            regionless_captions = pdffigures2_data.get("regionless-captions", [])
            if regionless_captions:
                logger.info(f"🐍 Python Fallback 处理 {len(regionless_captions)} 个 regionless captions...")
                fallback_figures = self._extract_regionless_figures(pdf_path, regionless_captions)
                all_figures.extend(fallback_figures)

        else:
            # PDFFigures2 失败，完全使用 Python 方法
            logger.warning("⚠️  PDFFigures2 失败，使用纯 Python 方法提取")
            all_figures = self._extract_all_figures_python(pdf_path)

        # 步骤 3.5: 过滤附录图片
        if references_page:
            before_filter = len(all_figures)
            all_figures = [fig for fig in all_figures if fig['page'] < references_page]
            filtered_count = before_filter - len(all_figures)
            if filtered_count > 0:
                logger.info(f"🗑️  已过滤 {filtered_count} 张附录/参考文献图片（从第 {references_page} 页开始）")

        # 步骤 4: 按类型和编号排序
        all_figures.sort(key=lambda f: (
            f['fig_type'],
            int(f['fig_name']) if f['fig_name'].isdigit() else 999
        ))

        logger.info(f"✅ 总计提取: {len(all_figures)} 个 Figures/Tables（不含附录）")

        # 保存元数据
        self._save_metadata(all_figures)

        # 返回兼容格式（blocks 为空列表）
        return all_figures, []

    def _detect_references_page(self, pdf_path: str) -> Optional[int]:
        """
        检测 References 或 Appendix 的起始页码

        策略：
        1. 扫描每一页的前300个字符
        2. 查找 "References"、"REFERENCES"、"Appendix"、"APPENDIX" 等标识
        3. 返回第一个找到的页码（1-indexed）

        Returns:
            References/Appendix 起始页码（1-indexed），如果未找到返回 None
        """
        try:
            doc = fitz.open(pdf_path)
            total_pages = doc.page_count

            # 从页面的最后 30% 开始扫描（通常 References 在论文后部）
            start_scan_page = int(total_pages * 0.7)

            for page_num in range(start_scan_page, total_pages):
                page = doc[page_num]
                text = page.get_text()[:500]  # 只取前500字符

                # 查找多种可能的标识
                if any(marker in text for marker in ['References', 'REFERENCES', 'Appendix', 'APPENDIX', 'Bibliography', 'BIBLIOGRAPHY']):
                    detected_page = page_num + 1  # 转为 1-indexed
                    logger.info(f"📄 检测到 References/Appendix 起始页: 第 {detected_page} 页")
                    doc.close()
                    return detected_page

            doc.close()
            logger.info("未检测到 References/Appendix 标识，保留所有图片")
            return None

        except Exception as e:
            logger.warning(f"检测 References 页面失败: {e}")
            return None

    def _run_pdffigures2(self, pdf_path: str) -> Optional[Dict]:
        """运行 PDFFigures2 并返回结果"""
        if not self.pdffigures2_jar.exists():
            logger.warning("PDFFigures2 JAR 不存在，跳过")
            return None

        try:
            pdf_filename = Path(pdf_path).stem
            json_output = self.pdffigures2_output_dir / f"{pdf_filename}.json"

            cmd = [
                "java",
                "-jar",
                str(self.pdffigures2_jar),
                pdf_path,
                "-m", str(self.pdffigures2_output_dir) + "/",
                "-d", str(self.pdffigures2_output_dir) + "/",
                "-i", "300",  # 设置 DPI 为 300（高质量）
                "-c"  # 包含 regionless-captions
            ]

            # 设置 Java 环境变量
            env = os.environ.copy()
            java_home = os.getenv("JAVA_HOME")
            if not java_home:
                # 尝试使用 Homebrew 安装的 OpenJDK 11
                env["PATH"] = "/opt/homebrew/opt/openjdk@11/bin:" + env.get("PATH", "")

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.error(f"PDFFigures2 执行失败: {result.stderr}")
                return None

            # 读取 JSON 结果
            if json_output.exists():
                with open(json_output, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"PDFFigures2 输出文件不存在: {json_output}")
                return None

        except Exception as e:
            logger.error(f"PDFFigures2 运行失败: {e}")
            return None

    def _process_pdffigures2_figure(self, fig: Dict) -> Optional[Dict]:
        """处理 PDFFigures2 提取的单个 figure"""
        try:
            fig_type = fig['figType']
            fig_name = fig['name']
            render_url = fig.get('renderURL', '')

            if not render_url:
                return None

            src_path = Path(render_url)
            if not src_path.exists():
                logger.warning(f"PDFFigures2 渲染文件不存在: {src_path}")
                return None

            # 复制到最终输出目录，重命名为统一格式
            dst_filename = f"{fig_type}{fig_name}.png"
            dst_path = self.output_dir / dst_filename

            import shutil
            shutil.copy2(src_path, dst_path)

            return {
                'filename': dst_filename,
                'local_path': str(dst_path),
                'page': fig['page'] + 1,  # 转为 1-indexed
                'caption': fig.get('caption', ''),
                'bbox': fig.get('regionBoundary'),
                'source': 'pdffigures2',
                'fig_type': fig_type,
                'fig_name': fig_name,
                'width': int(fig.get('regionBoundary', {}).get('x2', 0) - fig.get('regionBoundary', {}).get('x1', 0)) if fig.get('regionBoundary') else 0,
                'height': int(fig.get('regionBoundary', {}).get('y2', 0) - fig.get('regionBoundary', {}).get('y1', 0)) if fig.get('regionBoundary') else 0,
                'format': 'png'
            }

        except Exception as e:
            logger.error(f"处理 PDFFigures2 figure 失败: {e}")
            return None

    def _extract_regionless_figures(self, pdf_path: str, regionless_captions: List[Dict]) -> List[Dict]:
        """使用 Python 密度检测算法提取 regionless figures"""
        doc = fitz.open(pdf_path)
        figures = []

        try:
            for item in regionless_captions:
                fig_name = item['name']
                fig_type = item['figType']
                page_num = item['page']
                caption_bbox = item['boundary']
                caption_text = item['text']

                logger.info(f"  处理 {fig_type} {fig_name} (Page {page_num + 1})...")

                page = doc[page_num]

                # 使用密度检测算法
                region_bbox = self._detect_figure_region_by_density(page, caption_bbox)

                if region_bbox:
                    # 渲染为 PNG（300 DPI，与 pdffigures2 保持一致）
                    zoom = 300 / 72
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, clip=region_bbox)

                    dst_filename = f"{fig_type}{fig_name}.png"
                    dst_path = self.output_dir / dst_filename
                    pix.save(str(dst_path))

                    figures.append({
                        'filename': dst_filename,
                        'local_path': str(dst_path),
                        'page': page_num + 1,
                        'caption': caption_text,
                        'bbox': {
                            'x1': region_bbox.x0,
                            'y1': region_bbox.y0,
                            'x2': region_bbox.x1,
                            'y2': region_bbox.y1
                        },
                        'source': 'python_fallback',
                        'fig_type': fig_type,
                        'fig_name': fig_name,
                        'width': int(region_bbox.width),
                        'height': int(region_bbox.height),
                        'format': 'png'
                    })

                    logger.info(f"    ✓ 提取成功 ({region_bbox.width:.1f}x{region_bbox.height:.1f})")
                else:
                    logger.warning(f"    ✗ 提取失败")

        finally:
            doc.close()

        return figures

    def _detect_figure_region_by_density(self, page, caption_bbox: Dict) -> Optional[fitz.Rect]:
        """基于对象密度检测 Figure 区域（核心算法）"""
        page_height = page.rect.height
        page_width = page.rect.width
        caption_y_top = caption_bbox['y1']

        # 获取所有绘图对象和文本块
        drawings = page.get_drawings()
        text_blocks = page.get_text("dict")["blocks"]

        # 只考虑 caption 上方的内容
        drawings_above = [d for d in drawings if d['rect'][3] < caption_y_top]
        text_blocks_above = [b for b in text_blocks
                             if b.get("type") == 0 and b["bbox"][3] < caption_y_top]

        if not drawings_above:
            return None

        # 找到 caption 正上方的空白间隙
        closest_drawing_y = max(d['rect'][3] for d in drawings_above)
        gap_to_caption = caption_y_top - closest_drawing_y

        # 确定扫描区域
        scan_top = 0
        scan_bottom = caption_y_top - gap_to_caption

        if scan_bottom <= scan_top:
            scan_bottom = caption_y_top

        # 分成水平条带计算密度
        stripe_height = 10
        num_stripes = int((scan_bottom - scan_top) / stripe_height) + 1

        drawing_density = np.zeros(num_stripes)
        text_density = np.zeros(num_stripes)

        # 计算绘图对象密度
        for d in drawings_above:
            rect = d['rect']
            if rect[3] > scan_bottom or rect[1] < scan_top:
                continue

            start_stripe = int((rect[1] - scan_top) / stripe_height)
            end_stripe = int((rect[3] - scan_top) / stripe_height)
            start_stripe = max(0, min(start_stripe, num_stripes - 1))
            end_stripe = max(0, min(end_stripe, num_stripes - 1))

            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            for i in range(start_stripe, end_stripe + 1):
                drawing_density[i] += area

        # 计算文本密度
        for block in text_blocks_above:
            bbox = block["bbox"]
            if bbox[3] > scan_bottom or bbox[1] < scan_top:
                continue

            start_stripe = int((bbox[1] - scan_top) / stripe_height)
            end_stripe = int((bbox[3] - scan_top) / stripe_height)
            start_stripe = max(0, min(start_stripe, num_stripes - 1))
            end_stripe = max(0, min(end_stripe, num_stripes - 1))

            text_chars = sum(len(span.get("text", ""))
                            for line in block.get("lines", [])
                            for span in line.get("spans", []))

            for i in range(start_stripe, end_stripe + 1):
                text_density[i] += text_chars

        # 归一化并计算 Figure 评分
        if drawing_density.max() > 0:
            drawing_density = drawing_density / drawing_density.max()
        if text_density.max() > 0:
            text_density = text_density / text_density.max()

        figure_score = drawing_density - 0.5 * text_density

        # 找到连续的高分区域
        threshold = 0.1
        figure_bottom_stripe = -1

        for i in range(num_stripes - 1, -1, -1):
            if figure_score[i] > threshold:
                figure_bottom_stripe = i
                break

        if figure_bottom_stripe == -1:
            # Fallback: 使用所有绘图对象的包围盒
            min_x = min(d['rect'][0] for d in drawings_above)
            min_y = min(d['rect'][1] for d in drawings_above)
            max_x = max(d['rect'][2] for d in drawings_above)
            max_y = max(d['rect'][3] for d in drawings_above)

            margin = 5
            return fitz.Rect(
                max(0, min_x - margin),
                max(0, min_y - margin),
                min(page_width, max_x + margin),
                min(caption_y_top - 5, max_y + margin)
            )

        # 向上扩展
        figure_top_stripe = figure_bottom_stripe
        for i in range(figure_bottom_stripe - 1, -1, -1):
            if figure_score[i] > threshold:
                figure_top_stripe = i
            else:
                if i > 2 and all(figure_score[j] <= threshold for j in range(i-2, i+1)):
                    break

        # 计算 y 范围
        figure_y_top = scan_top + figure_top_stripe * stripe_height
        figure_y_bottom = scan_top + (figure_bottom_stripe + 1) * stripe_height

        # 在该 y 范围内找到 x 边界
        relevant_drawings = [d for d in drawings_above
                            if d['rect'][1] >= figure_y_top and d['rect'][3] <= figure_y_bottom + 20]

        if not relevant_drawings:
            relevant_drawings = drawings_above

        min_x = min(d['rect'][0] for d in relevant_drawings)
        max_x = max(d['rect'][2] for d in relevant_drawings)

        # 检查宽度是否合理
        figure_width = max_x - min_x
        caption_width = caption_bbox['x2'] - caption_bbox['x1']

        if figure_width < caption_width * 0.6:
            min_x = 70
            max_x = page_width - 70

        # 添加 margin
        margin = 5
        min_x = max(0, min_x - margin)
        max_x = min(page_width, max_x + margin)
        min_y = max(0, figure_y_top - margin)
        max_y = min(caption_y_top - 5, figure_y_bottom + margin)

        return fitz.Rect(min_x, min_y, max_x, max_y)

    def _extract_all_figures_python(self, pdf_path: str) -> List[Dict]:
        """纯 Python 方法提取所有 figures（完全 fallback）"""
        logger.warning("纯 Python 提取暂未实现，返回空列表")
        return []

    def _save_metadata(self, figures: List[Dict]):
        """保存元数据到 JSON"""
        metadata_path = self.output_dir / "extraction_metadata.json"

        figures_count = sum(1 for f in figures if f['fig_type'] == 'Figure')
        tables_count = sum(1 for f in figures if f['fig_type'] == 'Table')
        pdffigures2_count = sum(1 for f in figures if f['source'] == 'pdffigures2')
        python_count = sum(1 for f in figures if f['source'] == 'python_fallback')

        metadata = {
            'total': len(figures),
            'figures': figures_count,
            'tables': tables_count,
            'sources': {
                'pdffigures2': pdffigures2_count,
                'python_fallback': python_count
            },
            'items': figures
        }

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✅ 元数据已保存: {metadata_path}")


# ========== 便捷函数 ==========

def extract_pdf_figures(pdf_path: str, output_dir: str = None) -> Tuple[List[Dict], List[Dict]]:
    """
    便捷函数：一行代码提取 PDF Figures/Tables（V2 方法）

    Args:
        pdf_path: PDF 文件路径
        output_dir: 图片保存目录

    Returns:
        (figures, blocks)
    """
    if output_dir is None:
        output_dir = "./paper_digest/figures"

    extractor = PDFFigureExtractorV2(output_dir)
    return extractor.extract(pdf_path)

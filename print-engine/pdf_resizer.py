"""
PDF格式化模块 - 基于内容边界的智能格式化
用于将PDF缩放到标准尺寸（A4/A5/B5��

版本：V2.0
创建日期：2026-03-18
更新日期：2026-03-19

核心功能：
  - 智能检测每页实际内容边界（文字+图片）
  - 自动裁剪白边
  - 非等比拉伸充满目标页面（无白边、无裁切、可能变形）
  - 格式化前自动备份，失败时自动恢复
  - 支持进度回调，实时推送处理进度
  - 智能检测：已是目标尺寸时跳过处理

技术方案：
  - 使用 PyMuPDF (fitz) 检测内容边界
  - 使用 get_pixmap() 将内容区域渲染为图片
  - 使用 insert_image(keep_proportion=False) 实现非等比拉伸
  - 确保内容100%充满目标页面，无任何白边

安全机制：
  - 格式化前创建带时间戳的备份文件
  - 格式化成��后自动删除备份
  - 格式化失败时自动恢复备份
"""

import io
import os
import shutil
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, Any

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logging.warning("PyMuPDF 未安装，将使用 PyPDF2 备用方案（功能受限）")

from PyPDF2 import PdfReader

try:
    import numpy as np
    from PIL import Image
    HAS_IMAGE_LIBS = True
except ImportError:
    HAS_IMAGE_LIBS = False
    logging.warning("PIL/numpy 未安装，双页检测功能将被禁用")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 标准尺寸定义（mm）
STANDARD_SIZES = {
    'A4': (210, 297),
    'A5': (148, 210),
    'B5': (176, 250)
}

# 尺寸匹配容差（mm）
SIZE_TOLERANCE = 2.0

# 白边检测阈值（mm）- 边距小于此值视为充满
MARGIN_THRESHOLD = 5.0

# 双页检测阈值
CENTER_WIDTH_RATIO = 0.10  # 中间区域宽度占比
BRIGHTNESS_THRESHOLD = 1.15  # 中间/两侧亮度比阈值

# 文档级基线检测参数
BASELINE_WIDTH_TOLERANCE = 0.15  # 宽度聚类容差（±15%）
BASELINE_HEIGHT_TOLERANCE = 0.15  # 高度聚类容差（±15%）
WIDE_PAGE_RATIO_MIN = 1.7  # 双页候选最小宽度倍数（放宽到1.7x）
WIDE_PAGE_RATIO_MAX = 4.0  # 双页候选最大宽度倍数（放宽到4.0x）
HEIGHT_MATCH_TOLERANCE = 0.20  # 高度匹配容差（±20%）
LANDSCAPE_DOC_THRESHOLD = 0.4  # 景观文档阈值（>40%页面为宽页时判定为横向文档）


class PdfResizer:
    """
    PDF格式化器

    核心逻辑：
    1. 检测每页内容的实际边界（去除白边）
    2. 裁剪到内容边界
    3. 非等比拉伸到目标尺寸（充满整个页面）
    """

    def __init__(self, book_path: str, target_size: str, progress_callback=None):
        """
        初始化PDF格式化器

        Args:
            book_path: 书籍文件路径（不含.pdf后缀或含.pdf后缀均可）
            target_size: 目标尺寸（A4/A5/B5，不区分大小写）
            progress_callback: 进度回调函数，接收dict参数：
                {
                    "progress": 0-100,  # 进度百分比
                    "stage": "当前阶段描述",
                    "current_page": 当前页码（可选）,
                    "total_pages": 总页数（可选）
                }

        Raises:
            ValueError: 目标尺寸不支持
            RuntimeError: PyMuPDF 未安装
        """
        if not HAS_PYMUPDF:
            raise RuntimeError(
                "PDF格式化功能需要 PyMuPDF 库。\n"
                "请安装: pip install PyMuPDF"
            )

        self.book_path = book_path
        self.target_size = target_size.upper()
        self.progress_callback = progress_callback
        self.backup_path = None

        # 文档级基线（在第一次扫描时计算）
        self.baseline_width = None  # 主流单页宽度
        self.baseline_height = None  # 主流单页高度
        self.is_landscape_doc = False  # 是否为横向文档

        # 构建PDF路径（兼容有无.pdf后缀）
        if book_path.lower().endswith(".pdf"):
            self.pdf_path = book_path
        else:
            self.pdf_path = book_path + ".pdf"

        # 验证目标尺寸
        if self.target_size not in STANDARD_SIZES:
            raise ValueError(
                f"不支持的目标尺寸: {target_size}，"
                f"支持的尺寸: {', '.join(STANDARD_SIZES.keys())}"
            )

    def resize(self) -> Dict:
        """
        执行PDF格式化

        Returns:
            结果字典：
            {
                "success": True/False,
                "new_size": {"width_mm": 210, "height_mm": 297},
                "error": "错误信息",
                "skipped": True/False  # 是否因为已是目标尺寸而跳过
            }
        """
        try:
            # 1. 检查文件
            self.emit_progress(5, "正在检查PDF文件...")
            if not os.path.exists(self.pdf_path):
                raise Exception("PDF文件不存在")

            # 2. 检查当前PDF尺寸是否已经是目标尺寸
            self.emit_progress(8, "正在检测PDF尺寸...")
            # 注意：即使页面尺寸匹配，也可能需要处理白边
            # 所以这里不再跳过，而是继续检测内容边界
            is_target_size = self._check_if_already_target_size()
            if is_target_size:
                logger.info(f"PDF页面尺寸已是{self.target_size}，但仍需检查内容边界")

            # 3. 备份原文件
            self.emit_progress(10, "正在备份原文件...")
            self.backup_path = self._backup_file()

            # 4. 执行格式化
            self.emit_progress(15, "正在格式化PDF...")
            stats = self._resize_with_pymupdf()

            # 5. 删除备份（格式化成功）
            self.emit_progress(98, "正在清理备份...")
            if self.backup_path and os.path.exists(self.backup_path):
                try:
                    os.remove(self.backup_path)
                except OSError as e:
                    logger.warning(f"删除备份文件失败: {e}")

            # 6. 完成
            summary = f"格式化完成！双页:{stats['double_count']}页 / 单页:{stats['single_count']}页"
            if stats['error_count'] > 0:
                summary += f" / 错误:{stats['error_count']}页"

            self.emit_progress(
                100,
                summary,
                double_pages_count=stats['double_count'],
                single_pages_count=stats['single_count'],
                error_pages_count=stats['error_count'],
            )
            target_w_mm, target_h_mm = STANDARD_SIZES[self.target_size]
            return {
                "success": True,
                "new_size": {
                    "width_mm": target_w_mm,
                    "height_mm": target_h_mm
                },
                "stats": stats,
            }

        except Exception as e:
            # 恢复备份（格式化失败）
            error_detail = str(e)
            logger.error(f"PDF格式化失败: {error_detail}", exc_info=True)

            if self.backup_path and os.path.exists(self.backup_path):
                self.emit_progress(0, "格式化失败，正在恢复原文件...")
                try:
                    shutil.copy2(self.backup_path, self.pdf_path)
                    os.remove(self.backup_path)
                    logger.info("原文件已恢复")
                except Exception as restore_error:
                    logger.error(f"恢复备份失败: {str(restore_error)}", exc_info=True)
                    error_detail += f" (备份恢复也失败: {str(restore_error)})"

            return {
                "success": False,
                "error": error_detail
            }

    def _check_if_already_target_size(self) -> bool:
        """
        检查PDF是否已经是目标尺寸

        Returns:
            True: 已是目标尺寸，无需格式化
            False: 需要格式化
        """
        try:
            reader = PdfReader(self.pdf_path, strict=False)
            if len(reader.pages) == 0:
                return False

            first_page = reader.pages[0]
            current_w_mm = float(first_page.mediabox.width) * 25.4 / 72
            current_h_mm = float(first_page.mediabox.height) * 25.4 / 72

            target_w_mm, target_h_mm = STANDARD_SIZES[self.target_size]

            # 使用容差判断
            if (abs(current_w_mm - target_w_mm) <= SIZE_TOLERANCE and
                abs(current_h_mm - target_h_mm) <= SIZE_TOLERANCE):
                logger.info(
                    f"PDF已经是{self.target_size}尺寸"
                    f"({current_w_mm:.1f}x{current_h_mm:.1f}mm)，无需格式化"
                )
                return True

            return False

        except Exception as e:
            logger.warning(f"检测PDF尺寸失败: {e}")
            return False

    def _resize_with_pymupdf(self):
        """
        使用 PyMuPDF 执行格式化

        核心步骤：
        1. 打开PDF文档
        2. 创建新文档
        3. 遍历每一页（逐页检测并格式化）
        4. 检测双页并切分
        5. 保存

        技术方案：
        - 使用 get_pixmap() 将内容区域渲染为高分辨率图片（2倍zoom）
        - 使用 insert_image(keep_proportion=False) 将图片插入到新页面
        - keep_proportion=False 确保图片强制拉伸充满目标矩形
        - 最终效果：内容100%充满页面，无任何白边
        """
        # 打开原PDF文档
        src_doc = fitz.open(self.pdf_path)
        total_pages = len(src_doc)

        # 预扫描：计算文档级单页基线（用于泛化性双页检测）
        self.emit_progress(12, "正在分析页面结构...")
        profile = self._build_document_profile(src_doc)
        self.baseline_width = profile.get("baseline_width")
        self.baseline_height = profile.get("baseline_height")
        self.is_landscape_doc = profile.get("is_landscape_doc", False)

        logger.info(
            "文档基线检测：baseline_w=%s pt, baseline_h=%s pt, wide_ratio=%.2f, is_landscape_doc=%s",
            self.baseline_width,
            self.baseline_height,
            profile.get("wide_page_ratio", 0.0),
            self.is_landscape_doc,
        )

        # 创建新文档
        dst_doc = fitz.open()

        # 获取目标尺寸（点）
        target_w_mm, target_h_mm = STANDARD_SIZES[self.target_size]
        target_w_pt = target_w_mm * 72 / 25.4
        target_h_pt = target_h_mm * 72 / 25.4
        target_rect = fitz.Rect(0, 0, target_w_pt, target_h_pt)

        # 统计计数器
        double_count = 0  # 双页计数
        single_count = 0  # 单页计数
        error_count = 0   # 错误计数

        # 进度说明：
        # 0-5%: 初始化阶段
        # 5-88%: 逐页处理（每页进度 + 子阶段进度）
        # 88-92%: 保存文件
        # 92-95%: 替换文件
        # 95-100%: 完成

        # 处理每一页
        for page_num in range(total_pages):
            page_num_display = page_num + 1
            src_page = None

            # 计算当前页的进度（单调递增，不跳动）
            current_progress = 5 + int((page_num / total_pages) * 83)

            try:
                src_page = src_doc[page_num]

                # === 阶段1: 提取页面 ===
                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] 提取页面内容 | 已处理:{double_count + single_count} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="extracting",
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                    error_pages_count=error_count,
                )

                page_image, source_type = self._get_main_image_from_page(src_doc, src_page)

                if page_image is None:
                    logger.warning(
                        f"[{page_num_display}/{total_pages}] 主图提取失败，回退整页渲染"
                    )
                    error_count += 1
                    single_count += 1
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] 主图提取失败，回退整页渲染 | 已处理:{double_count + single_count} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="fallback_render",
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                        error_pages_count=error_count,
                    )
                    self._render_page_to_target(
                        src_doc, page_num, dst_doc, target_rect,
                    )
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] ✅ 完成 | 本页:单页(回退渲染) | 来源:{source_type} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="page_done",
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                        error_pages_count=error_count,
                    )
                    continue

                # === 阶段2: 双页检测 ===
                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] 检测页面类型 | 已处理:{double_count + single_count} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="detecting",
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                    error_pages_count=error_count,
                )

                detection_result = self._detect_double_page(page_image)

                if detection_result["is_double"]:
                    # === 双页处理 ===
                    logger.info(
                        f"[{page_num_display}/{total_pages}] ✂️ 双页 | "
                        f"宽度比={detection_result.get('width_ratio', 0):.2f} | "
                        f"宽高比={detection_result['aspect_ratio']:.3f} | "
                        f"亮度比={detection_result['brightness_ratio']:.3f} | "
                        f"{detection_result['reason']}"
                    )

                    # 更新计数
                    double_count += 1

                    # 阶段2.1: 切分双页并分别矢量嵌入到目标页面

                    # 阶段2.2: 格式化左页（矢量嵌入，保持原始分辨率）
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] 格式化左页 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="formatting_left",
                        is_double=True,
                        detection_info=detection_result,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    src_rect = src_page.rect
                    left_clip = fitz.Rect(0, 0, src_rect.width / 2, src_rect.height)
                    dst_page_left = dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    dst_page_left.show_pdf_page(target_rect, src_doc, page_num, clip=left_clip, keep_proportion=False)

                    # 阶段2.3: 格式化右页（矢量嵌入，保持原始分辨率）
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] 格式化右页 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="formatting_right",
                        is_double=True,
                        detection_info=detection_result,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    right_clip = fitz.Rect(src_rect.width / 2, 0, src_rect.width, src_rect.height)
                    dst_page_right = dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    dst_page_right.show_pdf_page(target_rect, src_doc, page_num, clip=right_clip, keep_proportion=False)

                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] ✅ 完成 | 本页:双页拆分 | 来源:{source_type} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="page_done",
                        is_double=True,
                        detection_info=detection_result,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                        error_pages_count=error_count,
                    )

                else:
                    # === 单页处理 ===
                    single_count += 1

                    logger.debug(
                        f"[{page_num_display}/{total_pages}] 单页 | "
                        f"宽高比={detection_result['aspect_ratio']:.3f} | "
                        f"亮度比={detection_result.get('brightness_ratio', 0):.3f}"
                    )

                    # 阶段2.1: 检测内容边界
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] 检测内容边界 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="detecting_content",
                        is_double=False,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    content_bbox = self._detect_content_bbox(src_page)
                    clip_rect = content_bbox if content_bbox else src_page.rect

                    # 阶段2.2: 渲染内容
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] 渲染页面内容 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="rendering",
                        is_double=False,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    # 阶段2.3: 插入新页面
                    sub_progress = current_progress
                    self.emit_progress(
                        sub_progress,
                        f"[{page_num_display}/{total_pages}] 插入目标页面 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="inserting",
                        is_double=False,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    self._render_page_to_target(
                        src_doc, page_num, dst_doc, target_rect,
                        clip_rect=clip_rect,
                    )

                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] ✅ 完成 | 本页:单页 | 来源:{source_type} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="page_done",
                        is_double=False,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                        error_pages_count=error_count,
                    )

                # 本页完成（不再单独emit，避免进度跳动）

            except Exception as e:
                error_count += 1
                logger.error(f"[{page_num_display}/{total_pages}] ❌ 处理失败: {e}", exc_info=True)

                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] ❌ 失败: {str(e)} | 双页:{double_count} 单页:{single_count} 错误:{error_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="error",
                    error=str(e),
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                    error_pages_count=error_count,
                )

                try:
                    if src_page is not None:
                        logger.warning(
                            f"[{page_num_display}/{total_pages}] 发生异常，回退整页渲染"
                        )
                        self._render_page_to_target(
                            src_doc, page_num, dst_doc, target_rect,
                        )
                    else:
                        dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                except Exception:
                    dst_doc.new_page(width=target_w_pt, height=target_h_pt)

        # 关闭原文档
        src_doc.close()

        # 保存到临时文件
        self.emit_progress(
            88,
            f"正在保存PDF（双页:{double_count}页 / 单页:{single_count}页 / 错误:{error_count}页）...",
            double_pages_count=double_count,
            single_pages_count=single_count,
            error_pages_count=error_count,
        )
        temp_path = self.pdf_path + ".tmp"
        try:
            dst_doc.save(temp_path, garbage=4, deflate=True, clean=True)
            dst_doc.close()
        except Exception as e:
            dst_doc.close()
            raise Exception(f"保存PDF失败: {str(e)}")

        # 替换原文件
        self.emit_progress(95, f"正在替换原文件（双页:{double_count} / 单页:{single_count}）...")
        try:
            os.replace(temp_path, self.pdf_path)
        except OSError as e:
            # 替换失败，尝试清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise Exception(f"替换原文件失败: {str(e)}")

        # 返回统计信息
        return {
            "double_count": double_count,
            "single_count": single_count,
            "error_count": error_count,
        }

    def _render_page_to_target(
        self,
        src_doc: fitz.Document,
        page_num: int,
        dst_doc: fitz.Document,
        target_rect: fitz.Rect,
        clip_rect: Optional[fitz.Rect] = None,
    ) -> None:
        """将源页面矢量内容嵌入目标文档（保持原始矢量分辨率）

        使用 show_pdf_page 替代 get_pixmap + insert_image：
        - 保留文字/矢量图形的原始锐度
        - 不受 DPI 限制，输出分辨率由 PDF 阅读器决定
        - 非等比拉伸由 PDF 阅读器层面的变换完成
        """
        render_clip = clip_rect if clip_rect else src_doc[page_num].rect
        dst_page = dst_doc.new_page(width=target_rect.width, height=target_rect.height)
        dst_page.show_pdf_page(target_rect, src_doc, page_num, clip=render_clip, keep_proportion=False)

    def _build_document_profile(self, doc: fitz.Document) -> Dict[str, Any]:
        """
        文档级预扫描：基于页面主图宽度计算主流单页基线

        说明：
        - 使用每页主图（优先嵌入图）的实际宽度聚类
        - 避免 PDF 页框尺寸（如 Letter/A4 默认框）误导基线
        - 双页通常是两页拼在一起，主图宽度约为单页的 2x
        - 横向书保护：超过 40% 页面宽度 > 基线 x 1.7 时，判定为横向文档
        """
        if not HAS_IMAGE_LIBS:
            return {
                "baseline_width": None,
                "baseline_height": None,
                "wide_page_ratio": 0.0,
                "is_landscape_doc": False,
            }

        page_sizes = []
        total_pages = len(doc)

        # 采样：最多扫描前100页（大文档性能优化）
        sample_size = min(100, total_pages)

        for page_num in range(sample_size):
            try:
                if self.progress_callback and (
                    page_num == 0 or
                    (page_num + 1) % 10 == 0 or
                    page_num == sample_size - 1
                ):
                    profile_progress = 12 + int(((page_num + 1) / sample_size) * 3)
                    self.emit_progress(
                        profile_progress,
                        f"正在分析页面结构... [{page_num + 1}/{sample_size}]",
                        current_page=page_num + 1,
                        total_pages=sample_size,
                        sub_stage="profiling",
                    )

                page = doc[page_num]
                page_image, _ = self._get_main_image_from_page(doc, page)
                if page_image:
                    w, h = page_image.size
                    page_sizes.append({"width": w, "height": h})
            except Exception as e:
                logger.debug(f"预扫描页面{page_num + 1}失败: {e}")
                continue

        if not page_sizes:
            return {
                "baseline_width": None,
                "baseline_height": None,
                "wide_page_ratio": 0.0,
                "is_landscape_doc": False,
            }

        widths = [p["width"] for p in page_sizes]
        heights = [p["height"] for p in page_sizes]

        # 宽度聚类：找主流单页宽度（选择最高频的窄页宽度）
        widths_sorted = sorted(widths)
        width_clusters = []
        current_cluster = [widths_sorted[0]]

        for w in widths_sorted[1:]:
            cluster_center = sum(current_cluster) / len(current_cluster)
            if abs(w - cluster_center) / cluster_center <= BASELINE_WIDTH_TOLERANCE:
                current_cluster.append(w)
            else:
                width_clusters.append(current_cluster)
                current_cluster = [w]
        width_clusters.append(current_cluster)

        # 选择最窄的大聚类作为单页基线（双页通常更宽）
        width_clusters_sorted = sorted(width_clusters, key=lambda c: sum(c) / len(c))
        baseline_width_cluster = max(width_clusters_sorted[:max(1, len(width_clusters_sorted)//2 + 1)], key=len)
        baseline_width = sum(baseline_width_cluster) / len(baseline_width_cluster)

        # 高度聚类：找主流单页高度
        heights_sorted = sorted(heights)
        height_clusters = []
        current_cluster = [heights_sorted[0]]

        for h in heights_sorted[1:]:
            cluster_center = sum(current_cluster) / len(current_cluster)
            if abs(h - cluster_center) / cluster_center <= BASELINE_HEIGHT_TOLERANCE:
                current_cluster.append(h)
            else:
                height_clusters.append(current_cluster)
                current_cluster = [h]
        height_clusters.append(current_cluster)

        baseline_height_cluster = max(height_clusters, key=len)
        baseline_height = sum(baseline_height_cluster) / len(baseline_height_cluster)

        # 统计宽页占比
        wide_count = sum(1 for p in page_sizes if p["width"] > baseline_width * WIDE_PAGE_RATIO_MIN)
        wide_ratio = wide_count / len(page_sizes)

        return {
            "baseline_width": baseline_width,
            "baseline_height": baseline_height,
            "wide_page_ratio": wide_ratio,
            "is_landscape_doc": wide_ratio > LANDSCAPE_DOC_THRESHOLD,
        }

    def _detect_double_page(self, image: Image.Image) -> Dict:
        """
        检测图片是否为双页

        基于文档级基线 + 多信号确认策略：
        1. 文档级保护：横向文档（>50%宽页）直接判定为单页
        2. 相对尺寸检测：页面宽度是否为基线的1.8-2.2倍
        3. 信号1：中缝检测（中间区域亮度/密度明显不同）
        4. 信号2：左右半区独立性检测（都有实质性内容）
        5. 信号3：左右密度相似性检测（都是书页，密度应相近）

        Args:
            image: PIL Image 对象

        Returns:
            检测结果字典
        """
        if not HAS_IMAGE_LIBS:
            return {
                "is_double": False,
                "aspect_ratio": 0,
                "brightness_ratio": 0,
                "confidence": "未知",
                "reason": "图像库未安装，跳过双页检测"
            }

        try:
            width, height = image.size
            if height == 0:
                return {
                    "is_double": False,
                    "aspect_ratio": 0,
                    "brightness_ratio": 0,
                    "confidence": "低",
                    "reason": "图片高度为0"
                }

            aspect_ratio = width / height

            # 文档级保护：如果文档本身就是横向书（大部分页面都宽）
            if self.is_landscape_doc:
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "brightness_ratio": 0,
                    "confidence": "高",
                    "reason": "文档级保护：横向文档不拆分"
                }

            # 无基线：无法判断相对尺寸，默认单页
            if self.baseline_width is None:
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "brightness_ratio": 0,
                    "confidence": "低",
                    "reason": "无文档基线，跳过双页检测"
                }

            # 相对尺寸检测：宽度是否为基线的1.8-2.2倍
            width_ratio = width / self.baseline_width
            height_ratio = height / self.baseline_height if self.baseline_height else 0

            if not (WIDE_PAGE_RATIO_MIN <= width_ratio <= WIDE_PAGE_RATIO_MAX):
                # 宽度不在1.8-2.2倍范围内，直接判定为单页
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "width_ratio": width_ratio,
                    "height_ratio": height_ratio,
                    "brightness_ratio": 0,
                    "confidence": "高",
                    "reason": f"宽度比{width_ratio:.2f}不在[{WIDE_PAGE_RATIO_MIN:.1f}, {WIDE_PAGE_RATIO_MAX:.1f}]倍范围内"
                }

            # 高度必须匹配基线（±15%）
            if not (1 - HEIGHT_MATCH_TOLERANCE <= height_ratio <= 1 + HEIGHT_MATCH_TOLERANCE):
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "width_ratio": width_ratio,
                    "height_ratio": height_ratio,
                    "brightness_ratio": 0,
                    "confidence": "中",
                    "reason": f"高度比{height_ratio:.2f}不匹配基线"
                }

            # 信号1：中缝检测（中间明显更亮或更暗）
            # 兼顾不同扫描件：用相对比值 + 绝对差值双条件
            gray = image.convert("L")
            img_array = np.array(gray)
            h, w = img_array.shape

            center_start = int(w * (0.5 - CENTER_WIDTH_RATIO / 2))
            center_end = int(w * (0.5 + CENTER_WIDTH_RATIO / 2))
            left_end = int(w * 0.3)
            right_start = int(w * 0.7)

            center_region = img_array[:, center_start:center_end]
            left_region = img_array[:, :left_end]
            right_region = img_array[:, right_start:]

            center_brightness = float(np.mean(center_region))
            side_brightness = (float(np.mean(left_region)) + float(np.mean(right_region))) / 2
            brightness_ratio = center_brightness / side_brightness if side_brightness > 0 else 1.0

            center_side_diff = abs(center_brightness - side_brightness)
            has_seam_signal = (brightness_ratio >= 1.06) or (brightness_ratio <= 0.94) or (center_side_diff >= 6.0)

            # 信号2：左右半区独立性
            mid_x = w // 2
            left_half = img_array[:, :mid_x]
            right_half = img_array[:, mid_x:]

            left_density = float(np.mean(left_half))
            right_density = float(np.mean(right_half))
            side_density = (left_density + right_density) / 2

            left_independent = left_density < side_density * 0.85  # 左半区比平均暗
            right_independent = right_density < side_density * 0.85  # 右半区比平均暗
            both_independent = left_independent and right_independent

            # 信号3：左右密度相似性（都是书页，密度应相近）
            density_ratio = max(left_density, right_density) / min(left_density, right_density) if min(left_density, right_density) > 0 else 1.0
            density_similar = density_ratio < 1.5  # 密度相差不超过50%

            # 综合判断：
            # - 强候选（宽度约为基线 2x 且高度匹配）允许仅凭密度相似就拆分
            # - 其他候选需要至少 2 个信号确认
            signals_met = sum([has_seam_signal, both_independent, density_similar])

            strong_candidate = (
                (1.9 <= width_ratio <= 2.2) and
                (1 - HEIGHT_MATCH_TOLERANCE <= height_ratio <= 1 + HEIGHT_MATCH_TOLERANCE)
            )

            if strong_candidate and density_similar:
                confidence = "高" if signals_met >= 2 else "中"
                return {
                    "is_double": True,
                    "aspect_ratio": aspect_ratio,
                    "width_ratio": width_ratio,
                    "height_ratio": height_ratio,
                    "brightness_ratio": brightness_ratio,
                    "confidence": confidence,
                    "reason": f"宽度比{width_ratio:.2f}x基线(强候选) + 密度相似({density_similar})"
                }

            if signals_met >= 2:
                # 至少2个信号确认
                confidence = "高" if signals_met == 3 else "中"
                return {
                    "is_double": True,
                    "aspect_ratio": aspect_ratio,
                    "width_ratio": width_ratio,
                    "height_ratio": height_ratio,
                    "brightness_ratio": brightness_ratio,
                    "confidence": confidence,
                    "reason": f"宽度比{width_ratio:.2f}x基线 + 中缝信号({has_seam_signal}) + 左右独立({both_independent}) + 密度相似({density_similar})"
                }
            else:
                # 信号不足
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "width_ratio": width_ratio,
                    "height_ratio": height_ratio,
                    "brightness_ratio": brightness_ratio,
                    "confidence": "中",
                    "reason": f"宽度比{width_ratio:.2f}x基线但信号不足({signals_met}/3)"
                }

        except Exception as e:
            logger.warning(f"双页检测失败: {e}")
            return {
                "is_double": False,
                "aspect_ratio": 0,
                "brightness_ratio": 0,
                "confidence": "低",
                "reason": f"检测异常: {str(e)}"
            }

    def _split_double_page_image(self, image: Image.Image) -> Tuple[Image.Image, Image.Image]:
        """
        将双页图片从中间切分成左右两页

        Args:
            image: PIL Image 对象

        Returns:
            (left_image, right_image) 元组
        """
        width, height = image.size
        mid_x = width // 2

        left_img = image.crop((0, 0, mid_x, height))
        right_img = image.crop((mid_x, 0, width, height))

        return left_img, right_img

    def _get_main_image_from_page(self, doc: fitz.Document, page: fitz.Page) -> Tuple[Optional[Image.Image], str]:
        """
        从页面提取主图，优先提取嵌入图片，无嵌入图时渲染整页

        Args:
            doc: PyMuPDF 文档对象
            page: PyMuPDF 页面对象

        Returns:
            (image, source_type) 元组
            - image: PIL Image 对象，失败时返回 None
            - source_type: "embedded_image" 或 "rendered_page" 或 "none"
        """
        if not HAS_IMAGE_LIBS:
            return None, "none"

        try:
            # 优先提取嵌入图片
            images = page.get_images(full=True)
            main_image = None
            max_area = 0

            for img in images:
                try:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    width, height = pil_img.size
                    area = width * height

                    if area > max_area:
                        max_area = area
                        main_image = pil_img
                except Exception as e:
                    logger.debug(f"提取嵌入图片失败: {e}")
                    continue

            if main_image is not None:
                return main_image, "embedded_image"

            # 回退：渲染整页
            pix = page.get_pixmap(dpi=144, alpha=False)
            rendered = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            return rendered, "rendered_page"

        except Exception as e:
            logger.warning(f"获取页面图片失败: {e}")
            return None, "none"

    def _detect_content_bbox(self, page: fitz.Page) -> Optional[fitz.Rect]:
        """
        检测页面的实际内容边界（去除白边）

        Args:
            page: PyMuPDF 页面对象

        Returns:
            内容边界矩形，如果检测失败返回 None
        """
        try:
            page_rect = page.rect

            # 获取页面上所有内容的边界
            # get_text("dict") 返回文字块的边界
            text_dict = page.get_text("dict")
            blocks = text_dict.get("blocks", [])

            # 获取所有图片的边界
            images = page.get_image_info(xrefs=True)

            # 如果页面没有内容，返回整个页面
            if not blocks and not images:
                return None

            # 计算内容的最小包围框
            min_x = page_rect.width
            min_y = page_rect.height
            max_x = 0
            max_y = 0

            # 文字块边界
            for block in blocks:
                bbox = block.get("bbox")
                if bbox:
                    min_x = min(min_x, bbox[0])
                    min_y = min(min_y, bbox[1])
                    max_x = max(max_x, bbox[2])
                    max_y = max(max_y, bbox[3])

            # 图片边界
            for img in images:
                bbox = img.get("bbox")
                if bbox:
                    min_x = min(min_x, bbox[0])
                    min_y = min(min_y, bbox[1])
                    max_x = max(max_x, bbox[2])
                    max_y = max(max_y, bbox[3])

            # 构造内容边界矩形
            content_bbox = fitz.Rect(min_x, min_y, max_x, max_y)

            # 计算边距（毫米）
            margin_left_mm = min_x * 25.4 / 72
            margin_top_mm = min_y * 25.4 / 72
            margin_right_mm = (page_rect.width - max_x) * 25.4 / 72
            margin_bottom_mm = (page_rect.height - max_y) * 25.4 / 72

            # 如果四边边距都很小（<5mm），说明已经充满，不需要裁剪
            if all([
                margin_left_mm < MARGIN_THRESHOLD,
                margin_top_mm < MARGIN_THRESHOLD,
                margin_right_mm < MARGIN_THRESHOLD,
                margin_bottom_mm < MARGIN_THRESHOLD
            ]):
                return None

            return content_bbox

        except Exception as e:
            logger.warning(f"检测内容边界失败: {e}")
            return None

    def _backup_file(self) -> str:
        """
        备份原文件（带时间戳）

        Returns:
            备份文件路径

        Raises:
            Exception: 备份失败
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.pdf_path}.backup_{timestamp}"
        try:
            shutil.copy2(self.pdf_path, backup_path)
            logger.info(f"已创建备份: {backup_path}")
            return backup_path
        except (IOError, OSError) as e:
            raise Exception(f"创建备份失败: {str(e)}")

    def emit_progress(self, progress: int, stage: str, **kwargs):
        """
        发送进度信息到回调函数

        Args:
            progress: 进度百分比（0-100）
            stage: 当前阶段描述
            **kwargs: 其���信息（如current_page, total_pages）
        """
        if self.progress_callback:
            try:
                self.progress_callback({
                    "progress": progress,
                    "stage": stage,
                    **kwargs
                })
            except Exception as e:
                # 回调失败不应影响主流程
                logger.warning(f"进度回调失败: {e}")

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
from typing import Optional, Dict, Tuple

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
ASPECT_RATIO_MIN = 1.30  # 宽高比小于此值直接判定为单页
ASPECT_RATIO_STRONG = 1.34  # 宽高比大于此值即使无明显中缝也判定为双页
CENTER_WIDTH_RATIO = 0.10  # 中间区域宽度占比
BRIGHTNESS_THRESHOLD = 1.15  # 中间/两侧亮度比阈值


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

            # 计算当前页的进度（单调递增，不跳动）
            current_progress = 5 + int((page_num / total_pages) * 83)

            try:
                src_page = src_doc[page_num]

                # === 阶段1: 提取页面 ===
                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] 提取页面内容 | 双页:{double_count} 单页:{single_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="extracting",
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                )

                page_image, source_type = self._get_main_image_from_page(src_doc, src_page)

                if page_image is None:
                    # 无法获取图片，记录错误并添加空白页
                    logger.warning(f"[{page_num_display}/{total_pages}] 无法提取图片，使用空白页")
                    error_count += 1
                    dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    continue

                # === 阶段2: 双页检测 ===
                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] 检测页面类型 | 双页:{double_count} 单页:{single_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="detecting",
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                )

                detection_result = self._detect_double_page(page_image)

                if detection_result["is_double"]:
                    # === 双页处理 ===
                    logger.info(
                        f"[{page_num_display}/{total_pages}] ✂️ 双页 | "
                        f"宽高比={detection_result['aspect_ratio']:.3f} | "
                        f"亮度比={detection_result['brightness_ratio']:.3f} | "
                        f"{detection_result['reason']}"
                    )

                    # 更新计数
                    double_count += 1

                    # 阶段2.1: 切分双页
                    self.emit_progress(
                        current_progress,
                        f"[{page_num_display}/{total_pages}] ✂️ 切分双页 | 双页:{double_count} 单页:{single_count}",
                        current_page=page_num_display,
                        total_pages=total_pages,
                        sub_stage="splitting",
                        is_double=True,
                        detection_info=detection_result,
                        double_pages_count=double_count,
                        single_pages_count=single_count,
                    )

                    left_img, right_img = self._split_double_page_image(page_image)

                    # 阶段2.2: 格式化左页
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

                    dst_page_left = dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    left_bytes = io.BytesIO()
                    left_img.save(left_bytes, format="PNG")
                    left_bytes.seek(0)
                    dst_page_left.insert_image(target_rect, stream=left_bytes, keep_proportion=False)

                    # 阶段2.3: 格式化右页
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

                    dst_page_right = dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    right_bytes = io.BytesIO()
                    right_img.save(right_bytes, format="PNG")
                    right_bytes.seek(0)
                    dst_page_right.insert_image(target_rect, stream=right_bytes, keep_proportion=False)

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

                    if content_bbox:
                        clip_rect = content_bbox
                    else:
                        clip_rect = src_page.rect

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

                    zoom = 2.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = src_page.get_pixmap(matrix=mat, clip=clip_rect)

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

                    dst_page = dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                    dst_page.insert_image(target_rect, pixmap=pix, keep_proportion=False)

                    # 释放内存
                    pix = None

                # 本页完成（不再单独emit，避免进度跳动）

            except Exception as e:
                error_count += 1
                logger.error(f"[{page_num_display}/{total_pages}] ❌ 处理失败: {e}", exc_info=True)

                self.emit_progress(
                    current_progress,
                    f"[{page_num_display}/{total_pages}] ❌ 失败: {str(e)} | 双页:{double_count} 单页:{single_count}",
                    current_page=page_num_display,
                    total_pages=total_pages,
                    sub_stage="error",
                    error=str(e),
                    double_pages_count=double_count,
                    single_pages_count=single_count,
                )

                # 出错时添加空白页
                try:
                    dst_doc.new_page(width=target_w_pt, height=target_h_pt)
                except Exception:
                    pass

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

    def _detect_double_page(self, image: Image.Image) -> Dict:
        """
        检测图片是否为双页

        基于 v2 规则：
        1. 宽高比 < 1.30：单页
        2. 宽高比 >= 1.30 且中间亮度比 >= 1.15：双页
        3. 宽高比 >= 1.34：双页（即使无明显中缝）

        Args:
            image: PIL Image 对象

        Returns:
            检测结果字典：
            {
                "is_double": True/False,
                "aspect_ratio": 宽高比,
                "brightness_ratio": 中间亮度比,
                "confidence": "高"/"中"/"低",
                "reason": "判断依据"
            }
        """
        if not HAS_IMAGE_LIBS:
            # 没有图像库，默认返回单页
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

            # 规则1: 宽高比过小，直接判定为单页
            if aspect_ratio < ASPECT_RATIO_MIN:
                return {
                    "is_double": False,
                    "aspect_ratio": aspect_ratio,
                    "brightness_ratio": 0,
                    "confidence": "高",
                    "reason": f"宽高比{aspect_ratio:.3f}<{ASPECT_RATIO_MIN}，竖版单页"
                }

            # 检测中间亮度
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

            # 规则2: 宽高比足够 + 中间明显更亮
            if brightness_ratio >= BRIGHTNESS_THRESHOLD:
                confidence = "高" if brightness_ratio >= 1.30 else "中"
                return {
                    "is_double": True,
                    "aspect_ratio": aspect_ratio,
                    "brightness_ratio": brightness_ratio,
                    "confidence": confidence,
                    "reason": f"宽高比{aspect_ratio:.3f}≥{ASPECT_RATIO_MIN}，中间亮度比{brightness_ratio:.3f}≥{BRIGHTNESS_THRESHOLD}，存在中缝"
                }

            # 规则3: 宽高比非常大，即使无明显中缝也判定为双页
            if aspect_ratio >= ASPECT_RATIO_STRONG:
                return {
                    "is_double": True,
                    "aspect_ratio": aspect_ratio,
                    "brightness_ratio": brightness_ratio,
                    "confidence": "中",
                    "reason": f"宽高比{aspect_ratio:.3f}≥{ASPECT_RATIO_STRONG}，纯色/无明显中缝双页"
                }

            # 其他情况：单页
            return {
                "is_double": False,
                "aspect_ratio": aspect_ratio,
                "brightness_ratio": brightness_ratio,
                "confidence": "中",
                "reason": f"宽高比{aspect_ratio:.3f}，中间亮度比{brightness_ratio:.3f}，判定为单页"
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

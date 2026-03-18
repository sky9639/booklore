"""
PDF格式化模块
用于将PDF缩放到标准尺寸（A4/A5/B5）
"""

import os
import shutil
import logging
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter, PageObject

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 标准尺寸定义（mm）
STANDARD_SIZES = {
    'A4': (210, 297),
    'A5': (148, 210),
    'B5': (176, 250)
}


class PdfResizer:
    """PDF格式化器"""

    def __init__(self, book_path: str, target_size: str, progress_callback=None):
        """
        初始化PDF格式化器

        Args:
            book_path: 书籍文件路径（不含.pdf后缀）
            target_size: 目标尺寸（A4/A5/B5）
            progress_callback: 进度回调函数，接收dict参数
        """
        self.book_path = book_path
        self.target_size = target_size.upper()
        self.progress_callback = progress_callback
        self.backup_path = None

        # 构建PDF路径
        if book_path.lower().endswith(".pdf"):
            self.pdf_path = book_path
        else:
            self.pdf_path = book_path + ".pdf"

        # 验证目标尺寸
        if self.target_size not in STANDARD_SIZES:
            raise ValueError(f"不支持的目标尺寸: {target_size}")

    def resize(self) -> dict:
        """
        执行PDF格式化

        Returns:
            结果字典：
            {
                "success": True/False,
                "new_size": {"width_mm": 210, "height_mm": 297},
                "error": "错误信息"
            }
        """
        try:
            # 1. 检查文件
            self.emit_progress(5, "正在检查PDF文件...")
            if not os.path.exists(self.pdf_path):
                raise Exception("PDF文件不存在")

            # 2. 备份原文件
            self.emit_progress(10, "正在备份原文件...")
            self.backup_path = self._backup_file()

            # 3. 读取原PDF
            self.emit_progress(15, "正在读取PDF...")
            try:
                reader = PdfReader(self.pdf_path, strict=False)  # 非严格模式，容忍PDF错误
            except Exception as e:
                raise Exception(f"无法读取PDF文件: {str(e)}")

            total_pages = len(reader.pages)

            if total_pages == 0:
                raise Exception("PDF文件为空，没有页面")

            # 4. 创建新PDF
            self.emit_progress(20, "正在创建新PDF...")
            writer = PdfWriter()

            # 获取目标尺寸（点）
            target_w_mm, target_h_mm = STANDARD_SIZES[self.target_size]
            target_w_pt = target_w_mm * 72 / 25.4
            target_h_pt = target_h_mm * 72 / 25.4

            # 5. 处理每一页
            for i, page in enumerate(reader.pages):
                progress = 20 + int((i / total_pages) * 70)
                self.emit_progress(
                    progress,
                    f"正在处理第 {i + 1}/{total_pages} 页...",
                    current_page=i + 1,
                    total_pages=total_pages
                )

                try:
                    # 处理单页
                    new_page = self._process_page(page, target_w_pt, target_h_pt, i + 1)
                    writer.add_page(new_page)
                except Exception as e:
                    # 获取详细的错误堆栈
                    import traceback
                    error_trace = traceback.format_exc()
                    error_msg = f"第{i+1}页处理失败: {str(e)}\n详细信息: {error_trace}"
                    logger.error(error_msg)
                    raise Exception(f"第{i+1}页处理失败: {str(e)}")

            # 6. 写入临时文件
            self.emit_progress(92, "正在保存PDF...")
            temp_path = self.pdf_path + ".tmp"
            with open(temp_path, 'wb') as f:
                writer.write(f)

            # 7. 替换原文件
            self.emit_progress(95, "正在替换原文件...")
            os.replace(temp_path, self.pdf_path)

            # 8. 删除备份
            self.emit_progress(98, "正在清理备份...")
            if self.backup_path and os.path.exists(self.backup_path):
                os.remove(self.backup_path)

            # 9. 完成
            self.emit_progress(100, "格式化完成！")
            return {
                "success": True,
                "new_size": {
                    "width_mm": target_w_mm,
                    "height_mm": target_h_mm
                }
            }

        except Exception as e:
            # 恢复备份
            error_detail = str(e)
            logger.error(f"PDF格式化失败: {error_detail}")

            if self.backup_path and os.path.exists(self.backup_path):
                self.emit_progress(0, "格式化失败，正在恢复原文件...")
                try:
                    shutil.copy2(self.backup_path, self.pdf_path)
                    os.remove(self.backup_path)
                    logger.info("原文件已恢复")
                except Exception as restore_error:
                    logger.error(f"恢复备份失败: {str(restore_error)}")
                    error_detail += f" (备份恢复也失败: {str(restore_error)})"

            return {
                "success": False,
                "error": error_detail
            }

    def _process_page(self, page, target_w_pt: float, target_h_pt: float, page_num: int = 0):
        """
        处理单个页面：缩放并居中，四周加白边

        Args:
            page: 原页面对象
            target_w_pt: 目标宽度（点）
            target_h_pt: 目标高度（点）
            page_num: 页码（用于错误提示）

        Returns:
            新页面对象
        """
        from PyPDF2 import Transformation
        import copy

        try:
            # 获取原页面尺寸
            try:
                orig_w = float(page.mediabox.width)
                orig_h = float(page.mediabox.height)
            except Exception as e:
                raise Exception(f"无法读取页面尺寸: {str(e)}")

            if orig_w <= 0 or orig_h <= 0:
                raise Exception(f"页面尺寸无效: {orig_w}x{orig_h}")

            # 计算缩放比例（保持宽高比，不裁剪）
            scale_w = target_w_pt / orig_w
            scale_h = target_h_pt / orig_h
            scale = min(scale_w, scale_h)  # 取较小的比例

            # 缩放后的实际尺寸
            scaled_w = orig_w * scale
            scaled_h = orig_h * scale

            # 计算居中偏移
            offset_x = (target_w_pt - scaled_w) / 2
            offset_y = (target_h_pt - scaled_h) / 2

            # 创建新页面（目标尺寸，白色背景）
            try:
                new_page = PageObject.create_blank_page(
                    width=target_w_pt,
                    height=target_h_pt
                )
            except Exception as e:
                raise Exception(f"创建空白页失败: {str(e)}")

            # 复制原页面以避免修改原对象
            try:
                page_copy = copy.copy(page)
            except Exception as e:
                raise Exception(f"复制页面对象失败: {str(e)}")

            # 创建变换：先缩放，再平移
            try:
                transformation = Transformation().scale(scale, scale).translate(offset_x, offset_y)
            except Exception as e:
                raise Exception(f"创建变换矩阵失败: {str(e)}")

            # 应用变换
            try:
                page_copy.add_transformation(transformation)
            except Exception as e:
                raise Exception(f"应用变换失败: {str(e)}")

            # 合并页面
            try:
                new_page.merge_page(page_copy)
            except Exception as e:
                raise Exception(f"合并页面失败: {str(e)}")

            return new_page

        except Exception as e:
            error_detail = str(e)
            logger.error(f"第{page_num}页处理失败: {error_detail}")
            # 重新抛出异常，保留详细信息
            raise

    def _backup_file(self) -> str:
        """
        备份原文件

        Returns:
            备份文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.pdf_path}.backup_{timestamp}"
        shutil.copy2(self.pdf_path, backup_path)
        return backup_path

    def emit_progress(self, progress: int, stage: str, **kwargs):
        """
        发送进度信息

        Args:
            progress: 进度百分比（0-100）
            stage: 当前阶段描述
            **kwargs: 其他信息（如current_page, total_pages）
        """
        if self.progress_callback:
            self.progress_callback({
                "progress": progress,
                "stage": stage,
                **kwargs
            })

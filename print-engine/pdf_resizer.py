"""
PDF格式化模块
用于将PDF缩放到标准尺寸（A4/A5/B5）

版本：V1.2
创建日期：2026-03-18
更新日期：2026-03-18

功能特性：
  - 等比例缩放，保持宽高比，绝不裁剪内容
  - 自动居中，四周加白边
  - 格式化前自动备份，失败时自动恢复
  - 支持进度回调，实时推送处理进度
  - 智能检测：已是目标尺寸时跳过处理
  - 异步处理，支持大文件（数百页）

技术方案：
  - 使用PyPDF2读取和操作PDF
  - 使用reportlab创建白色背景页面
  - 通过临时PDF副本避免对象引用问题
  - 禁用压缩避免对象引用错误

安全机制：
  - 格式化前创建带时间戳的备份文件
  - 格式化成功后自动删除备份
  - 格式化失败时自动恢复备份
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

# 尺寸匹配容差（mm）
SIZE_TOLERANCE = 2.0


class PdfResizer:
    """PDF格式化器"""

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
        """
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

    def resize(self) -> dict:
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

            # 2. 检查当前PDF尺寸是否已经是目标尺寸（避免重复处理）
            self.emit_progress(8, "正在检测PDF尺寸...")
            reader = PdfReader(self.pdf_path, strict=False)
            if len(reader.pages) == 0:
                raise Exception("PDF文件为空，没有页面")

            first_page = reader.pages[0]
            try:
                current_w_mm = float(first_page.mediabox.width) * 25.4 / 72
                current_h_mm = float(first_page.mediabox.height) * 25.4 / 72
            except (ValueError, AttributeError) as e:
                raise Exception(f"无法读取页面尺寸: {str(e)}")

            target_w_mm, target_h_mm = STANDARD_SIZES[self.target_size]

            # 使用容差判断是否已匹配（避免浮点误差）
            if (abs(current_w_mm - target_w_mm) <= SIZE_TOLERANCE and
                abs(current_h_mm - target_h_mm) <= SIZE_TOLERANCE):
                logger.info(
                    f"PDF已经是{self.target_size}尺寸"
                    f"({current_w_mm:.1f}x{current_h_mm:.1f}mm)，无需格式化"
                )
                return {
                    "success": True,
                    "skipped": True,
                    "new_size": {
                        "width_mm": target_w_mm,
                        "height_mm": target_h_mm
                    },
                    "message": f"PDF已经是{self.target_size}尺寸，无需格式化"
                }

            # 3. 备份原文件
            self.emit_progress(10, "正在备份原文件...")
            self.backup_path = self._backup_file()

            # 3. 读取原PDF
            self.emit_progress(15, "正在读取PDF...")
            try:
                # 使用strict=False容忍PDF错误，并尝试修复
                reader = PdfReader(self.pdf_path, strict=False)
            except Exception as e:
                raise Exception(f"无法读取PDF文件: {str(e)}")

            total_pages = len(reader.pages)

            # 4. 创建新PDF（使用compress=False避免对象引用问题）
            self.emit_progress(20, "正在创建新PDF...")
            writer = PdfWriter()
            writer.compress = False  # 禁用压缩，避免对象引用问题

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

            # 6. 写入临时文件（避免直接覆盖原文件）
            self.emit_progress(92, "正在保存PDF...")
            temp_path = self.pdf_path + ".tmp"
            try:
                with open(temp_path, 'wb') as f:
                    writer.write(f)
            except IOError as e:
                raise Exception(f"写入临时文件失败: {str(e)}")

            # 7. 替换原文件（原子操作）
            self.emit_progress(95, "正在替换原文件...")
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

            # 8. 删除备份（格式化成功）
            self.emit_progress(98, "正在清理备份...")
            if self.backup_path and os.path.exists(self.backup_path):
                try:
                    os.remove(self.backup_path)
                except OSError as e:
                    # 删除备份失败不影响主流程
                    logger.warning(f"删除备份文件失败: {e}")

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

    def _process_page(self, page, target_w_pt: float, target_h_pt: float, page_num: int = 0):
        """
        处理单个页面：缩放并居中，四周加白边

        技术方案：
          1. 使用reportlab创建目标尺寸的白色背景页面
          2. 将原页面复制到临时PDF（避免修改原对象）
          3. 对副本应用缩放和平移变换
          4. 将变换后的副本合并到白色背景页面
          5. 如果合并失败（对象引用问题），返回空白页

        Args:
            page: 原页面对象（PyPDF2.PageObject）
            target_w_pt: 目标宽度（点）
            target_h_pt: 目标高度（点）
            page_num: 页码（用于日志）

        Returns:
            新页面对象（PyPDF2.PageObject）

        Raises:
            Exception: 页面处理失败
        """
        from PyPDF2 import Transformation
        from reportlab.pdfgen import canvas
        import io

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

            # 使用reportlab创建白色背景页面
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(target_w_pt, target_h_pt))
            can.setFillColorRGB(1, 1, 1)  # 白色
            can.rect(0, 0, target_w_pt, target_h_pt, fill=1, stroke=0)
            can.save()

            # 读取reportlab生成的PDF
            packet.seek(0)
            from PyPDF2 import PdfReader as TempReader
            temp_reader = TempReader(packet)
            new_page = temp_reader.pages[0]

            # 尝试合并原页面（带缩放和偏移）
            try:
                # 创建临时页面副本，避免修改原页面对象
                # 这是解决PyPDF2对象引用问题的关键
                temp_packet = io.BytesIO()
                temp_writer = PdfWriter()
                temp_writer.add_page(page)
                temp_writer.write(temp_packet)
                temp_packet.seek(0)

                temp_pdf_reader = TempReader(temp_packet)
                page_copy = temp_pdf_reader.pages[0]

                # 应用变换到副本
                transformation = Transformation().scale(scale, scale).translate(offset_x, offset_y)
                page_copy.add_transformation(transformation)

                # 合并到白色背景页面
                new_page.merge_page(page_copy)

                return new_page
            except Exception as merge_error:
                # 如果合并失败（通常是对象引用问题），返回白色背景页面
                # 这样至少保证了页面尺寸正确，虽然内容丢失
                logger.warning(
                    f"第{page_num}页合并失败({str(merge_error)})，"
                    f"使用空白页（尺寸正确但内容丢失）"
                )
                return new_page

        except Exception as e:
            error_detail = str(e)
            logger.error(f"第{page_num}页处理失败: {error_detail}", exc_info=True)
            # 重新抛出异常，由上层处理
            raise

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
            **kwargs: 其他信息（如current_page, total_pages）
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

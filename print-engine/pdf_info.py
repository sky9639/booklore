"""
PDF信息获取模块
用于获取电子书PDF的尺寸、页数等信息

版本：V1.0
创建日期：2026-03-18
功能：
  - 检测PDF实际物理尺寸（mm）
  - 判断页面方向（竖向/横向/正方形）
  - 检测混合尺寸页面
  - 获取页数和文件大小
"""

import os
import logging
from PyPDF2 import PdfReader

# 配置日志
logger = logging.getLogger(__name__)


def get_pdf_info(book_path: str) -> dict:
    """
    获取PDF文件的详细信息

    Args:
        book_path: 书籍文件的完整路径（不含.pdf后缀）

    Returns:
        包含PDF信息的字典，格式：
        {
            "success": True/False,
            "data": {
                "width_mm": 210.0,
                "height_mm": 297.0,
                "orientation": "portrait",  # portrait/landscape/square
                "page_count": 150,
                "has_mixed_sizes": False,
                "file_size_mb": 12.5
            },
            "error": "错误信息"  # 仅在success=False时存在
        }
    """
    # 构建PDF路径
    if book_path.lower().endswith(".pdf"):
        pdf_path = book_path
    else:
        pdf_path = book_path + ".pdf"

    # 检查文件是否存在
    if not os.path.exists(pdf_path):
        return {
            "success": False,
            "error": "PDF文件不存在"
        }

    try:
        # 读取PDF（使用strict=False容忍格式错误）
        reader = PdfReader(pdf_path, strict=False)

        if len(reader.pages) == 0:
            return {
                "success": False,
                "error": "PDF文件为空"
            }

        # 获取第一页尺寸
        first_page = reader.pages[0]

        try:
            width_pt = float(first_page.mediabox.width)
            height_pt = float(first_page.mediabox.height)
        except (ValueError, AttributeError) as e:
            logger.error(f"无法读取页面尺寸: {e}")
            return {
                "success": False,
                "error": "无法读取页面尺寸"
            }

        # 验证尺寸有效性
        if width_pt <= 0 or height_pt <= 0:
            return {
                "success": False,
                "error": f"页面尺寸无效: {width_pt}x{height_pt}pt"
            }

        # 转换为毫米（1英寸 = 72点 = 25.4毫米）
        width_mm = round(width_pt * 25.4 / 72, 1)
        height_mm = round(height_pt * 25.4 / 72, 1)

        # 判断方向
        if width_mm > height_mm:
            orientation = "landscape"
        elif width_mm < height_mm:
            orientation = "portrait"
        else:
            orientation = "square"

        # 检查是否有混合尺寸（容差2点，避免浮点误差）
        has_mixed_sizes = False
        tolerance = 2.0  # 点

        try:
            for page in reader.pages[1:]:
                pw = float(page.mediabox.width)
                ph = float(page.mediabox.height)
                if abs(pw - width_pt) > tolerance or abs(ph - height_pt) > tolerance:
                    has_mixed_sizes = True
                    break
        except Exception as e:
            # 混合尺寸检测失败不影响主要功能
            logger.warning(f"混合尺寸检测失败: {e}")
            has_mixed_sizes = False

        # 获取文件大小
        try:
            file_size_bytes = os.path.getsize(pdf_path)
            file_size_mb = round(file_size_bytes / (1024 * 1024), 2)
        except OSError as e:
            logger.warning(f"获取文件大小失败: {e}")
            file_size_mb = 0.0

        return {
            "success": True,
            "data": {
                "width_mm": width_mm,
                "height_mm": height_mm,
                "orientation": orientation,
                "page_count": len(reader.pages),
                "has_mixed_sizes": has_mixed_sizes,
                "file_size_mb": file_size_mb
            }
        }

    except Exception as e:
        logger.error(f"读取PDF失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"读取PDF失败: {str(e)}"
        }

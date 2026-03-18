"""
PDF信息获取模块
用于获取电子书PDF的尺寸、页数等信息
"""

import os
from PyPDF2 import PdfReader


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
        # 读取PDF
        reader = PdfReader(pdf_path)

        if len(reader.pages) == 0:
            return {
                "success": False,
                "error": "PDF文件为空"
            }

        # 获取第一页尺寸
        first_page = reader.pages[0]
        width_pt = float(first_page.mediabox.width)
        height_pt = float(first_page.mediabox.height)

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

        # 检查是否有混合尺寸（容差2点）
        has_mixed_sizes = False
        for page in reader.pages[1:]:
            pw = float(page.mediabox.width)
            ph = float(page.mediabox.height)
            if abs(pw - width_pt) > 2 or abs(ph - height_pt) > 2:
                has_mixed_sizes = True
                break

        # 获取文件大小
        file_size_bytes = os.path.getsize(pdf_path)
        file_size_mb = round(file_size_bytes / 1024 / 1024, 2)

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
        return {
            "success": False,
            "error": f"读取PDF失败: {str(e)}"
        }

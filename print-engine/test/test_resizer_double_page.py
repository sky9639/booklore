#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 pdf_resizer 的双页检测和切分功能

使用方法:
    python test_resizer_double_page.py "test.pdf" A5
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf_resizer import PdfResizer


def progress_callback(info):
    """进度回调"""
    print(f"[{info['progress']}%] {info['stage']}")
    if 'current_page' in info:
        print(f"  当前页: {info['current_page']}/{info['total_pages']}")


def test_resize_with_double_page_detection(pdf_path, target_size="A5"):
    """测试带双页检测的格式化"""
    print("=" * 80)
    print(f"测试文件: {pdf_path}")
    print(f"目标尺寸: {target_size}")
    print("=" * 80)

    try:
        resizer = PdfResizer(pdf_path, target_size, progress_callback=progress_callback)
        result = resizer.resize()

        print("\n" + "=" * 80)
        print("格式化结果:")
        print("=" * 80)
        print(f"成功: {result['success']}")
        if result['success']:
            print(f"新尺寸: {result['new_size']['width_mm']}mm x {result['new_size']['height_mm']}mm")
            if result.get('skipped'):
                print("状态: 已是目标尺寸，跳过处理")
        else:
            print(f"错误: {result.get('error', '未知错误')}")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python test_resizer_double_page.py <pdf_path> [target_size]")
        print("示例: python test_resizer_double_page.py 'test.pdf' A5")
        sys.exit(1)

    input_pdf = sys.argv[1]
    input_size = sys.argv[2] if len(sys.argv) >= 3 else "A5"

    test_resize_with_double_page_detection(input_pdf, input_size)

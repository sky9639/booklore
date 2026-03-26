#!/usr/bin/env python
"""
测试 ReportLab Canvas.setPageSize() 的行为
验证：setPageSize() 必须在 drawImage() 之前调用才能生效
"""
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image
import os
import tempfile

def test_setPageSize_after_init():
    """测试：Canvas 初始化后立即 setPageSize，然后 drawImage"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试图片
        img_path = os.path.join(tmpdir, "test.png")
        img = Image.new("RGB", (100, 100), "red")
        img.save(img_path)

        # 测试 1：初始化后立即 setPageSize
        pdf1 = os.path.join(tmpdir, "test1.pdf")
        c = canvas.Canvas(pdf1)
        c.setPageSize((210 * mm, 297 * mm))  # A4
        c.drawImage(img_path, 0, 0, width=50*mm, height=50*mm)
        c.showPage()
        c.save()

        # 测试 2：初始化时指定 pagesize
        pdf2 = os.path.join(tmpdir, "test2.pdf")
        c = canvas.Canvas(pdf2, pagesize=(210 * mm, 297 * mm))
        c.drawImage(img_path, 0, 0, width=50*mm, height=50*mm)
        c.showPage()
        c.save()

        # 读取 PDF 页面尺寸
        import re
        for name, pdf_path in [("setPageSize after init", pdf1), ("pagesize in init", pdf2)]:
            with open(pdf_path, 'rb') as f:
                data = f.read()
            pages = re.finditer(rb'/Type\s*/Page[^s]', data)
            for i, match in enumerate(pages):
                start = match.start()
                chunk = data[max(0, start-500):start+500].decode('latin-1', errors='ignore')
                mb = re.search(r'/MediaBox\s*\[([^\]]+)\]', chunk)
                if mb:
                    nums = [float(x) for x in mb.group(1).split()]
                    if len(nums) == 4:
                        w_pt, h_pt = nums[2], nums[3]
                        w_mm = w_pt / 72 * 25.4
                        h_mm = h_pt / 72 * 25.4
                        print(f'{name} - Page {i+1}: {w_mm:.1f}mm x {h_mm:.1f}mm')

if __name__ == "__main__":
    test_setPageSize_after_init()

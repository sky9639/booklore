#!/usr/bin/env python
"""
测试 layout_engine.generate_layout() 生成的 PDF 页面尺寸

验证：
- 当 trim_size=A5 (148x210mm), output_sheet_size=A4 (210x297mm) 时
- 生成的 PDF 页面尺寸应该是 210x297mm (A4)
- 而不是内容尺寸 (148+spine_width)x210mm
"""
import os
import tempfile
import shutil
from PIL import Image
from layout_engine import generate_layout

def test_pdf_page_size_with_a5_trim_and_a4_sheet():
    """
    测试：A5 成书尺寸 + A4 输出纸张时，PDF 页面应该是 A4 尺寸
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # 准备测试素材
        # 封面 (A5: 148x210mm, 400dpi → 2323x3307px)
        front_path = os.path.join(tmpdir, "front_output", "cover.png")
        os.makedirs(os.path.dirname(front_path))
        front_img = Image.new("RGB", (2323, 3307), "red")
        front_img.save(front_path)

        # 书脊 (18mm x 210mm, 400dpi → 283x3307px)
        spine_path = os.path.join(tmpdir, "spine", "spine.png")
        os.makedirs(os.path.dirname(spine_path))
        spine_img = Image.new("RGB", (283, 3307), "blue")
        spine_img.save(spine_path)

        # 封底 (A5: 148x210mm, 400dpi → 2323x3307px)
        back_path = os.path.join(tmpdir, "back", "back.png")
        os.makedirs(os.path.dirname(back_path))
        back_img = Image.new("RGB", (2323, 3307), "green")
        back_img.save(back_path)

        # 调用生成函数
        trim_width_mm = 148   # A5
        trim_height_mm = 210  # A5
        spine_width_mm = 18.0
        sheet_width_mm = 210  # A4
        sheet_height_mm = 297 # A4

        pdf_filename = generate_layout(
            print_root=tmpdir,
            front_category="front_output",
            front_filename="cover.png",
            spine_filename="spine.png",
            back_filename="back.png",
            spine_width_mm=spine_width_mm,
            trim_width_mm=trim_width_mm,
            trim_height_mm=trim_height_mm,
            book_name="Test_Book",
            sheet_width_mm=sheet_width_mm,
            sheet_height_mm=sheet_height_mm,
        )

        pdf_path = os.path.join(tmpdir, pdf_filename)
        assert os.path.exists(pdf_path), f"PDF not generated at {pdf_path}"

        # 验证 PDF 页面尺寸
        import re
        with open(pdf_path, 'rb') as f:
            data = f.read()

        # 提取所有页面的 MediaBox
        pages = list(re.finditer(rb'/Type\s*/Page[^s]', data))
        assert len(pages) >= 2, f"Expected at least 2 pages, got {len(pages)}"

        expected_width_mm = 210.0   # A4
        expected_height_mm = 297.0  # A4
        tolerance_mm = 0.5  # 允许 0.5mm 误差

        for i, match in enumerate(pages[:2]):
            start = match.start()
            chunk = data[max(0, start-500):start+500].decode('latin-1', errors='ignore')
            mb = re.search(r'/MediaBox\s*\[([^\]]+)\]', chunk)
            assert mb, f"Page {i+1} has no MediaBox"

            nums = [float(x) for x in mb.group(1).split()]
            assert len(nums) == 4, f"Page {i+1} MediaBox has wrong format"

            w_pt, h_pt = nums[2], nums[3]
            w_mm = w_pt / 72 * 25.4
            h_mm = h_pt / 72 * 25.4

            print(f"Page {i+1}: {w_mm:.1f}mm x {h_mm:.1f}mm (expected: {expected_width_mm}mm x {expected_height_mm}mm)")

            assert abs(w_mm - expected_width_mm) < tolerance_mm, \
                f"Page {i+1} width {w_mm}mm != expected {expected_width_mm}mm"
            assert abs(h_mm - expected_height_mm) < tolerance_mm, \
                f"Page {i+1} height {h_mm}mm != expected {expected_height_mm}mm"

        print("✓ All pages have correct A4 size")

if __name__ == "__main__":
    test_pdf_page_size_with_a5_trim_and_a4_sheet()

import os
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image

DPI = 400


def mm_to_px(mm_value):
    return int(mm_value / 25.4 * DPI)


def generate_preview_layout(
    print_root,
    cover_filename,
    spine_filename,
    back_filename,
    spine_width_mm,
    trim_width_mm,
    trim_height_mm
):

    preview_path = os.path.join(print_root, "preview", "preview.png")

    spread_width_mm = trim_width_mm + spine_width_mm

    width_px = mm_to_px(spread_width_mm)
    height_px = mm_to_px(trim_height_mm)

    img = Image.new("RGB", (width_px, height_px), "white")

    cover = Image.open(os.path.join(print_root, "cover", cover_filename)).resize(
        (mm_to_px(trim_width_mm), height_px)
    )

    spine = Image.open(os.path.join(print_root, "spine", spine_filename)).resize(
        (mm_to_px(spine_width_mm), height_px)
    )

    img.paste(spine, (0, 0))
    img.paste(cover, (mm_to_px(spine_width_mm), 0))

    img.save(preview_path, dpi=(DPI, DPI))

    return "preview/preview.png"


def generate_layout(
    print_root,
    cover_filename,
    spine_filename,
    back_filename,
    spine_width_mm,
    trim_width_mm,
    trim_height_mm,
    book_name=None
):
    # 生成文件名：使用书名或默认名称
    if book_name:
        # 清理书名中的非法字符
        safe_name = "".join(c for c in book_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        if not safe_name:
            safe_name = "layout_print"
        filename = f"{safe_name}_print.pdf"
    else:
        filename = "layout_print.pdf"

    output_pdf = os.path.join(print_root, filename)
    c = canvas.Canvas(output_pdf)

    cover_path = os.path.join(print_root, "cover", cover_filename)
    spine_path = os.path.join(print_root, "spine", spine_filename)
    back_path = os.path.join(print_root, "back", back_filename)

    # A5 / B5 → 2页
    if trim_width_mm in [148, 176]:

        spread_width_mm = trim_width_mm + spine_width_mm
        c.setPageSize((spread_width_mm * mm, trim_height_mm * mm))

        c.drawImage(ImageReader(spine_path), 0, 0,
                    width=spine_width_mm * mm,
                    height=trim_height_mm * mm)

        c.drawImage(ImageReader(cover_path),
                    spine_width_mm * mm, 0,
                    width=trim_width_mm * mm,
                    height=trim_height_mm * mm)

        c.showPage()

        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        c.drawImage(ImageReader(back_path), 0, 0,
                    width=trim_width_mm * mm,
                    height=trim_height_mm * mm)

        c.showPage()

    # A4 → 3页
    else:

        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        c.drawImage(ImageReader(cover_path), 0, 0,
                    width=trim_width_mm * mm,
                    height=trim_height_mm * mm)
        c.showPage()

        c.setPageSize((spine_width_mm * mm, trim_height_mm * mm))
        c.drawImage(ImageReader(spine_path), 0, 0,
                    width=spine_width_mm * mm,
                    height=trim_height_mm * mm)
        c.showPage()

        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        c.drawImage(ImageReader(back_path), 0, 0,
                    width=trim_width_mm * mm,
                    height=trim_height_mm * mm)
        c.showPage()

    c.save()

    return filename
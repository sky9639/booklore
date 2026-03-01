import os
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import black
from PIL import Image

DPI = 400


def mm_to_px(mm_value):
    return int(mm_value / 25.4 * DPI)


# ================================
# PDF 生成
# ================================

def generate_layout(
    book_path,
    spine_path,
    back_path,
    spine_width_mm,
    trim_width_mm,
    trim_height_mm,
    output_dir
):

    output_pdf = os.path.join(output_dir, "layout_print.pdf")

    trim_size = (trim_width_mm, trim_height_mm)

    c = canvas.Canvas(output_pdf)

    # A5/B5 → 2页
    if trim_width_mm in [148, 176]:

        spread_width_mm = trim_width_mm + spine_width_mm

        c.setPageSize((spread_width_mm * mm, trim_height_mm * mm))

        book_folder = os.path.dirname(book_path)
        cover_path = os.path.join(book_folder, "cover.jpg")

        cover = ImageReader(cover_path)
        spine = ImageReader(spine_path)

        # 书脊
        c.drawImage(
            spine,
            0,
            0,
            width=spine_width_mm * mm,
            height=trim_height_mm * mm
        )

        # 封面
        c.drawImage(
            cover,
            spine_width_mm * mm,
            0,
            width=trim_width_mm * mm,
            height=trim_height_mm * mm
        )

        c.showPage()

        # 第二页 封底
        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        back = ImageReader(back_path)

        c.drawImage(
            back,
            0,
            0,
            width=trim_width_mm * mm,
            height=trim_height_mm * mm
        )

        c.showPage()

    # A4 → 3页
    else:

        book_folder = os.path.dirname(book_path)
        cover_path = os.path.join(book_folder, "cover.jpg")

        # 封面
        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        cover = ImageReader(cover_path)

        c.drawImage(
            cover,
            0,
            0,
            width=trim_width_mm * mm,
            height=trim_height_mm * mm
        )

        c.showPage()

        # 书脊
        c.setPageSize((spine_width_mm * mm, trim_height_mm * mm))
        spine = ImageReader(spine_path)

        c.drawImage(
            spine,
            0,
            0,
            width=spine_width_mm * mm,
            height=trim_height_mm * mm
        )

        c.showPage()

        # 封底
        c.setPageSize((trim_width_mm * mm, trim_height_mm * mm))
        back = ImageReader(back_path)

        c.drawImage(
            back,
            0,
            0,
            width=trim_width_mm * mm,
            height=trim_height_mm * mm
        )

        c.showPage()

    c.save()
    return output_pdf


# ================================
# PNG 预览
# ================================

def generate_preview_layout(
    book_path,
    spine_path,
    back_path,
    spine_width_mm,
    trim_width_mm,
    trim_height_mm,
    output_dir
):

    preview_path = os.path.join(output_dir, "preview.png")

    spread_width_mm = trim_width_mm + spine_width_mm

    width_px = mm_to_px(spread_width_mm)
    height_px = mm_to_px(trim_height_mm)

    img = Image.new("RGB", (width_px, height_px), "white")

    book_folder = os.path.dirname(book_path)
    cover_path = os.path.join(book_folder, "cover.jpg")

    cover = Image.open(cover_path).resize(
        (mm_to_px(trim_width_mm), height_px)
    )

    spine = Image.open(spine_path).resize(
        (mm_to_px(spine_width_mm), height_px)
    )

    img.paste(spine, (0, 0))
    img.paste(cover, (mm_to_px(spine_width_mm), 0))

    img.save(preview_path, dpi=(DPI, DPI))
    return preview_path
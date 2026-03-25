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
    front_category,
    front_filename,
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

    # 检查文件是否存在，避免空图
    front_path = os.path.join(print_root, front_category, front_filename) if front_category and front_filename else None
    spine_path = os.path.join(print_root, "spine", spine_filename) if spine_filename else None

    if not front_path or not os.path.exists(front_path):
        raise FileNotFoundError(f"Front output file not found: {front_filename}")

    if not spine_path or not os.path.exists(spine_path):
        raise FileNotFoundError(f"Spine file not found: {spine_filename}")

    with Image.open(front_path) as front_image:
        front = front_image.resize(
            (mm_to_px(trim_width_mm), height_px)
        )

    with Image.open(spine_path) as spine_image:
        spine = spine_image.resize(
            (mm_to_px(spine_width_mm), height_px)
        )

    img.paste(spine, (0, 0))
    img.paste(front, (mm_to_px(spine_width_mm), 0))

    img.save(preview_path, dpi=(DPI, DPI))

    return "preview/preview.png"


def generate_layout(
    print_root,
    front_category,
    front_filename,
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

    front_path = os.path.join(print_root, front_category, front_filename)
    spine_path = os.path.join(print_root, "spine", spine_filename)
    back_path = os.path.join(print_root, "back", back_filename)

    # 检查文件是否存在
    if not os.path.exists(front_path):
        raise FileNotFoundError(f"Front output file not found: {front_filename}")
    if not os.path.exists(spine_path):
        raise FileNotFoundError(f"Spine file not found: {spine_filename}")
    if not os.path.exists(back_path):
        raise FileNotFoundError(f"Back file not found: {back_filename}")

    # A5 / B5 → 2页
    if trim_width_mm in [148, 176]:

        spread_width_mm = trim_width_mm + spine_width_mm
        c.setPageSize((spread_width_mm * mm, trim_height_mm * mm))

        c.drawImage(ImageReader(spine_path), 0, 0,
                    width=spine_width_mm * mm,
                    height=trim_height_mm * mm)

        c.drawImage(ImageReader(front_path),
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
        c.drawImage(ImageReader(front_path), 0, 0,
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
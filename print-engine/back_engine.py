import os
from PIL import Image, ImageDraw, ImageFont

DPI = 400


def mm_to_px(mm):
    return int(mm / 25.4 * DPI)


def generate_back(book_path, output_dir):
    output_path = os.path.join(output_dir, "auto_back.jpg")

    # 默认按 A5 高度生成（与 layout 保持一致）
    trim_width_mm = 148
    trim_height_mm = 210

    width_px = mm_to_px(trim_width_mm)
    height_px = mm_to_px(trim_height_mm)

    cover_path = os.path.join(os.path.dirname(book_path), "cover.jpg")
    cover = Image.open(cover_path).convert("RGB")

    # 用封面缩小做淡化背景
    bg = cover.resize((width_px, height_px))
    bg = bg.point(lambda p: p * 0.9)  # 略微变暗

    img = Image.new("RGB", (width_px, height_px))
    img.paste(bg, (0, 0))

    draw = ImageDraw.Draw(img)

    # 文件名作为标题
    title = os.path.splitext(os.path.basename(book_path))[0]

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(height_px * 0.06))
    except:
        font = ImageFont.load_default()

    draw.text(
        (width_px // 2, height_px // 2),
        title,
        fill="white",
        anchor="mm",
        font=font
    )

    img.save(output_path, dpi=(DPI, DPI))
    return output_path
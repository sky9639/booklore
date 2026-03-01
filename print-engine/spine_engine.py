import os
from PIL import Image, ImageDraw, ImageFont

DPI = 400


def mm_to_px(mm):
    return int(mm / 25.4 * DPI)


def extract_main_color(image):
    small = image.resize((50, 50))
    colors = small.getcolors(50 * 50)
    colors.sort(reverse=True)
    return colors[0][1]


def generate_spine(book_path, spine_width_mm, trim_height_mm, output_dir):
    output_path = os.path.join(output_dir, "auto_spine.jpg")

    width_px = mm_to_px(spine_width_mm)
    height_px = mm_to_px(trim_height_mm)

    if width_px < 20:
        width_px = 20  # 防止太薄

    cover_path = os.path.join(os.path.dirname(book_path), "cover.jpg")
    cover = Image.open(cover_path).convert("RGB")

    main_color = extract_main_color(cover)

    img = Image.new("RGB", (width_px, height_px), main_color)
    draw = ImageDraw.Draw(img)

    # 使用文件名作为标题
    title = os.path.splitext(os.path.basename(book_path))[0]

    # 尝试使用系统字体
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(height_px * 0.05))
    except:
        font = ImageFont.load_default()

    # 创建旋转文本画布（先横着写）
    text_img = Image.new("RGBA", (height_px, width_px), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_img)

    text_draw.text(
        (height_px // 2, width_px // 2),
        title,
        fill="white",
        anchor="mm",
        font=font
    )

    rotated = text_img.rotate(90, expand=True)

    img.paste(rotated, (0, 0), rotated)

    img.save(output_path, dpi=(DPI, DPI))
    return output_path
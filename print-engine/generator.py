import os
from datetime import datetime

from pdf_analyzer import get_pdf_page_count
from spine_engine import generate_spine
from back_engine import generate_back
from layout_engine import generate_layout, generate_preview_layout
from utils import calculate_spine_width


def generate_print_job(config: dict, preview_only: bool = False):

    book_path = config["book_path"]
    book_folder = os.path.dirname(book_path)
    print_root = os.path.join(book_folder, ".print")
    os.makedirs(print_root, exist_ok=True)

    # 1️⃣ 页数
    page_count = config.get("page_count") or get_pdf_page_count(book_path)

    # 2️⃣ 计算书脊宽度（mm）
    paper_thickness = config.get("paper_thickness", 0.06)
    spine_width_mm = calculate_spine_width(page_count, paper_thickness)

    # 3️⃣ trim_size 决定高度
    trim_size = config.get("trim_size", "A5")

    if trim_size == "A5":
        trim_width_mm = 148
        trim_height_mm = 210
    elif trim_size == "B5":
        trim_width_mm = 176
        trim_height_mm = 250
    else:
        trim_width_mm = 210
        trim_height_mm = 297

    # 4️⃣ 生成书脊
    if config["spine_mode"] == "auto":
        spine_path = generate_spine(
            book_path=book_path,
            spine_width_mm=spine_width_mm,
            trim_height_mm=trim_height_mm,
            output_dir=print_root
        )
    else:
        spine_path = config["uploaded_spine_path"]

    # 5️⃣ 生成封底
    if config["back_mode"] == "auto":
        back_path = generate_back(
            book_path=book_path,
            output_dir=print_root
        )
    else:
        back_path = config["uploaded_back_path"]

    # 6️⃣ Preview 或 Generate
    if preview_only:

        preview_png = generate_preview_layout(
            book_path=book_path,
            spine_path=spine_path,
            back_path=back_path,
            spine_width_mm=spine_width_mm,
            trim_width_mm=trim_width_mm,
            trim_height_mm=trim_height_mm,
            output_dir=print_root
        )

        return {
            "preview_png": preview_png,
            "page_count": page_count,
            "spine_width_mm": spine_width_mm
        }

    else:

        output_pdf = generate_layout(
            book_path=book_path,
            spine_path=spine_path,
            back_path=back_path,
            spine_width_mm=spine_width_mm,
            trim_width_mm=trim_width_mm,
            trim_height_mm=trim_height_mm,
            output_dir=print_root
        )

        return {
            "output_pdf": output_pdf,
            "page_count": page_count,
            "spine_width_mm": spine_width_mm,
            "generated_at": datetime.now().isoformat()
        }
import fitz
import os
from datetime import datetime


DPI = 400


def extract_cover_page(book_path: str, page_number: int, print_root: str):

    doc = fitz.open(book_path)

    page_index = page_number - 1
    if page_index < 0 or page_index >= doc.page_count:
        doc.close()
        raise ValueError("Invalid page number")

    page = doc.load_page(page_index)
    pix = page.get_pixmap(dpi=DPI)

    folder = os.path.join(print_root, "cover")
    os.makedirs(folder, exist_ok=True)

    filename = f"cover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    full_path = os.path.join(folder, filename)

    pix.save(full_path)
    doc.close()

    return filename
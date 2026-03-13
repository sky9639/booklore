import fitz


def get_pdf_page_count(pdf_path: str) -> int:
    """
    获取 PDF 页数
    """

    with fitz.open(pdf_path) as doc:
        return doc.page_count
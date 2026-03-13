def calculate_spine_width(page_count: int, paper_thickness_mm: float) -> float:
    return round(page_count * paper_thickness_mm, 2)
    
    
def upgrade_workspace_schema(ws: dict, request) -> dict:
    """
    Workspace Schema 自动升级
    """

    # ------------------------------
    # schema version
    # ------------------------------
    if "schema_version" not in ws:
        ws["schema_version"] = 1

    # ------------------------------
    # book_name
    # ------------------------------
    if "book_name" not in ws:

        if hasattr(request, "book_title") and request.book_title:
            ws["book_name"] = request.book_title
        else:
            ws["book_name"] = ""

    # ------------------------------
    # cover
    # ------------------------------
    if not isinstance(ws.get("cover"), dict):

        ws["cover"] = {
            "selected": None,
            "history": []
        }

    if not isinstance(ws["cover"].get("history"), list):
        ws["cover"]["history"] = []

    # ------------------------------
    # spine
    # ------------------------------
    if not isinstance(ws.get("spine"), dict):

        ws["spine"] = {
            "selected": None,
            "history": []
        }

    if not isinstance(ws["spine"].get("history"), list):
        ws["spine"]["history"] = []

    # ------------------------------
    # back
    # ------------------------------
    if not isinstance(ws.get("back"), dict):

        ws["back"] = {
            "selected": None,
            "history": []
        }

    if not isinstance(ws["back"].get("history"), list):
        ws["back"]["history"] = []

    # ------------------------------
    # preview_path
    # ------------------------------
    if "preview_path" not in ws:
        ws["preview_path"] = None

    # ------------------------------
    # pdf_path
    # ------------------------------
    if "pdf_path" not in ws:
        ws["pdf_path"] = None

    # ------------------------------
    # updated_at
    # ------------------------------
    if "updated_at" not in ws:

        from datetime import datetime
        ws["updated_at"] = datetime.utcnow().isoformat()

    return ws
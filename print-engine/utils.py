def calculate_spine_width(page_count: int | None, paper_thickness: float | None) -> float:
    page_count = page_count or 0
    paper_thickness = paper_thickness or 0
    return round(page_count * paper_thickness, 2)


def ensure_ai_crop_history(ws: dict) -> list:
    history = ws.get("ai_crop_history")
    if not isinstance(history, list):
        history = []
        ws["ai_crop_history"] = history
    return history


def upsert_ai_crop_history_item(ws: dict, item: dict):
    history = ensure_ai_crop_history(ws)
    spread_filename = item.get("spread_filename")
    if not spread_filename:
        return

    filtered = [entry for entry in history if entry.get("spread_filename") != spread_filename]
    filtered.insert(0, item)
    ws["ai_crop_history"] = filtered


def find_ai_crop_history_item(ws: dict, spread_filename: str | None) -> dict | None:
    if not spread_filename:
        return None

    history = ensure_ai_crop_history(ws)
    for entry in history:
        if entry.get("spread_filename") == spread_filename:
            return entry
    return None


def remove_ai_crop_history_item(ws: dict, spread_filename: str | None) -> dict | None:
    if not spread_filename:
        return None

    history = ensure_ai_crop_history(ws)
    removed = None
    kept = []
    for entry in history:
        if entry.get("spread_filename") == spread_filename and removed is None:
            removed = entry
            continue
        kept.append(entry)
    ws["ai_crop_history"] = kept
    return removed


def upgrade_workspace_schema(ws: dict, request) -> dict:
    """
    Workspace Schema 自动升级
    """

    if "schema_version" not in ws:
        ws["schema_version"] = 1

    if "book_name" not in ws:
        if hasattr(request, "book_title") and request.book_title:
            ws["book_name"] = request.book_title
        elif isinstance(request, dict) and request.get("book_title"):
            ws["book_name"] = request["book_title"]
        else:
            ws["book_name"] = ""

    if not isinstance(ws.get("cover"), dict):
        ws["cover"] = {"selected": None, "history": []}
    if not isinstance(ws["cover"].get("history"), list):
        ws["cover"]["history"] = []

    if not isinstance(ws.get("spine"), dict):
        ws["spine"] = {"selected": None, "history": []}
    if not isinstance(ws["spine"].get("history"), list):
        ws["spine"]["history"] = []

    if not isinstance(ws.get("back"), dict):
        ws["back"] = {"selected": None, "history": []}
    if not isinstance(ws["back"].get("history"), list):
        ws["back"]["history"] = []

    if not isinstance(ws.get("front_output"), dict):
        ws["front_output"] = {"selected": None, "history": []}
    if not isinstance(ws["front_output"].get("history"), list):
        ws["front_output"]["history"] = []

    if "preview_path" not in ws:
        ws["preview_path"] = None

    if "pdf_path" not in ws:
        ws["pdf_path"] = None

    if "updated_at" not in ws:
        from datetime import datetime, timezone
        ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    if "ai_crop_draft" not in ws:
        ws["ai_crop_draft"] = None

    if not isinstance(ws.get("ai_crop_history"), list):
        ws["ai_crop_history"] = []

    return ws

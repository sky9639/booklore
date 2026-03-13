import os
import json
from datetime import datetime


def get_print_root(book_path: str):
    book_folder = os.path.dirname(book_path)
    print_root = os.path.join(book_folder, ".print")
    os.makedirs(print_root, exist_ok=True)

    for sub in ["cover", "spine", "back", "preview"]:
        os.makedirs(os.path.join(print_root, sub), exist_ok=True)

    return print_root


def get_workspace_path(print_root: str):
    return os.path.join(print_root, "workspace.json")


def load_workspace(book_path: str):
    print_root = get_print_root(book_path)
    ws_path = get_workspace_path(print_root)

    if not os.path.exists(ws_path):
        return None

    with open(ws_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_workspace(book_path: str, workspace: dict):
    print_root = get_print_root(book_path)
    ws_path = get_workspace_path(print_root)

    workspace["updated_at"] = datetime.now().isoformat()

    with open(ws_path, "w", encoding="utf-8") as f:
        json.dump(workspace, f, indent=2, ensure_ascii=False)
import os
import json
from datetime import datetime, timezone


def get_print_root(book_path: str):
    book_folder = os.path.dirname(book_path)
    print_root = os.path.join(book_folder, ".print")
    os.makedirs(print_root, exist_ok=True)

    for sub in ["cover", "spine", "back", "preview", "front_output"]:
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
    """
    保存 workspace.json，确保原子写入。

    注意：
    - 自动更新 updated_at 时间戳
    - 使用临时文件 + 原子 rename 避免写入过程中被读取到不完整数据
    - 多入口写同一份 workspace.json 时，最后一次写入会覆盖前面的修改
    """
    print_root = get_print_root(book_path)
    ws_path = get_workspace_path(print_root)

    workspace["updated_at"] = datetime.now(timezone.utc).isoformat()

    temp_path = ws_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(workspace, f, indent=2, ensure_ascii=False)

    os.replace(temp_path, ws_path)

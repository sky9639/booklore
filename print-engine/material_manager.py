import os
from datetime import datetime


MAX_HISTORY = 5


def add_material(print_root: str, category: str, file_bytes: bytes, ext: str):

    folder = os.path.join(print_root, category)
    os.makedirs(folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{category}_{timestamp}.{ext}"
    full_path = os.path.join(folder, filename)

    with open(full_path, "wb") as f:
        f.write(file_bytes)

    return full_path


def update_history(workspace: dict, category: str, filename: str):

    history = workspace[category]["history"]

    if filename in history:
        history.remove(filename)

    history.insert(0, filename)

    if len(history) > MAX_HISTORY:
        history.pop()

    workspace[category]["selected"] = filename
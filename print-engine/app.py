import os
import threading
import uuid
from datetime import datetime

import requests
from cover_extractor import *

# AI 配置从 booklore.env 读取（COMFYUI_API_URL / JANUS_API_URL）
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from layout_engine import *
from material_manager import *
from pdf_analyzer import get_pdf_page_count
from pydantic import BaseModel
from utils import calculate_spine_width, upgrade_workspace_schema
from workspace_manager import *

load_dotenv("booklore.env")

from ai_generator import generate_ai_material

app = FastAPI()

# CORS：允许前端（Angular dev server 4200）直接访问 SSE 接口
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def touch_workspace(ws: dict):
    ws["updated_at"] = datetime.utcnow().isoformat()


# ==============================
# Request Models
# ==============================


class InitRequest(BaseModel):
    book_path: str
    book_title: str | None = None
    book_page_count: int | None = None
    book_id: int | None = None


class PreviewRequest(BaseModel):
    book_path: str
    paper_thickness: float = 0.06
    page_count: int | None = None
    spine_mode: str = "auto"
    back_mode: str = "auto"
    book_title: str | None = None
    book_page_count: int | None = None
    book_id: int | None = None
    trim_size: str = "A5"


class SaveParamsRequest(BaseModel):
    book_path: str
    trim_size: str
    page_count: int
    paper_thickness: float
    spine_width_mm: float


# ==============================
# 初始化 Workspace
# ==============================


@app.post("/workspace/init")
def init_workspace(request: InitRequest):

    ws = load_workspace(request.book_path)

    if ws:
        ws = upgrade_workspace_schema(ws, request)
        touch_workspace(ws)
        save_workspace(request.book_path, ws)
        return ws

    if request.book_path.lower().endswith(".pdf"):
        pdf_path = request.book_path
    else:
        pdf_path = request.book_path + ".pdf"

    page_count = request.book_page_count
    if page_count is None:
        page_count = get_pdf_page_count(pdf_path)

    ws = {
        "book_name": request.book_title or "",
        "trim_size": "A5",
        "page_count": page_count,
        "paper_thickness": 0.06,
        "spine_width_mm": calculate_spine_width(page_count, 0.06),
        "cover": {"selected": None, "history": []},
        "spine": {"selected": None, "history": []},
        "back": {"selected": None, "history": []},
        "preview_path": None,
        "pdf_path": None,
        "updated_at": datetime.utcnow().isoformat(),
    }

    print_root = get_print_root(request.book_path)

    try:
        if request.book_id:
            url = f"http://backend:6060/api/v1/media/book/{request.book_id}/cover"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                filename = add_material(print_root, "cover", r.content, "jpg")
                update_history(ws, "cover", filename)
    except Exception as e:
        print("BookLore cover fetch failed:", e)

    if not ws["cover"]["history"]:
        try:
            filename = extract_cover_page(request.book_path, 1, print_root)
            update_history(ws, "cover", filename)
        except Exception as e:
            print("PDF cover extract failed:", e)

    save_workspace(request.book_path, ws)
    return ws


# ==============================
# 从 PDF 抽取封面
# ==============================


@app.post("/workspace/cover/extract")
def extract_cover(request: dict):
    book_path = request["book_path"]
    page = request["page"]
    print_root = get_print_root(book_path)
    ws = load_workspace(book_path)
    if not ws:
        raise RuntimeError("workspace not initialized")
    filename = extract_cover_page(book_path, page, print_root)
    update_history(ws, "cover", filename)
    touch_workspace(ws)
    save_workspace(book_path, ws)
    return ws


# ==============================
# 上传素材
# ==============================


@app.post("/workspace/upload/{category}")
async def upload_material(
    category: str, book_path: str = Form(...), file: UploadFile = File(...)
):
    print_root = get_print_root(book_path)
    ws = load_workspace(book_path)
    ext = file.filename.split(".")[-1]
    content = await file.read()
    filename = add_material(print_root, category, content, ext)
    update_history(ws, category, filename)
    touch_workspace(ws)
    save_workspace(book_path, ws)
    return ws


# ==============================
# 保存成书参数
# ==============================


@app.post("/workspace/params")
def save_workspace_params(request: SaveParamsRequest):
    ws = load_workspace(request.book_path)

    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws["trim_size"] = request.trim_size
    ws["page_count"] = request.page_count
    ws["paper_thickness"] = request.paper_thickness
    ws["spine_width_mm"] = request.spine_width_mm

    # 参数变化，旧 PDF 作废
    ws["pdf_path"] = None

    touch_workspace(ws)
    save_workspace(request.book_path, ws)
    return ws


# ==============================
# 生成预览
# ==============================


@app.post("/preview")
def preview(request: PreviewRequest):
    print_root = get_print_root(request.book_path)
    ws = load_workspace(request.book_path)

    page_count = request.page_count or ws["page_count"]
    paper_thickness = request.paper_thickness or ws["paper_thickness"]
    spine_width = calculate_spine_width(page_count, paper_thickness)

    trim_map = {"A5": (148, 210), "B5": (176, 250), "A4": (210, 297)}
    trim_width_mm, trim_height_mm = trim_map[request.trim_size]

    preview_path = generate_preview_layout(
        print_root,
        ws["cover"]["selected"],
        ws["spine"]["selected"],
        ws["back"]["selected"],
        spine_width,
        trim_width_mm,
        trim_height_mm,
    )

    ws["page_count"] = page_count
    ws["paper_thickness"] = paper_thickness
    ws["spine_width_mm"] = spine_width
    ws["preview_path"] = preview_path

    touch_workspace(ws)
    save_workspace(request.book_path, ws)
    return ws


# ==============================
# 生成最终 PDF
# ==============================


@app.post("/generate")
def generate(request: PreviewRequest):
    print_root = get_print_root(request.book_path)
    ws = load_workspace(request.book_path)

    page_count = request.page_count or ws["page_count"]
    paper_thickness = request.paper_thickness or ws["paper_thickness"]
    spine_width = calculate_spine_width(page_count, paper_thickness)

    trim_map = {"A5": (148, 210), "B5": (176, 250), "A4": (210, 297)}

    trim_size = request.trim_size or ws.get("trim_size", "A5")
    trim_width_mm, trim_height_mm = trim_map[trim_size]

    pdf_filename = generate_layout(
        print_root,
        ws["cover"]["selected"],
        ws["spine"]["selected"],
        ws["back"]["selected"],
        spine_width,
        trim_width_mm,
        trim_height_mm,
    )

    abs_pdf_path = os.path.join(print_root, pdf_filename)
    ws["pdf_path"] = abs_pdf_path
    ws["trim_size"] = trim_size
    ws["page_count"] = page_count
    ws["paper_thickness"] = paper_thickness
    ws["spine_width_mm"] = spine_width

    touch_workspace(ws)
    save_workspace(request.book_path, ws)
    return ws


# ==============================
# AI 生成书脊 + 封底（合并任务版）
# ==============================
#
# 架构说明：
#   - 前端只发一次 POST /workspace/ai-generate/start（不带 target，默认生成全部）
#   - 后端子线程依次完成 spine(0~50%) → back(50~100%)
#   - 前端连一次 SSE /workspace/ai-generate/progress/{task_id}，全程不断线
#   - done 事件携带最终 workspace，前端直接刷新缩略图
#
import json
import threading
import uuid

_ai_tasks: dict = {}
_ai_tasks_lock = threading.Lock()


class AiGenerateRequest(BaseModel):
    book_path: str
    book_id: int | None = None
    target: str = "all"  # "all" | "spine" | "back"
    book_title: str | None = None
    authors: list[str] = []
    description: str | None = None
    categories: list[str] = []
    trim_size: str = "A5"
    spine_width_mm: float = 4.74
    count: int = 1
    quality: str = "medium"


def _run_ai_task_all(
    task_id: str,
    request: AiGenerateRequest,
    print_root: str,
    cover_selected: str,
    ws: dict,
):
    """
    子线程：依次生成 spine(0~50%) + back(50~100%)
    进度实时写入 _ai_tasks[task_id]["pct"]
    每步完成后写入 _ai_tasks[task_id]["spine_done"] / "back_done"
    """
    targets = ["spine", "back"] if request.target == "all" else [request.target]
    n = len(targets)

    def _make_cb(phase_start: int, phase_end: int):
        def _cb(pct: int):
            mapped = phase_start + int((pct / 100) * (phase_end - phase_start))
            with _ai_tasks_lock:
                if task_id in _ai_tasks:
                    _ai_tasks[task_id]["pct"] = min(mapped, phase_end - 1)

        return _cb

    try:
        for i, target in enumerate(targets):
            phase_start = int(i * 100 / n)
            phase_end = int((i + 1) * 100 / n)

            with _ai_tasks_lock:
                _ai_tasks[task_id]["phase"] = target

            filenames = generate_ai_material(
                print_root=print_root,
                cover_filename=cover_selected,
                target=target,
                book_title=request.book_title or ws.get("book_name", ""),
                authors=request.authors,
                description=request.description or "",
                categories=request.categories,
                trim_size=request.trim_size or ws.get("trim_size", "A5"),
                spine_width_mm=request.spine_width_mm or ws.get("spine_width_mm", 4.74),
                count=max(1, min(request.count, 3)),
                quality=request.quality,
                progress_callback=_make_cb(phase_start, phase_end),
            )

            if not filenames:
                raise RuntimeError(f"{target} AI generation produced no results")

            for filename in reversed(filenames):
                update_history(ws, target, filename)
            ws[target]["selected"] = filenames[0]
            touch_workspace(ws)
            save_workspace(request.book_path, ws)

            with _ai_tasks_lock:
                _ai_tasks[task_id][f"{target}_done"] = filenames[0]
                _ai_tasks[task_id]["pct"] = phase_end

        # done 前重新从磁盘读最新 workspace（合并生成中用户的删除操作）
        fresh_ws = load_workspace(request.book_path) or ws
        # 把本次 AI 生成的文件合并到最新 workspace
        for tgt in targets:
            done_file = _ai_tasks.get(task_id, {}).get(f"{tgt}_done")
            if done_file and tgt in fresh_ws:
                # 确保新文件在 history 第一位，selected 指向它
                hist = fresh_ws[tgt].get("history") or []
                if done_file not in hist:
                    hist.insert(0, done_file)
                    fresh_ws[tgt]["history"] = hist[:5]
                fresh_ws[tgt]["selected"] = done_file

        with _ai_tasks_lock:
            _ai_tasks[task_id]["pct"] = 100
            _ai_tasks[task_id]["status"] = "done"
            _ai_tasks[task_id]["ws"] = fresh_ws

    except Exception as e:
        import traceback

        traceback.print_exc()
        with _ai_tasks_lock:
            _ai_tasks[task_id]["status"] = "error"
            _ai_tasks[task_id]["error"] = str(e)


@app.post("/workspace/ai-generate/start")
def ai_generate_start(request: AiGenerateRequest):
    """
    启动 AI 生成任务，立即返回 task_id。
    target="all"（默认）：依次生成书脊和封底，进度 0~100%
    target="spine"|"back"：只生成单个，进度 0~100%
    """
    ws = load_workspace(request.book_path)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cover_selected = ws["cover"].get("selected")
    if not cover_selected:
        raise HTTPException(status_code=400, detail="No cover image selected")

    if request.target not in ("all", "spine", "back"):
        raise HTTPException(status_code=400, detail="target must be all/spine/back")

    task_id = str(uuid.uuid4())
    print_root = get_print_root(request.book_path)

    with _ai_tasks_lock:
        _ai_tasks[task_id] = {"status": "running", "pct": 0, "phase": "starting"}

    threading.Thread(
        target=_run_ai_task_all,
        args=(task_id, request, print_root, cover_selected, ws),
        daemon=True,
    ).start()

    return {"task_id": task_id}


@app.get("/workspace/ai-generate/progress/{task_id}")
def ai_generate_progress(task_id: str):
    """
    SSE 流，实时推送进度。
    事件格式：
        {"pct": 45,  "status": "running", "phase": "spine"}
        {"pct": 100, "status": "done",    "ws": {...}}
        {"pct": 0,   "status": "error",   "error": "..."}
    心跳（每10秒）：": heartbeat" — 前端 EventSource 忽略，但保持连接活跃
    """
    import time as _time

    def _stream():
        last_pct = -1
        last_heartbeat = _time.time()
        deadline = _time.time() + 1200  # 20分钟上限

        while _time.time() < deadline:
            with _ai_tasks_lock:
                task = dict(_ai_tasks.get(task_id, {}))

            if not task:
                yield f"data: {json.dumps({'status': 'error', 'error': 'task not found'})}\n\n"
                return

            pct = task.get("pct", 0)
            status = task.get("status", "running")
            phase = task.get("phase", "")

            if status == "done":
                yield f"data: {json.dumps({'pct': 100, 'status': 'done', 'ws': task.get('ws', {})})}\n\n"
                with _ai_tasks_lock:
                    _ai_tasks.pop(task_id, None)
                return

            if status == "error":
                yield f"data: {json.dumps({'pct': pct, 'status': 'error', 'error': task.get('error', '未知错误')})}\n\n"
                with _ai_tasks_lock:
                    _ai_tasks.pop(task_id, None)
                return

            if pct != last_pct:
                last_pct = pct
                last_heartbeat = _time.time()
                yield f"data: {json.dumps({'pct': pct, 'status': 'running', 'phase': phase})}\n\n"

            elif _time.time() - last_heartbeat > 10:
                last_heartbeat = _time.time()
                yield ": heartbeat\n\n"

            _time.sleep(0.3)

        yield f"data: {json.dumps({'status': 'error', 'error': 'generation timeout (20min)'})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/workspace/ai-generate")
def ai_generate(request: AiGenerateRequest):
    """同步接口（向后兼容）"""
    ws = load_workspace(request.book_path)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cover_selected = ws["cover"].get("selected")
    if not cover_selected:
        raise HTTPException(status_code=400, detail="No cover image selected")

    targets = ["spine", "back"] if request.target == "all" else [request.target]
    print_root = get_print_root(request.book_path)

    try:
        for target in targets:
            filenames = generate_ai_material(
                print_root=print_root,
                cover_filename=cover_selected,
                target=target,
                book_title=request.book_title or ws.get("book_name", ""),
                authors=request.authors,
                description=request.description or "",
                categories=request.categories,
                trim_size=request.trim_size or ws.get("trim_size", "A5"),
                spine_width_mm=request.spine_width_mm or ws.get("spine_width_mm", 4.74),
                count=max(1, min(request.count, 3)),
                quality=request.quality,
            )
            if filenames:
                for filename in reversed(filenames):
                    update_history(ws, target, filename)
                ws[target]["selected"] = filenames[0]

    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    touch_workspace(ws)
    save_workspace(request.book_path, ws)
    return ws

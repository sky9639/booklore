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
# PDF信息和格式化相关API
# ==============================

from pdf_info import get_pdf_info
from pdf_resizer import PdfResizer

# PDF格式化任务存储
_pdf_resize_tasks = {}
_pdf_resize_tasks_lock = threading.Lock()


class PdfInfoRequest(BaseModel):
    book_path: str


class PdfResizeRequest(BaseModel):
    book_path: str
    target_size: str  # A4/A5/B5


@app.post("/pdf/info")
def pdf_info(request: PdfInfoRequest):
    """
    获取PDF文件信息（尺寸、页数等）

    Args:
        request: 包含book_path的请求

    Returns:
        {
            "success": True/False,
            "data": {
                "width_mm": 210.0,
                "height_mm": 297.0,
                "orientation": "portrait",
                "page_count": 150,
                "has_mixed_sizes": False,
                "file_size_mb": 12.5
            },
            "error": "错误信息"
        }
    """
    return get_pdf_info(request.book_path)


@app.post("/pdf/resize/start")
def pdf_resize_start(request: PdfResizeRequest):
    """
    启动PDF格式化任务

    Args:
        request: 包含book_path和target_size的请求

    Returns:
        {"task_id": "uuid"}
    """
    # 验证目标尺寸
    if request.target_size.upper() not in ['A4', 'A5', 'B5']:
        raise HTTPException(status_code=400, detail="target_size must be A4/A5/B5")

    task_id = str(uuid.uuid4())

    # 初始化任务状态
    with _pdf_resize_tasks_lock:
        _pdf_resize_tasks[task_id] = {
            "status": "running",
            "progress": 0,
            "stage": "准备开始...",
            "current_page": 0,
            "total_pages": 0
        }

    # 启动后台线程执行格式化
    threading.Thread(
        target=_run_pdf_resize_task,
        args=(task_id, request.book_path, request.target_size),
        daemon=True
    ).start()

    return {"task_id": task_id}


def _run_pdf_resize_task(task_id: str, book_path: str, target_size: str):
    """后台执行PDF格式化任务"""

    def progress_callback(data: dict):
        """进度回调"""
        with _pdf_resize_tasks_lock:
            if task_id in _pdf_resize_tasks:
                _pdf_resize_tasks[task_id].update(data)

    try:
        resizer = PdfResizer(book_path, target_size, progress_callback)
        result = resizer.resize()

        with _pdf_resize_tasks_lock:
            if result["success"]:
                _pdf_resize_tasks[task_id] = {
                    "status": "done",
                    "progress": 100,
                    "stage": "格式化完成！",
                    "new_size": result["new_size"]
                }
            else:
                _pdf_resize_tasks[task_id] = {
                    "status": "error",
                    "progress": 0,
                    "error": result["error"]
                }
    except Exception as e:
        with _pdf_resize_tasks_lock:
            _pdf_resize_tasks[task_id] = {
                "status": "error",
                "progress": 0,
                "error": str(e)
            }


@app.get("/pdf/resize/progress/{task_id}")
def pdf_resize_progress(task_id: str):
    """
    SSE流式推送PDF格式化进度

    事件格式：
        - 进度更新: {"progress": 45, "status": "running", "stage": "...", "current_page": 10, "total_pages": 150}
        - 完成: {"progress": 100, "status": "done", "stage": "格式化完成！", "new_size": {...}}
        - 错误: {"progress": 0, "status": "error", "error": "..."}
        - 心跳: ": heartbeat"

    Args:
        task_id: 任务ID

    Returns:
        StreamingResponse: SSE流
    """
    import time as _time

    def _stream():
        last_progress = -1
        last_stage = ""
        last_heartbeat = _time.time()
        deadline = _time.time() + 600  # 10分钟超时

        while _time.time() < deadline:
            # 读取任务状态
            with _pdf_resize_tasks_lock:
                task = dict(_pdf_resize_tasks.get(task_id, {}))

            if not task:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Task not found'})}\n\n"
                break

            # 发送进度更新
            progress = task.get("progress", 0)
            stage = task.get("stage", "")
            if progress != last_progress or stage != last_stage:
                yield f"data: {json.dumps(task)}\n\n"
                last_progress = progress
                last_stage = stage

            # 任务完成或失败
            if task.get("status") in ("done", "error"):
                yield f"data: {json.dumps(task)}\n\n"
                break

            # 心跳
            now = _time.time()
            if now - last_heartbeat > 10:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            _time.sleep(0.5)

    import json
    return StreamingResponse(_stream(), media_type="text/event-stream")



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
        ws.get("book_name", None),
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
    categories: list[str] = ["children's book"]  # 默认儿童图书（与本地测试一致）
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
    AI生成任务主线程

    依次生成 spine(0~50%) + back(50~100%)，或单独生成指定目标
    进度实时写入 _ai_tasks[task_id]，通过 SSE 推送到前端

    Args:
        task_id: 任务唯一标识
        request: 生成请求参数
        print_root: 素材存储根目录
        cover_selected: 封面文件名
        ws: workspace 状态字典
    """
    targets = ["spine", "back"] if request.target == "all" else [request.target]
    n = len(targets)
    total_tokens = 0

    def _make_cb(phase_start: int, phase_end: int):
        """
        创建进度回调函数，将 0-100% 映射到指定区间

        Args:
            phase_start: 阶段起始百分比（0-100）
            phase_end: 阶段结束百分比（0-100）

        Returns:
            回调函数，接收 (pct, stage) 参数
        """
        def _cb(pct: int, stage: str = ""):
            import time as _t

            # 将子任务进度映射到总进度
            mapped = phase_start + int((pct / 100) * (phase_end - phase_start))

            with _ai_tasks_lock:
                if task_id in _ai_tasks:
                    _ai_tasks[task_id]["pct"] = min(mapped, phase_end - 1)
                    if stage:
                        _ai_tasks[task_id]["stage"] = stage

            # 短暂延迟确保 SSE 轮询能捕获每个状态变化
            # 避免快速连续更新导致中间状态被跳过
            if stage:
                _t.sleep(0.15)

        return _cb

    try:
        for i, target in enumerate(targets):
            # 计算当前目标的进度区间
            phase_start = int(i * 100 / n)
            phase_end = int((i + 1) * 100 / n)

            # 更新当前阶段
            with _ai_tasks_lock:
                if task_id in _ai_tasks:
                    _ai_tasks[task_id]["phase"] = target

            # 调用 AI 生成
            result = generate_ai_material(
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

            # 处理返回值：兼容 (filenames, token_usage) 和 filenames 两种格式
            filenames = None
            if isinstance(result, tuple) and len(result) == 2:
                filenames, token_usage = result
                if token_usage and isinstance(token_usage, dict):
                    total_tokens += token_usage.get("total_tokens", 0)
            else:
                filenames = result

            if not filenames:
                raise RuntimeError(f"{target} AI generation produced no results")

            # 更新 workspace 历史记录
            for filename in reversed(filenames):
                update_history(ws, target, filename)
            ws[target]["selected"] = filenames[0]
            touch_workspace(ws)
            save_workspace(request.book_path, ws)

            # 记录完成状态
            with _ai_tasks_lock:
                if task_id in _ai_tasks:
                    _ai_tasks[task_id][f"{target}_done"] = filenames[0]
                    _ai_tasks[task_id]["pct"] = phase_end
                    _ai_tasks[task_id]["total_tokens"] = total_tokens

        # 重新加载 workspace，合并生成期间用户可能的其他操作
        fresh_ws = load_workspace(request.book_path) or ws

        # 将本次生成的文件合并到最新 workspace
        for tgt in targets:
            done_file = _ai_tasks.get(task_id, {}).get(f"{tgt}_done")
            if done_file and tgt in fresh_ws:
                hist = fresh_ws[tgt].get("history") or []
                if done_file not in hist:
                    hist.insert(0, done_file)
                    fresh_ws[tgt]["history"] = hist[:5]  # 保留最近5个
                fresh_ws[tgt]["selected"] = done_file

        # 标记任务完成
        with _ai_tasks_lock:
            if task_id in _ai_tasks:
                _ai_tasks[task_id]["pct"] = 100
                _ai_tasks[task_id]["status"] = "done"
                _ai_tasks[task_id]["ws"] = fresh_ws
                _ai_tasks[task_id]["total_tokens"] = total_tokens
                if total_tokens > 0:
                    _ai_tasks[task_id]["stage"] = f"生成完成，本次消耗 {total_tokens} tokens"

    except Exception as e:
        import traceback
        traceback.print_exc()
        with _ai_tasks_lock:
            if task_id in _ai_tasks:
                _ai_tasks[task_id]["status"] = "error"
                _ai_tasks[task_id]["error"] = str(e)


@app.post("/workspace/ai-generate/start")
def ai_generate_start(request: AiGenerateRequest):
    """
    启动 AI 生成任务

    Args:
        request: 生成请求参数
            - target: "all"（默认）生成书脊和封底，"spine"/"back" 单独生成
            - book_path: 书籍路径
            - 其他参数见 AiGenerateRequest

    Returns:
        {"task_id": "uuid"} 用于查询进度

    Raises:
        HTTPException: workspace 不存在、封面未选择、target 参数非法
    """
    ws = load_workspace(request.book_path)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cover_selected = ws.get("cover", {}).get("selected")
    if not cover_selected:
        raise HTTPException(status_code=400, detail="No cover image selected")

    if request.target not in ("all", "spine", "back"):
        raise HTTPException(status_code=400, detail="target must be all/spine/back")

    task_id = str(uuid.uuid4())
    print_root = get_print_root(request.book_path)

    # 初始化任务状态
    with _ai_tasks_lock:
        _ai_tasks[task_id] = {
            "status": "running",
            "pct": 0,
            "phase": "starting",
            "stage": "准备开始生成...",
            "total_tokens": 0
        }

    # 启动后台线程执行生成任务
    threading.Thread(
        target=_run_ai_task_all,
        args=(task_id, request, print_root, cover_selected, ws),
        daemon=True,
    ).start()

    return {"task_id": task_id}


@app.get("/workspace/ai-generate/progress/{task_id}")
def ai_generate_progress(task_id: str):
    """
    SSE 流式推送 AI 生成进度

    事件格式：
        - 进度更新: {"pct": 45, "status": "running", "phase": "spine", "stage": "...", "total_tokens": 100}
        - 完成: {"pct": 100, "status": "done", "ws": {...}, "total_tokens": 916}
        - 错误: {"pct": 0, "status": "error", "error": "..."}
        - 心跳: ": heartbeat" (每10秒，保持连接活跃)

    Args:
        task_id: 任务ID（由 /start 接口返回）

    Returns:
        StreamingResponse: text/event-stream 格式的 SSE 流
    """
    import time as _time

    def _stream():
        last_pct = -1
        last_stage = ""
        last_heartbeat = _time.time()
        deadline = _time.time() + 1200  # 20分钟超时

        while _time.time() < deadline:
            # 读取任务状态（复制一份避免长时间持锁）
            with _ai_tasks_lock:
                task = dict(_ai_tasks.get(task_id, {}))

            if not task:
                yield f"data: {json.dumps({'status': 'error', 'error': 'task not found'})}\n\n"
                return

            pct = task.get("pct", 0)
            status = task.get("status", "running")
            phase = task.get("phase", "")
            stage = task.get("stage", "")
            total_tokens = task.get("total_tokens", 0)

            # 任务完成
            if status == "done":
                done_data = {
                    'pct': 100,
                    'status': 'done',
                    'ws': task.get('ws', {}),
                    'total_tokens': total_tokens
                }
                if stage:
                    done_data['stage'] = stage
                yield f"data: {json.dumps(done_data)}\n\n"

                # 清理任务记录
                with _ai_tasks_lock:
                    _ai_tasks.pop(task_id, None)
                return

            # 任务失败
            if status == "error":
                yield f"data: {json.dumps({'pct': pct, 'status': 'error', 'error': task.get('error', '未知错误')})}\n\n"
                with _ai_tasks_lock:
                    _ai_tasks.pop(task_id, None)
                return

            # 进度或阶段有变化，推送更新
            if pct != last_pct or stage != last_stage:
                last_pct = pct
                last_stage = stage
                last_heartbeat = _time.time()

                progress_data = {'pct': pct, 'status': 'running', 'phase': phase}
                if stage:
                    progress_data['stage'] = stage
                if total_tokens > 0:
                    progress_data['total_tokens'] = total_tokens

                yield f"data: {json.dumps(progress_data)}\n\n"

            # 发送心跳保持连接
            elif _time.time() - last_heartbeat > 10:
                last_heartbeat = _time.time()
                yield ": heartbeat\n\n"

            # 轮询间隔（缩短以减少状态丢失）
            _time.sleep(0.1)

        # 超时
        yield f"data: {json.dumps({'status': 'error', 'error': 'generation timeout (20min)'})}\n\n"
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

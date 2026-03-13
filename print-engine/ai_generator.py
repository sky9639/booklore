#!/usr/bin/env python3
"""
ai_generator.py  —  Booklore Print Engine
版本：V3.0

修复内容（相较旧版）：
1. Janus 调用方式修正：改为 JSON body + image_base64，传入 target/authors/description/categories
2. ComfyUI 工作流修正：采用已验证的 comfyui_flux_outpaint.py 节点结构
   - 先 /upload/image 上传图片，用文件名引用（而非 base64）
   - 加入 ImageToMask 节点（channel="red"）
   - 加入 FluxGuidance 节点（guidance=3.5）
   - grow_mask_by=0，steps=20，weight_dtype=fp8_e4m3fn_fast
3. 画布构建逻辑修正：与 comfyui_flux_outpaint.py 完全一致
   - 封底参考宽 = min(cover_w, back_width_px)
   - 书脊参考宽 = spine_width_px * 4
4. 新增 WebSocket 进度推送：通过 progress_callback 回调传递步数百分比
5. 生成顺序固定：先 back（封底）再 spine（书脊），与已验证脚本一致

配置从 booklore.env 读取：
    COMFYUI_API_URL=http://ROG:8188
    JANUS_API_URL=http://ROG:8788
"""

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import requests
import websocket  # websocket-client
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv("booklore.env")

COMFYUI_API_URL = os.getenv("COMFYUI_API_URL", "http://ROG:8188")
JANUS_API_URL = os.getenv("JANUS_API_URL", "http://ROG:8788")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── 字体自动探测 ────────────────────────────────────────────────────────────
def _find_font_paths() -> tuple[str, str]:
    """返回 (normal_path, bold_path)，尽量找中文支持字体"""
    import glob

    normal_candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    ]
    all_fonts = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True) + glob.glob(
        "/usr/share/fonts/**/*.ttc", recursive=True
    )
    normal_candidates += all_fonts
    bold_candidates += all_fonts

    normal = next((p for p in normal_candidates if Path(p).exists()), "")
    bold = next((p for p in bold_candidates if Path(p).exists()), "")
    logger.info(f"[Font] normal={normal or 'PIL默认'}, bold={bold or 'PIL默认'}")
    return normal, bold


_FONT_NORMAL, _FONT_BOLD = _find_font_paths()


def _load_font(size: int, bold: bool = False):
    path = _FONT_BOLD if (bold and _FONT_BOLD) else _FONT_NORMAL
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# 尺寸映射（400 DPI）
# ─────────────────────────────────────────────────────────────────────────────

TRIM_SIZE_PX = {
    "A4": (1654, 2339),
    "A5": (1240, 1748),
    "B5": (1390, 1969),
}


# ─────────────────────────────────────────────────────────────────────────────
# Janus 风格分析（修正版）
# 接口：POST http://ROG:8788/analyze
# Body：JSON { image_base64, target, book_title, authors, description, categories }
# 返回：{ "prompt": "..." }
# ─────────────────────────────────────────────────────────────────────────────


def _analyze_style(
    front_img: Image.Image,
    target: str,
    book_title: str,
    authors: list,
    description: str,
    categories: list,
) -> str:
    """调用 Janus API 分析封面风格，返回英文 prompt 字符串。失败时返回空字符串。"""
    try:
        buf = io.BytesIO()
        front_img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        resp = requests.post(
            f"{JANUS_API_URL}/analyze",
            json={
                "image_base64": image_b64,
                "target": target,
                "book_title": book_title,
                "authors": authors,
                "description": description,
                "categories": categories,
            },
            timeout=120,
        )
        resp.raise_for_status()
        prompt = resp.json().get("prompt", "")
        logger.info(f"[Janus] {target} prompt: {prompt[:80]}...")
        return prompt
    except Exception as e:
        logger.warning(f"[Janus] 风格分析失败，使用默认 prompt: {e}")
        return ""


def _parse_janus_to_tags(style: str) -> str:
    """
    清洗 Janus 编号列表格式，只保留前4行（风格+天空色+地面色+光照），
    丢弃第5行内容词（避免 scattered bones / castle 等干扰生成内容）。
    """
    import re

    lines = [l.strip() for l in style.strip().splitlines() if l.strip()]
    tags = []
    for line in lines:
        clean = re.sub(r"^[0-9]+[.)\s]+", "", line).strip()
        if clean and len(tags) < 4:
            tags.append(clean.lower())
    return ", ".join(tags) if tags else style[:150]


# ─────────────────────────────────────────────────────────────────────────────
# ComfyUI：上传图片
# ─────────────────────────────────────────────────────────────────────────────


def _upload_image(img_bytes: bytes, filename: str) -> str:
    """上传图片到 ComfyUI，返回服务器端文件名。"""
    resp = requests.post(
        f"{COMFYUI_API_URL}/upload/image",
        files={"image": (filename, io.BytesIO(img_bytes), "image/png")},
        data={"overwrite": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["name"]


# ─────────────────────────────────────────────────────────────────────────────
# ComfyUI：构建工作流（与 comfyui_flux_outpaint.py 保持完全一致）
# ─────────────────────────────────────────────────────────────────────────────


def _build_flux_workflow(
    canvas_fn: str,
    mask_fn: str,
    prompt: str,
    seed: int,
    steps: int = 20,
    guidance: float = 3.5,
) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev.safetensors",
                "weight_dtype": "fp8_e4m3fn_fast",
            },
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "5": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "clip_l.safetensors",
                "clip_name2": "t5xxl_fp8_e4m3fn.safetensors",
                "type": "flux",
            },
        },
        "6": {"class_type": "LoadImage", "inputs": {"image": canvas_fn}},
        "7": {"class_type": "LoadImage", "inputs": {"image": mask_fn}},
        "8": {
            "class_type": "ImageToMask",
            "inputs": {"image": ["7", 0], "channel": "red"},
        },
        "9": {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {
                "pixels": ["6", 0],
                "vae": ["2", 0],
                "mask": ["8", 0],
                "grow_mask_by": 0,  # 已验证：0，不扩展边缘
            },
        },
        "10": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["5", 0], "text": prompt},
        },
        "11": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["5", 0], "text": ""},
        },
        "12": {
            "class_type": "FluxGuidance",
            "inputs": {"conditioning": ["10", 0], "guidance": guidance},
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["12", 0],
                "negative": ["11", 0],
                "latent_image": ["9", 0],
                "seed": seed,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "14": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["2", 0]},
        },
        "15": {
            "class_type": "SaveImage",
            "inputs": {"images": ["14", 0], "filename_prefix": "booklore_"},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ComfyUI：提交 workflow + WebSocket 实时进度
# progress_callback(step, total_steps, phase_start_pct, phase_end_pct)
# ─────────────────────────────────────────────────────────────────────────────


def _run_workflow_with_progress(
    workflow: dict,
    progress_callback: Optional[Callable[[int], None]] = None,
    phase_start: int = 0,
    phase_end: int = 100,
    timeout: int = 600,
) -> bytes:
    """
    提交 ComfyUI workflow，通过 WebSocket 监听进度。
    progress_callback(pct: int)  ← 回调整体百分比（0~100）
    phase_start/phase_end        ← 本次生成在整体进度中的区间，例如 0~50 或 50~100
    """
    client_id = str(uuid.uuid4())

    # 1. 提交 prompt
    resp = requests.post(
        f"{COMFYUI_API_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ComfyUI 提交失败: {resp.text}")
    prompt_id = resp.json()["prompt_id"]
    logger.info(f"[ComfyUI] 任务已提交: {prompt_id}")

    # 通知：已提交（phase起点）
    if progress_callback:
        progress_callback(phase_start)

    # 2. WebSocket 监听进度
    ws_url = COMFYUI_API_URL.replace("http://", "ws://") + f"/ws?clientId={client_id}"
    result_image: Optional[bytes] = None
    completed = False

    def _on_message(ws_app, message):
        nonlocal completed
        try:
            msg = json.loads(message)
            msg_type = msg.get("type")

            if msg_type == "progress":
                # {"type":"progress","data":{"value":15,"max":20,"prompt_id":"..."}}
                data = msg.get("data", {})
                value = data.get("value", 0)
                maxi = data.get("max", 1)
                # 映射到本 phase 的区间
                phase_pct = int((value / maxi) * (phase_end - phase_start))
                total_pct = phase_start + phase_pct
                logger.info(f"[ComfyUI] 进度 {value}/{maxi} → 整体 {total_pct}%")
                if progress_callback:
                    progress_callback(total_pct)

            elif msg_type == "executing":
                data = msg.get("data", {})
                if data.get("node") is None and data.get("prompt_id") == prompt_id:
                    # node=null 表示整个 prompt 执行完毕
                    completed = True
                    ws_app.close()

        except Exception as e:
            logger.warning(f"[ComfyUI WS] 消息解析失败: {e}")

    def _on_error(ws_app, error):
        logger.warning(f"[ComfyUI WS] 连接错误: {error}")

    ws_app = websocket.WebSocketApp(
        ws_url,
        on_message=_on_message,
        on_error=_on_error,
    )
    # 在子线程里跑 WS，主线程等待完成或超时
    import threading

    t = threading.Thread(target=lambda: ws_app.run_forever(), daemon=True)
    t.start()
    t.join(timeout=timeout)

    if not completed:
        ws_app.close()
        logger.warning("[ComfyUI WS] WebSocket 超时，降级为轮询")

    # 3. 从 history 取结果图（WS 完成后 history 一定存在）
    deadline = time.time() + 60
    while time.time() < deadline:
        hist = requests.get(f"{COMFYUI_API_URL}/history/{prompt_id}", timeout=10).json()
        if prompt_id in hist:
            for node_out in hist[prompt_id].get("outputs", {}).values():
                for img_info in node_out.get("images", []):
                    r = requests.get(
                        f"{COMFYUI_API_URL}/view",
                        params={
                            "filename": img_info["filename"],
                            "subfolder": img_info.get("subfolder", ""),
                            "type": img_info.get("type", "output"),
                        },
                        timeout=15,
                    )
                    r.raise_for_status()
                    if progress_callback:
                        progress_callback(phase_end)
                    logger.info(f"[ComfyUI] 图片取回完成: {img_info['filename']}")
                    return r.content
        time.sleep(1)

    raise TimeoutError(f"[ComfyUI] 取结果超时: {prompt_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 画布 + Mask 构建（与 comfyui_flux_outpaint.py 完全一致）
# ─────────────────────────────────────────────────────────────────────────────


def _make_canvas_and_mask(
    bg_img: Image.Image,
    fill_w: int,
    fill_on_left: bool = True,
) -> tuple[bytes, bytes, int, int]:
    """
    bg_img:       已有内容的 PIL Image（封面或封面裁边）
    fill_w:       需要填充的宽度（左侧）
    返回 (canvas_bytes, mask_bytes, total_w, total_h)
    """
    bw, bh = bg_img.size
    total_w = fill_w + bw
    total_h = bh

    canvas = Image.new("RGB", (total_w, total_h), (200, 200, 200))
    mask = Image.new("L", (total_w, total_h), 0)  # 全黑 = 保留
    md = ImageDraw.Draw(mask)

    if fill_on_left:
        canvas.paste(bg_img, (fill_w, 0))
        md.rectangle([(0, 0), (fill_w - 1, total_h - 1)], fill=255)
    else:
        canvas.paste(bg_img, (0, 0))
        md.rectangle([(bw, 0), (total_w - 1, total_h - 1)], fill=255)

    cb = io.BytesIO()
    canvas.save(cb, "PNG")
    mb = io.BytesIO()
    mask.save(mb, "PNG")
    return cb.getvalue(), mb.getvalue(), total_w, total_h


def _resize_to(img_bytes: bytes, w: int, h: int) -> Image.Image:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# 文字合成
# ─────────────────────────────────────────────────────────────────────────────


def _draw_text_shadowed(
    draw, pos, text, font, fill=(255, 255, 255), shadow=(0, 0, 0), offset=2
):
    """文字带多方向阴影，不需要背景框也清晰可读。（照搬本地测试脚本）"""
    x, y = pos
    for dx in (-offset, 0, offset):
        for dy in (-offset, 0, offset):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _make_gradient_overlay(size, start_ratio=0.40):
    """从透明到半透明黑色的垂直渐变。用numpy向量化避免putpixel噪点问题。"""
    import numpy as np

    w, h = size
    start_y = int(h * start_ratio)
    arr = np.zeros((h, w, 4), dtype=np.uint8)  # RGBA全0=透明
    if h > start_y:
        rows = np.arange(h - start_y, dtype=np.float32)
        progress = rows / (h - start_y)
        alpha_col = (185 * (progress**1.4)).astype(np.uint8)  # 缓动曲线
        # 广播到所有列
        arr[start_y:, :, 3] = alpha_col[:, np.newaxis]
    return Image.fromarray(arr, mode="RGBA")


def _composite_back(img: Image.Image, book_info: dict) -> Image.Image:
    """
    封底文字合成（完全照搬本地测试脚本 composite_back）：
    - 渐变遮罩从40%高度开始，缓动曲线，无硬边
    - 书名白色粗体+阴影，作者暖金色，虚线分隔，简介自动折行
    """
    import textwrap

    img = img.convert("RGBA")
    w, h = img.size

    gradient = _make_gradient_overlay((w, h), start_ratio=0.40)
    img = Image.alpha_composite(img, gradient).convert("RGB")
    draw = ImageDraw.Draw(img)

    mx = int(w * 0.08)
    mr = w - int(w * 0.08)
    max_tw = mr - mx
    y = int(h * 0.50)

    # 书名 — 白色粗体 + 黑色阴影
    title = book_info.get("title") or "Unknown Title"
    font_size = int(w * 0.070)
    font = _load_font(font_size, bold=True)
    while font_size > int(w * 0.026):
        if draw.textbbox((0, 0), title, font=font)[2] <= max_tw:
            break
        font_size -= 2
        font = _load_font(font_size, bold=True)
    _draw_text_shadowed(
        draw, (mx, y), title, font, fill=(255, 255, 255), shadow=(0, 0, 0), offset=2
    )
    y += draw.textbbox((0, 0), title, font=font)[3] + int(h * 0.016)

    # 作者 — 暖金色
    authors = book_info.get("authors", [])
    if authors:
        a_str = (
            "by " + ", ".join(authors[:3])
            if all(c.isascii() for c in authors[0])
            else ", ".join(authors[:3])
        )
        font_a = _load_font(int(w * 0.029))
        _draw_text_shadowed(
            draw,
            (mx, y),
            a_str,
            font_a,
            fill=(255, 225, 130),
            shadow=(0, 0, 0),
            offset=1,
        )
        y += draw.textbbox((0, 0), a_str, font=font_a)[3] + int(h * 0.018)

    # 虚线分隔
    dash, gap, lx = 16, 7, mx
    while lx < mr - dash:
        draw.line([(lx, y + 2), (lx + dash, y + 2)], fill=(180, 180, 180), width=1)
        lx += dash + gap
    y += int(h * 0.026)

    # 简介
    desc = (
        book_info.get("description")
        or "A captivating story that will keep you turning pages."
    )
    font_b = _load_font(int(w * 0.025))
    avg_cw = max(1, int(w * 0.025 * 0.55))
    max_char = max(20, max_tw // avg_cw)
    line_h = int(h * 0.033)
    for line in textwrap.fill(desc, width=max_char).split("\n"):
        if y + line_h > int(h * 0.95):
            _draw_text_shadowed(
                draw,
                (mx, y),
                "…",
                font_b,
                fill=(190, 190, 190),
                shadow=(0, 0, 0),
                offset=1,
            )
            break
        _draw_text_shadowed(
            draw,
            (mx, y),
            line,
            font_b,
            fill=(225, 225, 225),
            shadow=(0, 0, 0),
            offset=1,
        )
        y += line_h

    return img


def _composite_spine(spine_img: Image.Image, book_info: dict) -> Image.Image:
    """
    书脊文字合成（V2.0基线）：rotate(-90) → 横向写字 → rotate(+90)
    旋转后：rw=原高(长度方向), rh=原宽(书脊宽度方向)
    主标题在长度方向和宽度方向均居中。
    """
    sw, sh = spine_img.size
    if sw < 5:
        return spine_img

    rotated = spine_img.rotate(-90, expand=True)
    rw, rh = rotated.size  # rw=长度方向, rh=书脊宽度方向

    # 字号以 rh（书脊宽度）为基准
    font_size = max(6, int(rh * 0.70))
    font_t = _load_font(font_size, bold=True)

    # 只取主标题（冒号前）
    full_title = book_info.get("title") or ""
    main_title = full_title.split(":")[0].strip() if ":" in full_title else full_title

    draw = ImageDraw.Draw(rotated)

    # 自动缩小直到适合长度方向（留2%边距）
    max_text_w = int(rw * 0.96)
    while font_size > 6:
        bbox = draw.textbbox((0, 0), main_title, font=font_t)
        if bbox[2] - bbox[0] <= max_text_w:
            break
        font_size -= 1
        font_t = _load_font(font_size, bold=True)

    bbox_t = draw.textbbox((0, 0), main_title, font=font_t)
    tw_main = bbox_t[2] - bbox_t[0]
    th_main = bbox_t[3] - bbox_t[1]

    # 长度方向居中，宽度方向居中
    tx = max(0, (rw - tw_main) // 2)
    ty = max(0, (rh - th_main) // 2)

    # 半透明背景（整体覆盖）
    overlay = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([(0, 0), (rw, rh)], fill=(0, 0, 0, 80))
    rotated = Image.alpha_composite(rotated.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(rotated)

    draw.text((tx, ty), main_title, font=font_t, fill=(255, 255, 255))

    return rotated.rotate(90, expand=True)


def generate_ai_material(
    print_root: str,
    cover_filename: str,
    target: str,  # "spine" | "back"
    book_title: str = "",
    authors: list = None,
    description: str = "",
    categories: list = None,
    trim_size: str = "A5",
    spine_width_mm: float = 4.74,
    count: int = 1,
    quality: str = "medium",
    progress_callback: Optional[Callable[[int], None]] = None,
) -> list[str]:
    """
    生成书脊或封底图片，保存到 print_root/{target}/。
    返回生成的文件名列表（最新在前）。

    progress_callback(pct: int)  ← 整体进度 0~100
    """
    authors = authors or []
    categories = categories or []
    steps = 20  # 书脊和封底都用20步保证质量

    # ── 1. 加载封面 ──────────────────────────────────────────────────────────
    cover_path = Path(print_root) / "cover" / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"封面图不存在: {cover_path}")

    front_orig = Image.open(cover_path).convert("RGB")

    # ── 2. 尺寸计算 ──────────────────────────────────────────────────────────
    page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])

    # 缩放封面到标准高度（与 comfyui_flux_outpaint.py 一致）
    scale = page_h / front_orig.height
    cw = int(front_orig.width * scale)
    cover = front_orig.resize((cw, page_h), Image.LANCZOS)

    spine_px = max(1, round(spine_width_mm * 400 / 25.4))
    author_str = ", ".join(authors)

    logger.info(
        f"[AI] target={target} trim={trim_size} cover={cw}x{page_h} spine_px={spine_px}"
    )

    # ── 3. Janus 风格分析（修正版调用）──────────────────────────────────────
    if progress_callback:
        progress_callback(3)

    style_desc = _analyze_style(
        front_img=cover,
        target=target,
        book_title=book_title,
        authors=authors,
        description=description,
        categories=categories,
    )

    # 构建 prompt（与本地测试脚本 build_outpaint_prompt 完全一致）
    genre = ", ".join((categories or [])[:2])
    style = style_desc or (
        "seamless extension of book cover art, "
        "same color palette and illustration style, "
        "atmospheric background, professional book design"
    )

    if target == "spine":
        prompt = (
            f"{style}. "
            f"Seamlessly extend the book cover edge to the left as a narrow spine strip. "
            f"{(genre + ' style, ') if genre else ''}"
            f"Exact same background color, texture and pattern as the cover left edge. "
            f"Simple vertical continuation, no new elements, seamless transition."
        )
    else:
        style_tags = _parse_janus_to_tags(style)
        prompt = (
            f"{style_tags}, "
            f"seamless book cover background extension, "
            f"open sky and landscape, no characters, no text, no logos, "
            f"lower half plain and open for text, "
            f"same art style and color temperature as reference image"
        )

    if progress_callback:
        progress_callback(10)

    # ── 4. 画布构建 ──────────────────────────────────────────────────────────
    if target == "back":
        # 封底 outpainting 策略（crop）：
        # 封面原尺寸放右侧，左侧为生成区（page_w宽）
        # FLUX 能看到封面完整内容，生成区和封面直接相邻，过渡自然
        ref_w = min(cw, page_w)
        ref_img = cover.crop((0, 0, ref_w, page_h))
        canvas_b, mask_b, total_w, total_h = _make_canvas_and_mask(
            ref_img, page_w, fill_on_left=True
        )
        # mask 右边缘羽化，消除生成区和参考图交界的噪点条
        import numpy as np

        mask_img = Image.open(io.BytesIO(mask_b)).convert("L")
        mask_arr = np.array(mask_img, dtype=np.float32)
        feather = 12
        for dx in range(feather):
            x = page_w - 1 - dx
            if 0 <= x < mask_arr.shape[1]:
                mask_arr[:, x] *= dx / feather
        mask_out = io.BytesIO()
        Image.fromarray(mask_arr.astype(np.uint8)).save(mask_out, "PNG")
        mask_b = mask_out.getvalue()
        phase_start, phase_end = 10, 90
        logger.info(f"[AI] 封底画布: {total_w}x{total_h}，crop策略，参考宽={ref_w}")

    else:  # spine
        # 书脊放大生成策略（与本地测试脚本一致）：
        # 真实书脊可能只有75px，FLUX处理<100px效果极差
        # 强制放大到至少150px给FLUX生成，生成后再LANCZOS缩回真实尺寸
        SPINE_GEN_MIN = 150
        spine_px_gen = max(SPINE_GEN_MIN, spine_px)
        edge_w = min(cw, spine_px_gen * 4)  # 封面左边缘参考宽度=生成书脊的4倍
        edge_img = cover.crop((0, 0, edge_w, page_h))
        canvas_b, mask_b, total_w, total_h = _make_canvas_and_mask(
            edge_img, spine_px_gen, fill_on_left=True
        )
        phase_start, phase_end = 10, 90
        logger.info(
            f"[AI] 书脊画布: {total_w}x{total_h}，生成宽={spine_px_gen}，真实宽={spine_px}"
        )

    # ── 5. 上传画布和 Mask 到 ComfyUI ────────────────────────────────────────
    if progress_callback:
        progress_callback(12)

    seed = int(time.time() * 1000) % (2**32)
    prefix = str(uuid.uuid4())[:8]
    canvas_fn = _upload_image(canvas_b, f"{prefix}_canvas.png")
    mask_fn = _upload_image(mask_b, f"{prefix}_mask.png")

    if progress_callback:
        progress_callback(15)

    # ── 6. 构建工作流并提交 ComfyUI（WebSocket 进度） ────────────────────────
    workflow = _build_flux_workflow(
        canvas_fn=canvas_fn,
        mask_fn=mask_fn,
        prompt=prompt,
        seed=seed,
        steps=steps,
        guidance=2.5,  # steps=8时低guidance更稳定
    )

    result_bytes = _run_workflow_with_progress(
        workflow=workflow,
        progress_callback=progress_callback,
        phase_start=phase_start,
        phase_end=phase_end,
        timeout=600,
    )

    # ── 7. 裁切 + 缩回真实尺寸 + 文字合成 ──────────────────────────────────
    if progress_callback:
        progress_callback(92)

    result_img = _resize_to(result_bytes, total_w, total_h)

    if target == "back":
        generated = result_img.crop((0, 0, page_w, page_h))
        book_info = {
            "title": book_title,
            "authors": authors,
            "description": description,
        }
        generated = _composite_back(generated, book_info)
    else:
        # 原版逻辑：先缩回真实尺寸，再在真实尺寸上合成文字
        raw_spine = result_img.crop((0, 0, spine_px_gen, page_h))
        spine_real = raw_spine.resize((spine_px, page_h), Image.LANCZOS)
        book_info_spine = {"title": book_title, "authors": authors}
        generated = _composite_spine(spine_real, book_info_spine)

    # ── 8. 保存文件 ────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(96)

    target_dir = Path(print_root) / target
    target_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ai_{target}_{timestamp}.png"

    out_buf = io.BytesIO()
    generated.save(out_buf, format="PNG", dpi=(400, 400))
    (target_dir / filename).write_bytes(out_buf.getvalue())

    logger.info(f"[AI] 生成完成: {filename}")

    if progress_callback:
        progress_callback(100)

    return [filename]

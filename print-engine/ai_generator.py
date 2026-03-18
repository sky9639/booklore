#!/usr/bin/env python3
"""
ai_generator.py  —  Booklore Print Engine
版本：V4.0 (Claude API + SDXL + IP-Adapter)

更新内容（V4.0）：
1. ✅ 替换 Janus API 为 Claude Sonnet 4.6 进行封面风格分析
2. ✅ 使用 SDXL + IP-Adapter 生成逻辑（封面作为参考图）
3. ✅ 添加缓存机制减少 Claude API 调用成本
4. ✅ Token 优化：图片缩放到 800px，精简 Prompt
5. ✅ 实时进度条：中文阶段描述 + Token 消耗统计

配置从 booklore.env 读取：
    COMFYUI_API_URL=http://ROG:8188
    CLAUDE_API_KEY=sk-xxx
    CLAUDE_API_URL=http://newapi.200m.997555.xyz
    CLAUDE_MODEL=claude-sonnet-4-6
    CACHE_ENABLED=True
    CACHE_DIR=./cache
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

# Claude API 配置
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_API_URL = os.getenv("CLAUDE_API_URL", "https://api.anthropic.com")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# 缓存配置
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "True").lower() == "true"
CACHE_DIR = os.getenv("CACHE_DIR", "./cache")

# 生成模型配置
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "SDXL")  # 可配置：SDXL, FLUX, SD3等
GENERATION_STRATEGY = os.getenv("GENERATION_STRATEGY", "crop")  # 可配置：crop, outpaint等

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 初始化 Claude 分析器
from claude_analyzer import ClaudeAnalyzer

_claude_analyzer = None
if CLAUDE_API_KEY:
    _claude_analyzer = ClaudeAnalyzer(
        api_key=CLAUDE_API_KEY,
        api_url=CLAUDE_API_URL,
        model=CLAUDE_MODEL,
        cache_dir=None,  # 禁用缓存，每次重新分析
        cache_ttl=3600,
    )
    logger.info(f"[Claude] 分析器已初始化: {CLAUDE_MODEL}")
else:
    logger.warning("[Claude] API Key 未配置，将使用默认 Prompt")


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
# Claude 风格分析（V4.0 新增）
# 使用 Claude Sonnet 4.6 替代 Janus
# ─────────────────────────────────────────────────────────────────────────────


def _analyze_style_with_claude(
    front_img: Image.Image,
    target: str,
    book_title: str,
    authors: list,
    description: str,
    categories: list,
    request_id: str = "",
) -> dict:
    """
    使用 Claude API 分析封面风格

    返回:
        {
            "style_prompt": str,
            "negative_prompt": str,
            "analysis": str,
            "token_usage": dict
        }
    """
    if not _claude_analyzer:
        logger.warning(f"[{request_id}] Claude 未配置，使用默认 Prompt")
        return {
            "style_prompt": "seamless extension, natural continuation, open space for text, decorative elements",
            "negative_prompt": "blurry, low quality, distorted, text, watermark, signature, ugly, deformed, noisy, artifacts, jpeg artifacts, oversaturated, undersaturated",
            "analysis": "Claude API not configured",
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        }

    try:
        # 转换图片为字节
        buf = io.BytesIO()
        front_img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        # 构建书籍信息
        book_info = {
            "title": book_title,
            "authors": authors,
            "description": description,
            "categories": categories,
            "target": target,  # 添加 target 参数
        }

        # 调用 Claude 分析
        result = _claude_analyzer.analyze_cover(image_bytes, book_info, request_id, target=target)

        logger.info(f"[{request_id}] Claude 分析完成: {result.get('analysis', '')[:80]}...")

        return result

    except Exception as e:
        logger.error(f"[{request_id}] Claude 分析失败: {e}", exc_info=True)
        return {
            "style_prompt": "seamless extension, natural continuation, open space for text, decorative elements",
            "negative_prompt": "blurry, low quality, distorted, text, watermark, signature, ugly, deformed, noisy, artifacts, jpeg artifacts, oversaturated, undersaturated",
            "analysis": f"Analysis failed: {e}",
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        }


def _parse_janus_to_tags(style: str) -> str:
    """
    清洗风格描述，提取关键标签
    （保留此函数以兼容旧代码，但 Claude 返回的已经是清洗后的标签）
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


def _build_sdxl_ipadapter_workflow(
    canvas_fn: str,
    mask_fn: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int = 30,
    reference_image_fn: str = None,
    ipadapter_weight: float = 1.05,
) -> dict:
    """
    构建 SDXL + IP-Adapter 工作流（完全复用本地测试逻辑）

    Args:
        canvas_fn: 画布图片文件名
        mask_fn: 遮罩图片文件名
        prompt: 生成 Prompt
        negative_prompt: 负面 Prompt
        seed: 随机种子
        steps: 生成步数（优化：30）
        reference_image_fn: 参考图片文件名（封面原图，用于 IP-Adapter）
        ipadapter_weight: IP-Adapter 权重（优化：1.05）
    """
    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "sd_xl_base_1.0.safetensors",
            },
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "sdxl_vae.safetensors"}},
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
                "grow_mask_by": 8,  # SDXL 需要扩展边缘（优化：6→8，更平滑过渡）
            },
        },
        "10": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "11": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative_prompt},  # 使用 Claude 返回的 negative_prompt
        },
    }

    # 如果提供了参考图，使用 IP-Adapter（关键！）
    if reference_image_fn:
        workflow["16"] = {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image_fn}
        }
        workflow["17"] = {
            "class_type": "AV_IPAdapter",
            "inputs": {
                "ip_adapter_name": "sdxl_models\\ip-adapter-plus_sdxl_vit-h.safetensors",
                "clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
                "model": ["1", 0],
                "image": ["16", 0],
                "weight": ipadapter_weight,  # 优化：1.05（略微增强风格一致性）
                "weight_type": "style transfer",
                "start_at": 0.0,
                "end_at": 1.0,
                "enabled": True,
            }
        }
        model_source = ["17", 0]
    else:
        model_source = ["1", 0]

    workflow["13"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_source,
            "positive": ["10", 0],
            "negative": ["11", 0],
            "latent_image": ["9", 0],
            "seed": seed,
            "steps": steps,  # 优化：30步（极致质量）
            "cfg": 7.5,  # 优化：7.0→7.5（提升prompt遵循度）
            "sampler_name": "dpmpp_2m_sde",  # 优化：dpmpp_2m→dpmpp_2m_sde（高质量采样器）
            "scheduler": "karras",
            "denoise": 1.0,
        },
    }
    workflow["14"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["13", 0], "vae": ["2", 0]},
    }
    workflow["15"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["14", 0], "filename_prefix": "booklore_"},
    }

    return workflow


# ─────────────────────────────────────────────────────────────────────────────
# ComfyUI：提交 workflow + 轮询结果（SDXL 版本，简化版）
# ─────────────────────────────────────────────────────────────────────────────


def _run_workflow_simple(workflow: dict, timeout: int = 600) -> bytes:
    """
    提交 ComfyUI workflow，轮询获取结果（SDXL 用这个就够了）

    Args:
        workflow: ComfyUI 工作流
        timeout: 超时时间（秒）

    Returns:
        生成的图片字节
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

    # 2. 轮询 history 获取结果
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
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
                    logger.info(f"[ComfyUI] 图片取回完成: {img_info['filename']}")
                    return r.content

    raise TimeoutError(f"[ComfyUI] 取结果超时: {prompt_id}")


# ─────────────────────────────────────────────────────────────────────────────
# ComfyUI：提交 workflow + WebSocket 实时进度（FLUX 版本，保留但不用）
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
# 文字风格解析工具
# ─────────────────────────────────────────────────────────────────────────────


def _parse_color(color_desc: str) -> tuple:
    """
    解析Claude返回的颜色描述为RGB值

    Args:
        color_desc: 颜色描述（如"white", "golden yellow", "light blue"）

    Returns:
        RGB元组 (r, g, b)
    """
    if not color_desc or color_desc == "null":
        return None

    # 颜色映射表
    COLOR_MAP = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "golden": (255, 215, 0),
        "golden yellow": (255, 225, 130),
        "warm gold": (255, 200, 80),
        "gold": (255, 215, 0),
        "red": (220, 50, 50),
        "bright red": (255, 50, 50),
        "dark red": (180, 30, 30),
        "blue": (50, 120, 220),
        "light blue": (150, 200, 255),
        "dark blue": (30, 60, 120),
        "sky blue": (135, 206, 235),
        "green": (50, 180, 80),
        "light green": (150, 220, 150),
        "dark green": (30, 100, 50),
        "pink": (255, 150, 180),
        "light pink": (255, 200, 220),
        "hot pink": (255, 105, 180),
        "purple": (180, 100, 220),
        "light purple": (200, 150, 255),
        "dark purple": (100, 50, 150),
        "orange": (255, 150, 50),
        "bright orange": (255, 165, 0),
        "yellow": (255, 230, 80),
        "bright yellow": (255, 255, 0),
        "brown": (150, 100, 60),
        "dark brown": (100, 60, 30),
        "gray": (150, 150, 150),
        "grey": (150, 150, 150),
        "light gray": (200, 200, 200),
        "dark gray": (80, 80, 80),
        "silver": (192, 192, 192),
        "cream": (255, 253, 208),
        "beige": (245, 245, 220),
        "turquoise": (64, 224, 208),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "lime": (0, 255, 0),
        "navy": (0, 0, 128),
        "teal": (0, 128, 128),
        "olive": (128, 128, 0),
        "maroon": (128, 0, 0),
    }

    color_lower = color_desc.lower().strip()

    # 精确匹配
    if color_lower in COLOR_MAP:
        return COLOR_MAP[color_lower]

    # 模糊匹配（包含关键词，优先匹配长的）
    matches = []
    for key, rgb in COLOR_MAP.items():
        if key in color_lower:
            matches.append((len(key), rgb))

    if matches:
        # 返回最长匹配
        matches.sort(reverse=True)
        return matches[0][1]

    # 默认白色
    return (255, 255, 255)


def _parse_text_style(text_style: dict) -> dict:
    """
    解析Claude返回的文字风格为可用的参数

    Args:
        text_style: Claude返回的text_style字典

    Returns:
        {
            "title_color": (r, g, b),
            "title_bold": bool,
            "title_has_shadow": bool,
            "title_has_outline": bool,
            "author_color": (r, g, b),
            "author_bold": bool,
            "description_color": (r, g, b),
        }
    """
    if not text_style:
        # 默认值
        return {
            "title_color": (255, 255, 255),
            "title_bold": True,
            "title_has_shadow": True,
            "title_has_outline": False,
            "author_color": (255, 225, 130),
            "author_bold": False,
            "description_color": (225, 225, 225),
        }

    # 解析标题颜色
    title_color = _parse_color(text_style.get("title_color"))
    if not title_color:
        title_color = (255, 255, 255)  # 默认白色

    # 解析标题风格
    title_style_desc = (text_style.get("title_style") or "").lower()
    title_bold = "bold" in title_style_desc or "thick" in title_style_desc

    # 解析标题效果
    title_effects = (text_style.get("title_effects") or "").lower()
    title_has_shadow = "shadow" in title_effects
    title_has_outline = "outline" in title_effects

    # 解析作者颜色
    author_color = _parse_color(text_style.get("author_color"))
    if not author_color:
        # 如果没有作者颜色，使用标题颜色的变体（稍微暗一点或金色）
        if title_color == (255, 255, 255):
            author_color = (255, 225, 130)  # 金色
        else:
            # 使用标题颜色的80%亮度
            author_color = tuple(int(c * 0.8) for c in title_color)

    # 解析作者风格
    author_style_desc = (text_style.get("author_style") or "").lower()
    author_bold = "bold" in author_style_desc

    # 解析简介颜色
    description_color = _parse_color(text_style.get("description_color"))
    if not description_color:
        # 默认浅灰色
        description_color = (225, 225, 225)

    return {
        "title_color": title_color,
        "title_bold": title_bold,
        "title_has_shadow": title_has_shadow,
        "title_has_outline": title_has_outline,
        "author_color": author_color,
        "author_bold": author_bold,
        "description_color": description_color,
    }


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


def _composite_back(img: Image.Image, book_info: dict, text_style: dict = None) -> Image.Image:
    """
    封底文字合成，应用从封面识别的字体风格
    - 渐变遮罩从40%高度开始，缓动曲线，无硬边
    - 书名、作者、简介应用识别的颜色和风格
    - 如果没有text_style，使用默认值

    Args:
        img: 封底图片
        book_info: 书籍信息 {"title": str, "authors": list, "description": str}
        text_style: Claude识别的文字风格（可选）
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

    # 解析文字风格
    style = _parse_text_style(text_style)

    # 书名 — 应用识别的颜色和风格
    title = book_info.get("title") or "Unknown Title"
    font_size = int(w * 0.070)
    font = _load_font(font_size, bold=style["title_bold"])
    while font_size > int(w * 0.026):
        if draw.textbbox((0, 0), title, font=font)[2] <= max_tw:
            break
        font_size -= 2
        font = _load_font(font_size, bold=style["title_bold"])

    # 应用识别的颜色和阴影
    if style["title_has_shadow"]:
        _draw_text_shadowed(
            draw, (mx, y), title, font,
            fill=style["title_color"],
            shadow=(0, 0, 0),
            offset=2
        )
    else:
        draw.text((mx, y), title, font=font, fill=style["title_color"])

    y += draw.textbbox((0, 0), title, font=font)[3] + int(h * 0.016)

    # 作者 — 应用识别的颜色
    authors = book_info.get("authors", [])
    if authors:
        a_str = (
            "by " + ", ".join(authors[:3])
            if all(c.isascii() for c in authors[0])
            else ", ".join(authors[:3])
        )
        font_a = _load_font(int(w * 0.029), bold=style["author_bold"])
        _draw_text_shadowed(
            draw,
            (mx, y),
            a_str,
            font_a,
            fill=style["author_color"],
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

    # 简介 — 应用识别的颜色
    desc = (
        book_info.get("description")
        or "A captivating story that will keep you turning pages."
    )

    # 清理HTML标签
    import re
    desc = re.sub(r'<[^>]+>', '', desc)  # 删除所有HTML标签
    desc = desc.replace('&nbsp;', ' ')  # 替换HTML空格
    desc = desc.replace('&lt;', '<')
    desc = desc.replace('&gt;', '>')
    desc = desc.replace('&amp;', '&')
    desc = desc.replace('&quot;', '"')
    desc = desc.strip()  # 去除首尾空格

    if not desc:
        desc = "A captivating story that will keep you turning pages."

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
                fill=style["description_color"],
                shadow=(0, 0, 0),
                offset=1,
            )
            break
        _draw_text_shadowed(
            draw,
            (mx, y),
            line,
            font_b,
            fill=style["description_color"],
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
    progress_callback: Optional[Callable[[int, str], None]] = None,  # 修改：添加阶段说明参数
) -> tuple[list[str], dict]:
    """
    生成书脊或封底图片，保存到 print_root/{target}/。
    返回 (文件名列表, token_usage字典)。

    progress_callback(pct: int, stage: str)  ← 整体进度 0~100 + 中文阶段说明
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

    # ── 0. 打印输入信息 ──────────────────────────────────────────────────────────
    target_name = "书脊" if target == "spine" else "封底"

    if progress_callback:
        progress_callback(0, f"========== 开始生成{target_name} ==========")
        progress_callback(1, f"【输入信息】")
        progress_callback(1, f"  ├─ 书名: {book_title or '未提供'}")
        progress_callback(1, f"  ├─ 作者: {author_str or '未提供'}")
        progress_callback(1, f"  ├─ 分类: {', '.join(categories) or '未提供'}")
        progress_callback(1, f"  ├─ 封面路径: {cover_filename}")
        progress_callback(1, f"  ├─ 封面尺寸: {front_orig.size[0]}x{front_orig.size[1]}px")
        progress_callback(2, f"  ├─ 成书尺寸: {trim_size} ({page_w}x{page_h}px)")
        if target == "spine":
            progress_callback(2, f"  └─ 书脊宽度: {spine_width_mm}mm ({spine_px}px)")
        else:
            progress_callback(2, f"  └─ 简介: {(description[:50] + '...') if description and len(description) > 50 else (description or '未提供')}")


    # ── 3. Claude 风格分析（V4.0 更新）──────────────────────────────────────

    if progress_callback:
        progress_callback(3, f"【第一步】正在分析封面风格（生成{target_name}）...")
        progress_callback(4, f"  ├─ 封面预处理: 缩放到{cover.size[0]}x{cover.size[1]}px")
        progress_callback(5, f"  └─ 正在调用Claude API分析...")

    # 生成请求 ID 用于日志追踪
    request_id = f"AI-{int(time.time() * 1000) % 1000000}"

    # 调用 Claude 分析封面
    analysis = _analyze_style_with_claude(
        front_img=cover,
        target=target,
        book_title=book_title,
        authors=authors,
        description=description,
        categories=categories,
        request_id=request_id,
    )

    # 提取分析结果
    style_analysis = analysis.get("analysis", "")
    style_prompt = analysis.get("style_prompt", "")
    negative_prompt = analysis.get("negative_prompt", "blurry, low quality, distorted, text, watermark, signature, ugly, deformed, noisy, artifacts, jpeg artifacts, oversaturated, undersaturated")
    text_style = analysis.get("text_style", None)  # 提取文字风格
    token_usage = analysis.get("token_usage", {})

    # 固定使用优化后的参数
    ipadapter_weight = 1.05  # 优化值
    steps = 30  # 优化值

    if progress_callback:
        progress_callback(8, f"Claude分析完成: {style_analysis[:60]}...")
        progress_callback(9, f"Token消耗: 输入{token_usage.get('input_tokens', 0)} + 输出{token_usage.get('output_tokens', 0)} = {token_usage.get('total_tokens', 0)}")

    # 记录识别的文字风格
    if text_style and target == "back":
        logger.info(f"[{request_id}] 识别的文字风格:")
        logger.info(f"[{request_id}]   标题颜色: {text_style.get('title_color', 'null')}")
        logger.info(f"[{request_id}]   标题风格: {text_style.get('title_style', 'null')}")
        logger.info(f"[{request_id}]   作者颜色: {text_style.get('author_color', 'null')}")
        logger.info(f"[{request_id}]   简介颜色: {text_style.get('description_color', 'null')}")

    # 使用 Claude 生成的 style_prompt（已经包含具体图案描述）
    prompt = style_prompt
    if not prompt:
        # 降级处理
        prompt = "seamless extension, natural continuation, open space for text, decorative elements"

    if progress_callback:
        progress_callback(10, f"识别的图案: {prompt[:60]}...")

    if progress_callback:
        progress_callback(11, f"完整Prompt: {prompt[:80]}...")
        progress_callback(12, f"IP-Adapter权重: {ipadapter_weight}, 生成步数: {steps}")

    logger.info(f"[{request_id}] 使用 Prompt: {prompt[:100]}...")
    logger.info(f"[{request_id}] IP-Adapter 权重: {ipadapter_weight}, 步数: {steps}")

    if progress_callback:
        prompt_preview = prompt[:50]
        progress_callback(14, f"【第二步】风格分析完成，准备生成{target_name}...")
        progress_callback(15, f"  ├─ 识别图案: {prompt_preview}...")
        progress_callback(16, f"  ├─ IP-Adapter权重: {ipadapter_weight}")
        progress_callback(17, f"  └─ 生成步数: {steps}")

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
        if progress_callback:
            progress_callback(18, f"【第三步】构建封底画布: {total_w}x{total_h}px ({GENERATION_STRATEGY}策略)")
            progress_callback(19, f"  ├─ 参考区域宽度: {ref_w}px")
            progress_callback(20, f"  └─ 生成区域宽度: {page_w}px")

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
        if progress_callback:
            progress_callback(18, f"【第三步】构建书脊画布: {total_w}x{total_h}px")
            progress_callback(19, f"  ├─ 生成宽度: {spine_px_gen}px (放大策略)")
            progress_callback(20, f"  └─ 真实宽度: {spine_px}px (最终缩放)")

    # ── 5. 上传画布、Mask 和封面参考图到 ComfyUI ────────────────────────────
    if progress_callback:
        progress_callback(22, f"【第四步】正在上传素材到ComfyUI...")

    seed = int(time.time() * 1000) % (2**32)
    prefix = str(uuid.uuid4())[:8]
    canvas_fn = _upload_image(canvas_b, f"{prefix}_canvas.png")
    mask_fn = _upload_image(mask_b, f"{prefix}_mask.png")

    # 上传封面作为参考图（关键！用于 IP-Adapter）
    cover_ref_buf = io.BytesIO()
    cover.save(cover_ref_buf, "PNG")
    cover_ref_fn = _upload_image(cover_ref_buf.getvalue(), f"{prefix}_reference.png")

    if progress_callback:
        progress_callback(25, f"【第五步】提交{GENERATION_MODEL}生成任务...")
        progress_callback(26, f"  ├─ 模型: {GENERATION_MODEL} + IP-Adapter")
        progress_callback(27, f"  ├─ 随机种子: {seed}")
        progress_callback(28, f"  └─ 开始生成{target_name}图片...")

    # ── 6. 构建工作流并提交 ComfyUI（SDXL + IP-Adapter） ────────────────────────
    workflow = _build_sdxl_ipadapter_workflow(
        canvas_fn=canvas_fn,
        mask_fn=mask_fn,
        prompt=prompt,
        negative_prompt=negative_prompt,  # 添加 negative_prompt
        seed=seed,
        steps=steps,
        reference_image_fn=cover_ref_fn,  # 传入封面参考图
        ipadapter_weight=ipadapter_weight,  # 使用优化的权重 1.05
    )

    if progress_callback:
        progress_callback(30, f"【生成中】{GENERATION_MODEL}正在绘制{target_name}，请稍候（约15-30秒）...")

    result_bytes = _run_workflow_simple(workflow, timeout=600)

    if progress_callback:
        progress_callback(85, f"【第六步】{target_name}生成完成，正在后处理...")
        progress_callback(86, f"  ├─ 裁切到目标尺寸")
        progress_callback(87, f"  └─ 准备合成文字...")

    # ── 7. 裁切 + 缩回真实尺寸 + 文字合成 ──────────────────────────────────
    if progress_callback:
        progress_callback(92, f"【第七步】正在添加书名和简介文字...")

    result_img = _resize_to(result_bytes, total_w, total_h)

    if target == "back":
        generated = result_img.crop((0, 0, page_w, page_h))
        book_info = {
            "title": book_title,
            "authors": authors,
            "description": description,
        }
        generated = _composite_back(generated, book_info, text_style)  # 传递text_style
    else:
        # 原版逻辑：先缩回真实尺寸，再在真实尺寸上合成文字
        raw_spine = result_img.crop((0, 0, spine_px_gen, page_h))
        spine_real = raw_spine.resize((spine_px, page_h), Image.LANCZOS)
        book_info_spine = {"title": book_title, "authors": authors}
        generated = _composite_spine(spine_real, book_info_spine)

    # ── 8. 保存文件 ────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(96, "正在保存文件...")

    target_dir = Path(print_root) / target
    target_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ai_{target}_{timestamp}.png"

    out_buf = io.BytesIO()
    generated.save(out_buf, format="PNG", dpi=(400, 400))
    (target_dir / filename).write_bytes(out_buf.getvalue())

    logger.info(f"[AI] 生成完成: {filename}")

    # 输出 Token 统计信息
    if token_usage:
        total = token_usage.get("total_tokens", 0)
        input_t = token_usage.get("input_tokens", 0)
        output_t = token_usage.get("output_tokens", 0)
        logger.info(
            f"[{request_id}] 本次 Claude API 消耗: {total} tokens "
            f"(输入: {input_t}, 输出: {output_t})"
        )

    if progress_callback:
        # 最后返回 Token 信息
        token_msg = ""
        if token_usage:
            total = token_usage.get("total_tokens", 0)
            token_msg = f" (消耗 {total} tokens)"
        progress_callback(100, f"生成完成{token_msg}")

    # 返回文件名和 Token 信息
    return [filename], token_usage

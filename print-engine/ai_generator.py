#!/usr/bin/env python3
"""
ai_generator.py — Booklore Print Engine
版本：V5.0 (Gemini 中转 API)

说明：
1. 删除旧的 Claude / ComfyUI / SDXL / FLUX 生成链路
2. 保留 print-engine 现有的调用入口与进度回调接口
3. 新增 Gemini 展开图生成、初始裁切线推断、裁切保存能力
"""

import base64
import io
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv("booklore.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TRIM_SIZE_PX = {
    "A4": (1654, 2339),
    "A5": (1240, 1748),
    "B5": (1390, 1969),
}

BOOKLORE_ENV_PATH = Path("booklore.env")
AI_PROFILES_CONFIG_PATH = Path(os.getenv("AI_PROFILES_CONFIG_PATH", "./ai_profiles.json"))
PROMPT_CONFIG_PATH = Path(os.getenv("AI_PROMPT_CONFIG_PATH", "./ai_prompts.json"))
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://api.302.ai").rstrip("/")
GEMINI_API_PATH = os.getenv("GEMINI_API_PATH", "/google/v1/models/{model}")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "240"))
GEMINI_IMAGE_MAX_SEND = int(os.getenv("GEMINI_IMAGE_MAX_SEND", "2048"))


def reload_runtime_config() -> None:
    """重新加载运行时配置，供保存配置后立即生效。"""
    global AI_PROFILES_CONFIG_PATH, PROMPT_CONFIG_PATH, GEMINI_API_URL, GEMINI_API_PATH, GEMINI_API_KEY, GEMINI_IMAGE_MODEL, GEMINI_TIMEOUT, GEMINI_IMAGE_MAX_SEND
    load_dotenv("booklore.env", override=True)
    AI_PROFILES_CONFIG_PATH = Path(os.getenv("AI_PROFILES_CONFIG_PATH", "./ai_profiles.json"))
    PROMPT_CONFIG_PATH = Path(os.getenv("AI_PROMPT_CONFIG_PATH", "./ai_prompts.json"))
    GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://api.302.ai").rstrip("/")
    GEMINI_API_PATH = os.getenv("GEMINI_API_PATH", "/google/v1/models/{model}")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "240"))
    GEMINI_IMAGE_MAX_SEND = int(os.getenv("GEMINI_IMAGE_MAX_SEND", "2048"))


def load_profiles_config() -> dict:
    """
    读取联通参数多组配置。

    优先读取 ai_profiles.json；如果文件不存在，则从当前 .env 构造一个默认配置，
    这样可以兼容旧版本，仅升级配置结构，不影响已有运行时。
    """
    reload_runtime_config()

    if AI_PROFILES_CONFIG_PATH.exists():
        with AI_PROFILES_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        profiles = data.get("profiles") or []
        active_id = data.get("activeProfileId") or ""
        if profiles:
            if not any(str(p.get("id", "")).strip() == active_id for p in profiles):
                active_id = str(profiles[0].get("id", "profile_default"))
            data["activeProfileId"] = active_id
            return data

    # 向后兼容：从 .env 构造默认配置
    return {
        "activeProfileId": "profile_default",
        "profiles": [
            {
                "id": "profile_default",
                "name": "默认配置",
                "baseUrl": GEMINI_API_URL,
                "apiPath": GEMINI_API_PATH,
                "apiKey": GEMINI_API_KEY,
                "model": GEMINI_IMAGE_MODEL,
                "timeout": GEMINI_TIMEOUT,
                "imageMaxSend": 2048,
            }
        ],
    }


def save_profiles_config(config: dict) -> dict:
    """保存联通参数多组配置到独立 JSON 文件。"""
    profiles = config.get("profiles") or []
    active_id = str(config.get("activeProfileId", "")).strip()

    if not profiles:
        raise ValueError("联通参数配置不能为空")

    normalized_profiles = []
    for index, profile in enumerate(profiles):
        profile_id = str(profile.get("id", "")).strip() or f"profile_{index + 1}"
        normalized_profiles.append({
            "id": profile_id,
            "name": str(profile.get("name", "")).strip() or f"方案 {index + 1}",
            "baseUrl": str(profile.get("baseUrl", "")).strip(),
            "apiPath": str(profile.get("apiPath", "/google/v1/models/{model}")).strip(),
            "apiKey": str(profile.get("apiKey", "")).strip(),
            "model": str(profile.get("model", "")).strip(),
            "timeout": int(profile.get("timeout", 240)),
            "imageMaxSend": int(profile.get("imageMaxSend", 2048)),
        })

    if not any(item["id"] == active_id for item in normalized_profiles):
        active_id = normalized_profiles[0]["id"]

    data = {
        "activeProfileId": active_id,
        "profiles": normalized_profiles,
    }
    AI_PROFILES_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def _read_env_lines() -> list[str]:
    if not BOOKLORE_ENV_PATH.exists():
        return []
    return BOOKLORE_ENV_PATH.read_text(encoding="utf-8").splitlines()


def _write_env_map(env_map: dict[str, str]) -> None:
    lines = []
    for key, value in env_map.items():
        lines.append(f"{key}={value}")
    BOOKLORE_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reload_runtime_config()


def get_ai_runtime_config(mask_secret: bool = True) -> dict:
    """
    获取 AI 运行时配置（联通参数多组 profiles 模型）。

    说明：
    - 多组 profiles 从 ai_profiles.json 读取
    - 当前激活 profile 会同步写入 .env，供实际运行时使用
    - 这里返回完整 profiles 列表给前端管理
    """
    data = load_profiles_config()

    # 目前按用户要求返回明文；mask_secret 参数保留以减少调用方改动
    del mask_secret
    return data


def save_ai_runtime_config(config: dict) -> dict:
    """
    保存 AI 运行时配置（联通参数多组 profiles 模型）。

    处理分两步：
    1. 将完整 profiles 列表写入 ai_profiles.json，保证前端下次打开时能完整恢复
    2. 将当前激活 profile 同步写入 .env，保证生成流程始终读取当前生效配置
    """
    runtime_config = save_profiles_config(config)
    active_id = runtime_config.get("activeProfileId", "")
    profiles = runtime_config.get("profiles", [])

    active_profile = None
    for profile in profiles:
        if profile.get("id") == active_id:
            active_profile = profile
            break
    if not active_profile and profiles:
        active_profile = profiles[0]
    if not active_profile:
        raise ValueError("未找到有效的联通参数配置")

    env_map = {
        "PRINT_ENGINE_PORT": os.getenv("PRINT_ENGINE_PORT", "5800"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "GEMINI_API_URL": str(active_profile.get("baseUrl", GEMINI_API_URL)).strip(),
        "GEMINI_API_PATH": str(active_profile.get("apiPath", GEMINI_API_PATH)).strip(),
        "GEMINI_API_KEY": str(active_profile.get("apiKey", GEMINI_API_KEY)).strip(),
        "GEMINI_IMAGE_MODEL": str(active_profile.get("model", GEMINI_IMAGE_MODEL)).strip(),
        "GEMINI_TIMEOUT": str(active_profile.get("timeout", GEMINI_TIMEOUT)).strip(),
        "GEMINI_IMAGE_MAX_SEND": str(active_profile.get("imageMaxSend", GEMINI_IMAGE_MAX_SEND)).strip(),
        "AI_PROFILES_CONFIG_PATH": str(AI_PROFILES_CONFIG_PATH),
        "AI_PROMPT_CONFIG_PATH": str(config.get("promptConfigPath", PROMPT_CONFIG_PATH)).strip(),
    }
    _write_env_map(env_map)
    return get_ai_runtime_config(mask_secret=False)


def load_prompt_config() -> dict:
    if not PROMPT_CONFIG_PATH.exists():
        raise FileNotFoundError(f"提示词配置文件不存在: {PROMPT_CONFIG_PATH}")
    with PROMPT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_prompt_config(prompt_config: dict) -> dict:
    PROMPT_CONFIG_PATH.write_text(
        json.dumps(prompt_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return load_prompt_config()


def get_active_template(prompt_config: Optional[dict] = None) -> dict:
    prompt_config = prompt_config or load_prompt_config()
    active_id = prompt_config.get("activeTemplateId")
    templates = prompt_config.get("templates") or []
    for template in templates:
        if template.get("id") == active_id:
            return template
    if not templates:
        raise ValueError("提示词模板列表为空")
    return templates[0]


def build_prompt(book_name: str, template_id: Optional[str] = None) -> tuple[str, dict]:
    prompt_config = load_prompt_config()
    template = None
    for item in prompt_config.get("templates") or []:
        if template_id and item.get("id") == template_id:
            template = item
            break
    if template is None:
        template = get_active_template(prompt_config)
    content = str(template.get("content", "")).replace("{book_name}", book_name or "")
    return content, template


def test_gemini_connection(config_override: Optional[dict] = None) -> dict:
    """
    测试 Gemini 连接

    config_override 可以是单个 profile 对象，也可以是完整的 runtime 配置
    """
    # 如果传入的是完整 runtime 配置（包含 profiles），提取 active profile
    if config_override and "profiles" in config_override:
        active_id = config_override.get("activeProfileId", "")
        profiles = config_override.get("profiles", [])
        profile = None
        for p in profiles:
            if p.get("id") == active_id:
                profile = p
                break
        if not profile and profiles:
            profile = profiles[0]
        config_override = profile

    # 获取当前配置
    runtime_config = get_ai_runtime_config(mask_secret=False)
    active_profile = runtime_config.get("profiles", [{}])[0]

    # 合并覆盖参数
    if config_override:
        base_url = str(config_override.get("baseUrl", active_profile.get("baseUrl", ""))).rstrip("/")
        api_path = str(config_override.get("apiPath", active_profile.get("apiPath", ""))).strip()
        api_key = str(config_override.get("apiKey", active_profile.get("apiKey", ""))).strip()
        model = str(config_override.get("model", active_profile.get("model", ""))).strip()
        timeout = int(config_override.get("timeout", active_profile.get("timeout", GEMINI_TIMEOUT)))
    else:
        base_url = str(active_profile.get("baseUrl", "")).rstrip("/")
        api_path = str(active_profile.get("apiPath", "")).strip()
        api_key = str(active_profile.get("apiKey", "")).strip()
        model = str(active_profile.get("model", "")).strip()
        timeout = int(active_profile.get("timeout", GEMINI_TIMEOUT))

    if not base_url or not api_path or not api_key or not model:
        raise ValueError("Base URL、API Path、API Key、模型名称不能为空")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "contents": [{"parts": [{"text": "请回复: connection_ok"}]}],
        "generationConfig": {"responseModalities": ["TEXT"]},
    }

    # 用户手填的 apiPath 中可能包含 {model} 占位符，需要替换
    url = f"{base_url}{api_path}".replace("{model}", model)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout, verify=False)
        if response.ok:
            return {
                "success": True,
                "message": "连接测试成功",
                "statusCode": response.status_code,
                "url": url,
            }

        # 解析错误类型
        status_code = response.status_code
        error_text = response.text[:500]

        # 尝试解析 JSON 错误
        error_detail = error_text
        try:
            error_json = response.json()
            if "error" in error_json:
                error_obj = error_json["error"]
                if isinstance(error_obj, dict):
                    error_detail = error_obj.get("message_cn") or error_obj.get("message") or error_text
                else:
                    error_detail = str(error_obj)
        except:
            pass

        # 分类错误
        if status_code == 401 or status_code == 403:
            error_type = "auth_failed"
            error_msg = f"鉴权失败：API Key 无效或已过期"
        elif status_code == 503:
            error_type = "model_unavailable"
            error_msg = f"上游模型不可用：{error_detail}"
        elif status_code >= 500:
            error_type = "server_error"
            error_msg = f"服务端错误 ({status_code})：{error_detail}"
        elif status_code == 400:
            error_type = "config_error"
            error_msg = f"配置错误：{error_detail}"
        else:
            error_type = "unknown"
            error_msg = f"HTTP {status_code}：{error_detail}"

        return {
            "success": False,
            "error": error_msg,
            "errorType": error_type,
            "statusCode": status_code,
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "连接超时：请检查网络或增加超时时间",
            "errorType": "timeout",
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error": f"网络异常：无法连接到 {base_url}",
            "errorType": "network_error",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"接口测试失败：{str(e)}",
            "errorType": "unknown",
        }


def _extract_image_from_response(data: dict, target_size: Optional[tuple[int, int]] = None) -> Image.Image:
    candidates = data.get("candidates") or []
    for candidate in candidates:
        parts = ((candidate.get("content") or {}).get("parts") or [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data:
                continue
            mime_type = inline_data.get("mimeType") or inline_data.get("mime_type", "")
            if not mime_type.startswith("image/"):
                continue
            raw = base64.b64decode(inline_data.get("data", ""))
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            if target_size:
                image = image.resize(target_size, Image.Resampling.LANCZOS)
            return image
    raise RuntimeError("Gemini 响应中未找到图片数据")


def _save_image(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", dpi=(400, 400))


def _save_generated_image(print_root: str, category: str, image: Image.Image, prefix: str) -> str:
    target_dir = Path(print_root) / category
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{category}_{timestamp}.png"
    _save_image(target_dir / filename, image)
    return filename


def _save_spread_preview(print_root: str, image: Image.Image) -> str:
    preview_dir = Path(print_root) / "preview"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ai_spread_{timestamp}.png"
    _save_image(preview_dir / filename, image)
    return filename


def _guess_crop_lines(spread_size: tuple[int, int], page_w: int, page_h: int, spine_w: int) -> dict:
    spread_w, spread_h = spread_size
    ratio_total_w = max((page_w * 2) + spine_w, 1)

    usable_w = int(spread_w * 0.90)
    usable_h = int(spread_h * 0.82)
    start_x = max(0, (spread_w - usable_w) // 2)
    start_y = max(0, int(spread_h * 0.06))

    scale_x = usable_w / ratio_total_w
    scale_y = usable_h / max(page_h, 1)
    scale = max(0.01, min(scale_x, scale_y))

    scaled_page_w = max(20, int(page_w * scale))
    scaled_spine_w = max(4, int(spine_w * scale))
    content_w = scaled_page_w * 2 + scaled_spine_w
    content_h = max(20, int(page_h * scale))

    content_x = max(0, (spread_w - content_w) // 2)
    content_y = max(0, (spread_h - content_h) // 2)

    x1 = content_x
    x2 = x1 + scaled_page_w
    x3 = x2 + scaled_spine_w
    x4 = x3 + scaled_page_w
    y1 = content_y
    y2 = y1 + content_h

    return {
        "vertical": [x1, x2, x3, x4],
        "vertical_lines": [x1, x2, x3, x4],
        "horizontal": [y1, y2],
        "horizontal_lines": [y1, y2],
    }


def _normalize_crop_lines(crop_lines: Optional[dict]) -> dict:
    crop_lines = crop_lines or {}
    vertical = crop_lines.get("vertical") or crop_lines.get("vertical_lines") or []
    horizontal = crop_lines.get("horizontal") or crop_lines.get("horizontal_lines") or []
    return {
        "vertical": [int(v) for v in vertical],
        "vertical_lines": [int(v) for v in vertical],
        "horizontal": [int(v) for v in horizontal],
        "horizontal_lines": [int(v) for v in horizontal],
    }


def _resize_output_image(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)


def crop_gemini_spread(
    spread: Image.Image,
    page_w: int,
    page_h: int,
    spine_w: int,
    crop_lines: Optional[dict] = None,
) -> tuple[Image.Image, Image.Image, Image.Image, dict]:
    if crop_lines is None:
        crop_lines = _guess_crop_lines(spread.size, page_w, page_h, spine_w)

    crop_lines = _normalize_crop_lines(crop_lines)
    vertical = crop_lines.get("vertical") or []
    horizontal = crop_lines.get("horizontal") or []
    if len(vertical) != 4 or len(horizontal) != 2:
        raise ValueError("裁切线数量非法，必须为 4 条垂直线和 2 条水平线")

    x1, x2, x3, x4 = [int(v) for v in vertical]
    y1, y2 = [int(v) for v in horizontal]

    if not (0 <= x1 < x2 < x3 < x4 <= spread.width and 0 <= y1 < y2 <= spread.height):
        raise ValueError("裁切线坐标非法")

    back_raw = spread.crop((x1, y1, x2, y2)).convert("RGB")
    spine_raw = spread.crop((x2, y1, x3, y2)).convert("RGB")
    front_raw = spread.crop((x3, y1, x4, y2)).convert("RGB")

    back_img = _resize_output_image(back_raw, page_w, page_h)
    spine_img = _resize_output_image(spine_raw, spine_w, page_h)
    front_img = _resize_output_image(front_raw, page_w, page_h)
    return front_img, back_img, spine_img, crop_lines


def _generate_spread_gemini(
    cover: Image.Image,
    book_name: str,
    page_w: int,
    page_h: int,
    spine_w: int,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    template_id: Optional[str] = None,
) -> tuple[Image.Image, Image.Image, Image.Image, dict, dict]:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 未在 booklore.env 中配置")

    prompt, template = build_prompt(book_name, template_id=template_id)

    if progress_callback:
        progress_callback(5, "【第一步】读取当前提示词模板")
        progress_callback(10, f"已加载模板：{template.get('name', '未命名模板')}")

    scale = min(GEMINI_IMAGE_MAX_SEND / max(cover.size), 1.0)
    cover_send = cover.resize(
        (int(cover.width * scale), int(cover.height * scale)),
        Image.Resampling.LANCZOS,
    )
    buf = io.BytesIO()
    cover_send.save(buf, format="JPEG", quality=90)
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    if progress_callback:
        progress_callback(15, "【第二步】封面已压缩，准备请求 Gemini")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}",
    }
    url = f"{GEMINI_API_URL}{GEMINI_API_PATH}".replace("{model}", GEMINI_IMAGE_MODEL)
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
            ]
        }],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    if progress_callback:
        progress_callback(30, "【第三步】已发送 Gemini 请求，等待返回展开图")

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=GEMINI_TIMEOUT,
        verify=False,
    )
    if not response.ok:
        logger.error("[Gemini Spread] API 错误 %s: %s", response.status_code, response.text[:400])
        raise RuntimeError(f"Gemini 请求失败: HTTP {response.status_code} - {response.text[:300]}")

    data = response.json()
    usage = data.get("usageMetadata", {}) or {}
    token_usage = {
        "input_tokens": usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
        "total_tokens": usage.get("totalTokenCount", 0),
    }

    if progress_callback:
        progress_callback(70, "【第四步】Gemini 已返回，开始提取图片")

    spread = _extract_image_from_response(data, target_size=None)
    crop_lines = _guess_crop_lines(spread.size, page_w, page_h, spine_w)
    front_img, back_img, spine_img, crop_lines = crop_gemini_spread(
        spread,
        page_w,
        page_h,
        spine_w,
        crop_lines=crop_lines,
    )

    if progress_callback:
        progress_callback(90, "【第五步】已生成初始裁切线")

    return spread, back_img, spine_img, crop_lines, token_usage


def generate_spread_preview(
    print_root: str,
    cover_filename: str,
    book_title: str,
    trim_size: str,
    spine_width_mm: float,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    template_id: Optional[str] = None,
) -> dict:
    cover_path = Path(print_root) / "cover" / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"封面图不存在: {cover_path}")

    cover = Image.open(cover_path).convert("RGB")
    page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
    spine_px = max(1, round(spine_width_mm * 400 / 25.4))

    if progress_callback:
        progress_callback(0, "开始生成 Gemini 展开图...")
        progress_callback(2, f"封面尺寸: {cover.width}x{cover.height}px")

    spread, _back_img, _spine_img, crop_lines, token_usage = _generate_spread_gemini(
        cover=cover,
        book_name=book_title or "",
        page_w=page_w,
        page_h=page_h,
        spine_w=spine_px,
        progress_callback=progress_callback,
        template_id=template_id,
    )

    spread_filename = _save_spread_preview(print_root, spread)

    if progress_callback:
        progress_callback(100, "Gemini 展开图生成完成")

    return {
        "spread_filename": spread_filename,
        "spread_size": {"width": spread.width, "height": spread.height},
        "crop_lines": crop_lines,
        "token_usage": token_usage,
    }


def save_cropped_materials(
    print_root: str,
    spread_filename: str,
    trim_size: str,
    spine_width_mm: float,
    vertical_lines: list[int],
    horizontal_lines: list[int],
) -> dict:
    spread_path = Path(print_root) / "preview" / spread_filename
    if not spread_path.exists():
        raise FileNotFoundError(f"展开图不存在: {spread_path}")

    spread = Image.open(spread_path).convert("RGB")
    page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
    spine_px = max(1, round(spine_width_mm * 400 / 25.4))

    _front_img, back_img, spine_img, crop_lines = crop_gemini_spread(
        spread,
        page_w,
        page_h,
        spine_px,
        crop_lines={"vertical": vertical_lines, "horizontal": horizontal_lines},
    )

    back_filename = _save_generated_image(print_root, "back", back_img, "ai")
    spine_filename = _save_generated_image(print_root, "spine", spine_img, "ai")

    return {
        "back_filename": back_filename,
        "spine_filename": spine_filename,
        "crop_lines": crop_lines,
    }


def generate_ai_material(
    print_root: str,
    cover_filename: str,
    target: str,
    book_title: str = "",
    trim_size: str = "A5",
    spine_width_mm: float = 4.74,
    count: int = 1,
    quality: str = "medium",
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> tuple[list[str], dict]:
    """
    兼容旧调用入口：
    当前仍可按 target=spine/back 调用，但内部会先生成整张展开图，再自动按初始裁切线裁切。
    这样能最大限度减少对现有异步任务流程的影响。
    """
    del count, quality

    cover_path = Path(print_root) / "cover" / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"封面图不存在: {cover_path}")

    page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
    spine_px = max(1, round(spine_width_mm * 400 / 25.4))
    cover = Image.open(cover_path).convert("RGB")

    if progress_callback:
        progress_callback(0, f"开始生成{'书脊' if target == 'spine' else '封底'}（Gemini）")

    spread, back_img, spine_img, _crop_lines, token_usage = _generate_spread_gemini(
        cover=cover,
        book_name=book_title or "",
        page_w=page_w,
        page_h=page_h,
        spine_w=spine_px,
        progress_callback=progress_callback,
        template_id=None,
    )

    _save_spread_preview(print_root, spread)

    if target == "back":
        filename = _save_generated_image(print_root, "back", back_img, "ai")
    elif target == "spine":
        filename = _save_generated_image(print_root, "spine", spine_img, "ai")
    else:
        raise ValueError("target 必须为 spine 或 back")

    if progress_callback:
        progress_callback(100, f"{'书脊' if target == 'spine' else '封底'}生成完成")

    return [filename], token_usage

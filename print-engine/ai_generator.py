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
import hashlib
import io
import json
import logging
import os
import time
import uuid
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


def calculate_dynamic_resolution(
    cover_path: Path,
    trim_size: str,
    spine_width_mm: float,
) -> tuple[int, int, int, int]:
    """
    Calculate target pixel dimensions based on original cover resolution.

    Returns:
        (page_w, page_h, spine_px, target_dpi)
        Falls back to TRIM_SIZE_PX if cover is low-res or unreadable.
    """
    # Get trim dimensions in mm
    trim_map_mm = {
        "A5": (148, 210),
        "B5": (176, 250),
        "A4": (210, 297),
    }
    trim_width_mm, trim_height_mm = trim_map_mm.get(trim_size, trim_map_mm["A5"])

    # Try to read cover dimensions
    try:
        with Image.open(cover_path) as cover:
            cover_w, cover_h = cover.size
    except Exception:
        # Fallback to default
        page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
        spine_px = max(1, round(spine_width_mm * 300 / 25.4))
        return page_w, page_h, spine_px, 300

    # Calculate cover DPI
    cover_dpi_w = cover_w / (trim_width_mm / 25.4)
    cover_dpi_h = cover_h / (trim_height_mm / 25.4)
    cover_dpi = min(cover_dpi_w, cover_dpi_h)

    # Use cover DPI if it's higher than baseline (212 for A5)
    baseline_dpi = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])[0] / (trim_width_mm / 25.4)

    if cover_dpi >= baseline_dpi:
        target_dpi = cover_dpi
        page_w = round(trim_width_mm / 25.4 * target_dpi)
        page_h = round(trim_height_mm / 25.4 * target_dpi)
        spine_px = max(1, round(spine_width_mm / 25.4 * target_dpi))
    else:
        # Cover is low-res, use defaults
        page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
        spine_px = max(1, round(spine_width_mm * 300 / 25.4))
        target_dpi = 300

    return page_w, page_h, spine_px, int(target_dpi)


def _enhance_spine_quality(spine_img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Phase 2 书脊清晰度增强。

    当原始裁切区域像素不足时，通过高质量重采样和轻度锐化提升清晰度。
    """
    from PIL import ImageFilter

    # 先用 LANCZOS 重采样到目标尺寸
    enhanced = spine_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 应用轻度锐化，增强文字边缘
    # UnsharpMask(radius, percent, threshold)
    # - radius: 锐化半径，2-3 适合文字
    # - percent: 锐化强度，80-120 为保守范围
    # - threshold: 阈值，避免过度锐化平滑区域
    enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=2.5, percent=100, threshold=2))

    return enhanced


BOOKLORE_ENV_PATH = Path("booklore.env")
AI_PROFILES_CONFIG_PATH = Path(os.getenv("AI_PROFILES_CONFIG_PATH", "./ai_profiles.json"))
PROMPT_CONFIG_PATH = Path(os.getenv("AI_PROMPT_CONFIG_PATH", "./ai_prompts.json"))
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://api.302.ai").rstrip("/")
GEMINI_API_PATH = os.getenv("GEMINI_API_PATH", "/google/v1/models/{model}")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "240"))
GEMINI_IMAGE_MAX_SEND = int(os.getenv("GEMINI_IMAGE_MAX_SEND", "4096"))


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
    GEMINI_IMAGE_MAX_SEND = int(os.getenv("GEMINI_IMAGE_MAX_SEND", "4096"))


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
                "imageSize": "2K",
                "imageSizeSupported": None,
                "imageSizeDetectionStatus": "unknown",
                "imageSizeDetectionFingerprint": None,
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
            "imageSize": str(profile.get("imageSize", "2K")).strip(),
            "imageSizeSupported": profile.get("imageSizeSupported"),
            "imageSizeDetectionStatus": str(profile.get("imageSizeDetectionStatus", "unknown")).strip(),
            "imageSizeDetectionFingerprint": profile.get("imageSizeDetectionFingerprint"),
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


def _build_image_size_fingerprint(base_url: str, api_path: str, api_key: str, model: str) -> str:
    raw = "|".join([
        str(base_url).strip(),
        str(api_path).strip(),
        str(api_key).strip(),
        str(model).strip(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _probe_image_size_support(url: str, headers: dict, timeout: int) -> bool:
    payload = {
        "contents": [{"parts": [{"text": "请生成一个简单的纯色方形测试图。"}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageSize": "2K",
        },
    }

    probe_timeout = min(timeout, 30)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=probe_timeout)
    except requests.RequestException:
        return False

    if response.ok:
        return True

    try:
        error_json = response.json()
    except Exception:
        return False

    error_obj = error_json.get("error") or {}
    if not isinstance(error_obj, dict):
        return False

    message = str(error_obj.get("message_cn") or error_obj.get("message") or "").lower()
    unsupported_markers = [
        "imagesize",
        "unknown field",
        "invalid argument",
        "unsupported",
        "not supported",
    ]
    return not any(marker in message for marker in unsupported_markers)


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
    detection_fingerprint = _build_image_size_fingerprint(base_url, api_path, api_key, model)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if response.ok:
            image_size_supported = _probe_image_size_support(url, headers, timeout)
            return {
                "success": True,
                "message": "连接测试成功",
                "statusCode": response.status_code,
                "url": url,
                "capabilities": {
                    "imageSize": image_size_supported,
                },
                "detectionFingerprint": detection_fingerprint,
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
    inspected_parts: list[str] = []

    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            inspected_parts.append(",".join(sorted(part.keys())))

            inline_data = (
                part.get("inlineData")
                or part.get("inline_data")
                or part.get("image")
                or part.get("imageData")
            )
            if not inline_data:
                file_data = part.get("fileData") or part.get("file_data") or {}
                if (file_data.get("mimeType") or file_data.get("mime_type", "")).startswith("image/"):
                    raise RuntimeError("Gemini 返回的是图片文件引用而不是内联图片数据，当前通道暂不支持 fileData 拉取")
                continue

            mime_type = (
                inline_data.get("mimeType")
                or inline_data.get("mime_type")
                or inline_data.get("contentType")
                or inline_data.get("content_type", "")
            )
            data_b64 = inline_data.get("data") or inline_data.get("base64") or inline_data.get("bytesBase64") or ""
            if not mime_type.startswith("image/") or not data_b64:
                continue

            raw = base64.b64decode(data_b64)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            if target_size:
                image = image.resize(target_size, Image.Resampling.LANCZOS)
            return image

    response_excerpt = json.dumps(data, ensure_ascii=False)[:1200]
    parts_summary = "; ".join(inspected_parts[:10]) or "<no parts>"
    raise RuntimeError(f"Gemini 响应中未找到图片数据，parts keys: {parts_summary}，response: {response_excerpt}")


def _save_image(path: Path, image: Image.Image, dpi: int = 400) -> None:
    """
    保存图像到指定路径，并设置DPI元数据。

    Args:
        path: 保存路径
        image: PIL图像对象
        dpi: 输出DPI（默认400）
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", dpi=(dpi, dpi))


def _build_timestamp_suffix() -> str:
    """
    生成带高精度时间戳和唯一标识的文件名后缀。

    格式：YYYYMMDD_HHMMSS_微秒_短UUID
    示例：20260325_143052_123456_a3f9

    Returns:
        唯一文件名后缀字符串
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    unique_suffix = uuid.uuid4().hex[:4]
    return f"{timestamp}_{unique_suffix}"



def _save_generated_image(print_root: str, category: str, image: Image.Image, prefix: str, dpi: int = 400) -> str:
    """
    保存生成的素材图像。

    Args:
        print_root: 打印根目录
        category: 素材类别（cover/spine/back）
        image: PIL图像对象
        prefix: 文件名前缀
        dpi: 输出DPI（书脊建议600，封面/封底300-400）

    Returns:
        保存的文件名
    """
    target_dir = Path(print_root) / category
    timestamp = _build_timestamp_suffix()
    filename = f"{prefix}_{category}_{timestamp}.png"
    _save_image(target_dir / filename, image, dpi=dpi)
    return filename


def _save_spread_preview(print_root: str, image: Image.Image) -> str:
    preview_dir = Path(print_root) / "preview"
    timestamp = _build_timestamp_suffix()
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
    spine_dpi: int = 600,
) -> tuple[Image.Image, Image.Image, Image.Image, dict]:
    """
    裁切 Gemini 生成的展开图，分离出封面、封底、书脊。

    Args:
        spread: 展开图
        page_w: 目标页面像素宽度（@300DPI）
        page_h: 目标页面像素高度（@300DPI）
        spine_w: 目标书脊像素宽度（@300DPI）
        crop_lines: 裁切线坐标
        spine_dpi: 书脊输出DPI（默认600，保持文字清晰）

    Returns:
        (front_img, back_img, spine_img, crop_lines)
    """
    if crop_lines is None:
        crop_lines = _guess_crop_lines(spread.size, page_w, page_h, spine_w)

    crop_lines = _normalize_crop_lines(crop_lines)
    vertical = crop_lines.get("vertical") or []
    horizontal = crop_lines.get("horizontal") or []
    if len(vertical) != 4 or len(horizontal) != 2:
        raise ValueError("裁切线数量非法，必须为 4 条垂直线和 2 条水平线")

    x1, x2, x3, x4 = sorted(int(v) for v in vertical)
    y1, y2 = sorted(int(v) for v in horizontal)

    if not (0 <= x1 < x2 < x3 < x4 <= spread.width and 0 <= y1 < y2 <= spread.height):
        raise ValueError("裁切线坐标非法")

    normalized_vertical = [x1, x2, x3, x4]
    normalized_horizontal = [y1, y2]
    crop_lines = _normalize_crop_lines({
        "vertical": normalized_vertical,
        "horizontal": normalized_horizontal,
    })

    back_raw = spread.crop((x1, y1, x2, y2)).convert("RGB")
    spine_raw = spread.crop((x2, y1, x3, y2)).convert("RGB")
    front_raw = spread.crop((x3, y1, x4, y2)).convert("RGB")

    # 封面/封底：缩放到目标尺寸
    back_img = _resize_output_image(back_raw, page_w, page_h)
    front_img = _resize_output_image(front_raw, page_w, page_h)

    # 书脊：Phase 2 改为显式输出目标宽高，而不是保留原始裁切宽度
    spine_target_w = max(1, spine_w)
    spine_target_h = max(page_h, round(page_h * spine_dpi / 300))

    # 根据原始裁切宽度判断是否需要增强
    source_to_target_ratio = spine_raw.width / max(1, spine_target_w)
    needs_spine_enhancement = source_to_target_ratio < 1.15

    logger.info(
        "[Spine Analyze] source=%sx%s target=%sx%s ratio=%.3f enhance=%s",
        spine_raw.width,
        spine_raw.height,
        spine_target_w,
        spine_target_h,
        source_to_target_ratio,
        needs_spine_enhancement,
    )

    if needs_spine_enhancement:
        spine_img = _enhance_spine_quality(spine_raw, spine_target_w, spine_target_h)
    else:
        spine_img = spine_raw.resize((spine_target_w, spine_target_h), Image.Resampling.LANCZOS)

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
    spread_target_w = max(4000, page_w * 2 + max(spine_w * 6, spine_w + 400))
    prompt = (
        f"{prompt}\n\n"
        "【输出要求】必须直接返回最终生成的图片结果。"
        "不要返回任何文字说明、Markdown、代码块、前言、后记或额外解释。"
        "如果无法生成图片，也不要输出描述性文字。\n"
        f"【分辨率要求】生成的展开图必须保持高分辨率（至少{spread_target_w}px宽度），确保书脊文字清晰锐利。"
        "书脊区域必须给出清晰、锐利、可印刷的标题文字边缘，避免模糊、发光、糊边和低对比度。"
    )

    if progress_callback:
        progress_callback(5, "【第一步】读取当前提示词模板")
        progress_callback(10, f"已加载模板：{template.get('name', '未命名模板')}")

    scale = min(GEMINI_IMAGE_MAX_SEND / max(cover.size), 1.0)
    cover_send = cover if scale >= 1.0 else cover.resize(
        (int(cover.width * scale), int(cover.height * scale)),
        Image.Resampling.LANCZOS,
    )
    buf = io.BytesIO()
    cover_send.save(buf, format="JPEG", quality=95)
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    if progress_callback:
        progress_callback(15, "【第二步】封面参考图已准备，准备请求 Gemini")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}",
    }
    url = f"{GEMINI_API_URL}{GEMINI_API_PATH}".replace("{model}", GEMINI_IMAGE_MODEL)

    runtime_config = get_ai_runtime_config(mask_secret=False)
    active_profile_id = runtime_config.get("activeProfileId", "")
    active_profile = None
    for profile in runtime_config.get("profiles", []):
        if profile.get("id") == active_profile_id:
            active_profile = profile
            break
    if not active_profile:
        profiles_list = runtime_config.get("profiles", [])
        active_profile = profiles_list[0] if profiles_list else {}

    current_fingerprint = _build_image_size_fingerprint(
        active_profile.get("baseUrl", ""),
        active_profile.get("apiPath", ""),
        active_profile.get("apiKey", ""),
        active_profile.get("model", ""),
    )
    image_size_supported = (
        active_profile.get("imageSizeSupported") is True
        and active_profile.get("imageSizeDetectionStatus") == "supported"
        and active_profile.get("imageSizeDetectionFingerprint") == current_fingerprint
    )
    image_size_value = str(active_profile.get("imageSize", "2K")).strip()

    def request_generation(prompt_text: str) -> tuple[dict, dict]:
        generation_config = {"responseModalities": ["TEXT", "IMAGE"]}
        if image_size_supported and image_size_value in ("1K", "2K", "4K"):
            generation_config["imageSize"] = image_size_value

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt_text},
                    {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                ]
            }],
            "generationConfig": generation_config,
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=GEMINI_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("AI_TIMEOUT::AI 生图超时：该网关长时间未返回图片，可尝试更换模型或中转")
        except requests.exceptions.ConnectionError as e:
            error_msg = str(e)
            if "RemoteDisconnected" in error_msg or "Connection aborted" in error_msg:
                raise RuntimeError("AI_CONNECTION_ABORTED::AI 生图连接被对端中断：中转服务主动断开连接，通常是网关不稳定或上游限流")
            else:
                raise RuntimeError(f"AI_NETWORK_ERROR::AI 生图网络异常：无法连接到 {GEMINI_API_URL}")
        except requests.RequestException as e:
            raise RuntimeError(f"AI_REQUEST_ERROR::AI 生图请求异常：{str(e)}")

        if not response.ok:
            status_code = response.status_code
            error_text = response.text[:500]
            logger.error("[Gemini Spread] API 错误 %s: %s", status_code, error_text)

            if status_code == 400:
                raise RuntimeError(f"AI_BAD_REQUEST::AI 生图失败 (HTTP 400)：通常是模型名 / API Path / 请求体格式不兼容 - {error_text[:200]}")
            elif status_code == 401 or status_code == 403:
                raise RuntimeError("AI_AUTH_FAILED::AI 生图鉴权失败：API Key 无效或已过期")
            elif status_code == 503:
                raise RuntimeError("AI_SERVICE_UNAVAILABLE::AI 生图失败 (HTTP 503)：上游模型暂时不可用")
            elif status_code >= 500:
                raise RuntimeError(f"AI_SERVER_ERROR::AI 生图服务端错误 (HTTP {status_code})：{error_text[:200]}")
            else:
                raise RuntimeError(f"AI_HTTP_ERROR::AI 生图失败 (HTTP {status_code})：{error_text[:200]}")

        data = response.json()
        usage = data.get("usageMetadata", {}) or {}
        token_usage = {
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }
        return data, token_usage

    if progress_callback:
        progress_callback(30, "【第三步】已发送 Gemini 请求，等待返回展开图")

    data, token_usage = request_generation(prompt)

    if progress_callback:
        progress_callback(70, "【第四步】Gemini 已返回，开始提取图片")

    try:
        spread = _extract_image_from_response(data, target_size=None)
    except RuntimeError as e:
        if "未找到图片数据" in str(e):
            raise RuntimeError("AI_NO_IMAGE::AI 返回了非图片内容：该模型/路径可能不支持当前图片生成请求格式")
        raise

    estimated_spine_crop_w = max(1, round(spread.width * spine_w / max(1, page_w * 2 + spine_w)))
    logger.info(
        "[Gemini Spread] returned=%sx%s target_page=%sx%s target_spine=%s estimated_spine_crop=%s",
        spread.width,
        spread.height,
        page_w,
        page_h,
        spine_w,
        estimated_spine_crop_w,
    )
    if progress_callback:
        progress_callback(85, f"【第五步】展开图尺寸: {spread.width}x{spread.height}px，预估书脊原始宽度: {estimated_spine_crop_w}px")

    crop_lines = _guess_crop_lines(spread.size, page_w, page_h, spine_w)
    front_img, back_img, spine_img, crop_lines = crop_gemini_spread(
        spread,
        page_w,
        page_h,
        spine_w,
        crop_lines=crop_lines,
    )

    if progress_callback:
        progress_callback(90, "【第六步】已生成初始裁切线")

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
    """
    生成 Gemini 展开图预览（用于裁切工具）。

    使用300 DPI作为基准计算书脊宽度。
    """
    cover_path = Path(print_root) / "cover" / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"封面图不存在: {cover_path}")

    cover = Image.open(cover_path).convert("RGB")
    page_w, page_h, spine_px, target_dpi = calculate_dynamic_resolution(
        cover_path=cover_path,
        trim_size=trim_size,
        spine_width_mm=spine_width_mm,
    )

    if progress_callback:
        progress_callback(0, "开始生成 Gemini 展开图...")
        progress_callback(2, f"封面尺寸: {cover.width}x{cover.height}px, 目标DPI: {target_dpi}")

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
    source_cover_filename: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """
    保存用户裁切后的素材（封面、书脊、封底）。

    书脊使用600 DPI保存，确保文字清晰；封面/封底使用300 DPI。
    """
    spread_path = Path(print_root) / "preview" / spread_filename
    if not spread_path.exists():
        raise FileNotFoundError(f"展开图不存在: {spread_path}")

    spread = Image.open(spread_path).convert("RGB")

    if source_cover_filename:
        cover_path = Path(print_root) / "cover" / source_cover_filename
        page_w, page_h, spine_px, target_dpi = calculate_dynamic_resolution(
            cover_path=cover_path,
            trim_size=trim_size,
            spine_width_mm=spine_width_mm,
        )
        # Spine uses 2x DPI for text clarity
        spine_dpi = target_dpi * 2
    else:
        # Fallback to defaults
        page_w, page_h = TRIM_SIZE_PX.get(trim_size, TRIM_SIZE_PX["A5"])
        spine_px = max(1, round(spine_width_mm * 300 / 25.4))
        target_dpi = 300
        spine_dpi = 600

    if progress_callback:
        progress_callback(10, f"目标DPI: {target_dpi}, 书脊DPI: {spine_dpi}")

    front_img, back_img, spine_img, crop_lines = crop_gemini_spread(
        spread,
        page_w,
        page_h,
        spine_px,
        crop_lines={"vertical": vertical_lines, "horizontal": horizontal_lines},
        spine_dpi=spine_dpi,
    )

    if progress_callback:
        progress_callback(50, "裁切完成，正在保存素材...")

    front_output_dir = Path(print_root) / "front_output"
    timestamp = _build_timestamp_suffix()
    front_filename = f"ai_front_{timestamp}.png"
    _save_image(front_output_dir / front_filename, front_img, dpi=target_dpi)

    # 封底使用动态DPI
    back_filename = _save_generated_image(print_root, "back", back_img, "ai", dpi=target_dpi)
    # 书脊使用2x DPI，文字更清晰
    spine_filename = _save_generated_image(print_root, "spine", spine_img, "ai", dpi=spine_dpi)

    if progress_callback:
        progress_callback(100, "素材保存完成")

    return {
        "front_filename": front_filename,
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

    书脊使用600 DPI保存，封底使用300 DPI。
    """
    del count, quality

    cover_path = Path(print_root) / "cover" / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"封面图不存在: {cover_path}")

    page_w, page_h, spine_px, target_dpi = calculate_dynamic_resolution(
        cover_path=cover_path,
        trim_size=trim_size,
        spine_width_mm=spine_width_mm,
    )
    spine_dpi = target_dpi * 2
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
        filename = _save_generated_image(print_root, "back", back_img, "ai", dpi=target_dpi)
    elif target == "spine":
        filename = _save_generated_image(print_root, "spine", spine_img, "ai", dpi=spine_dpi)
    else:
        raise ValueError("target 必须为 spine 或 back")

    if progress_callback:
        progress_callback(100, f"{'书脊' if target == 'spine' else '封底'}生成完成")

    return [filename], token_usage

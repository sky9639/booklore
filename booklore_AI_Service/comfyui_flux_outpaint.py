"""
Booklore FLUX Outpainting Client V2.0
两步生成：
  Step1: 封面 → 向左 outpaint 封底（封底和封面各占50%画布）
  Step2: 封面左边缘 → 向左 outpaint 书脊（单独生成窄条）
"""

import io
import time
import uuid

import requests
from PIL import Image, ImageDraw

COMFYUI_URL = "http://127.0.0.1:8188"


# ──────────────────────────────────────────
# 工作流构建
# ──────────────────────────────────────────


def build_flux_inpaint_workflow(
    canvas_fn, mask_fn, prompt, seed, steps=20, guidance=3.5
):
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
                "grow_mask_by": 0,
            },
        },  # grow=0 避免边缘扩展
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


# ──────────────────────────────────────────
# 上传 / 运行
# ──────────────────────────────────────────


def upload_image(img_bytes, filename):
    resp = requests.post(
        f"{COMFYUI_URL}/upload/image",
        files={"image": (filename, io.BytesIO(img_bytes), "image/png")},
        data={"overwrite": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["name"]


def run_workflow(workflow, timeout=300):
    client_id = str(uuid.uuid4())
    resp = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=15,
    )
    if resp.status_code != 200:
        raise Exception(f"ComfyUI 提交失败: {resp.text}")
    prompt_id = resp.json()["prompt_id"]
    print(f"[ComfyUI] 任务已提交: {prompt_id}")
    for _ in range(timeout):
        time.sleep(1)
        history = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json()
        if prompt_id in history:
            for node_output in history[prompt_id]["outputs"].values():
                if "images" in node_output:
                    info = node_output["images"][0]
                    r = requests.get(
                        f"{COMFYUI_URL}/view",
                        params={
                            "filename": info["filename"],
                            "subfolder": info.get("subfolder", ""),
                            "type": info.get("type", "output"),
                        },
                        timeout=15,
                    )
                    r.raise_for_status()
                    return r.content
    raise TimeoutError(f"超时: {prompt_id}")


def make_canvas_and_mask(bg_img, fill_w, fill_on_left=True):
    """
    bg_img: 已有内容的 PIL Image（封面或封面裁边）
    fill_w: 需要填充的宽度（左侧）
    返回 (canvas_bytes, mask_bytes, total_w, total_h)
    """
    bw, bh = bg_img.size
    total_w = fill_w + bw
    total_h = bh

    canvas = Image.new("RGB", (total_w, total_h), (200, 200, 200))
    mask = Image.new("L", (total_w, total_h), 0)  # 全黑=保留
    md = ImageDraw.Draw(mask)

    if fill_on_left:
        canvas.paste(bg_img, (fill_w, 0))  # 内容贴右边
        md.rectangle([(0, 0), (fill_w - 1, total_h - 1)], fill=255)  # 左侧白=填充
    else:
        canvas.paste(bg_img, (0, 0))  # 内容贴左边
        md.rectangle([(bw, 0), (total_w - 1, total_h - 1)], fill=255)

    cb = io.BytesIO()
    canvas.save(cb, "PNG")
    mb = io.BytesIO()
    mask.save(mb, "PNG")
    return cb.getvalue(), mb.getvalue(), total_w, total_h


def flux_generate(canvas_bytes, mask_bytes, prompt, seed, steps):
    """上传画布和mask，提交FLUX任务，返回生成图bytes"""
    cf = upload_image(canvas_bytes, "canvas.png")
    mf = upload_image(mask_bytes, "mask.png")
    wf = build_flux_inpaint_workflow(cf, mf, prompt, seed, steps)
    raw = run_workflow(wf)
    # 返回前验证尺寸
    return raw


def resize_to(img_bytes, w, h):
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img


# ──────────────────────────────────────────
# 主入口：两步生成
# ──────────────────────────────────────────


def outpaint_cover(
    cover_path,
    prompt_back,
    prompt_spine,
    back_width_px,
    spine_width_px,
    page_height_px,
    seed=-1,
    steps=20,
):
    """
    Step1: 生成封底
    Step2: 生成书脊
    返回 (back_img, spine_img, cover_img) 三张 PIL Image，已对齐到 page_height_px
    """
    if seed == -1:
        seed = int(time.time() * 1000) % (2**32)

    # 加载并缩放封面
    cover_orig = Image.open(cover_path).convert("RGB")
    scale = page_height_px / cover_orig.height
    cw = int(cover_orig.width * scale)
    cover = cover_orig.resize((cw, page_height_px), Image.LANCZOS)
    print(f"[封面] 缩放后尺寸: {cw}x{page_height_px}")

    # ── Step 1: 生成封底 ──
    # 画布 = [封底空白(back_width_px)] + [封面(cw)]
    # 为了让FLUX更好地延伸，封面和封底各占画布约50%
    # 如果 back_width_px 远小于 cw，适当用封面左边一部分做参考
    ref_w = min(cw, back_width_px)  # 用封面左侧 ref_w 宽度作为参考
    ref_img = cover.crop((0, 0, ref_w, page_height_px))

    print(f"\n[Step1] 生成封底 {back_width_px}x{page_height_px}...")
    canvas_b, mask_b, tw1, th1 = make_canvas_and_mask(
        ref_img, back_width_px, fill_on_left=True
    )
    raw1 = flux_generate(canvas_b, mask_b, prompt_back, seed, steps)
    result1 = resize_to(raw1, tw1, th1)
    back_img = result1.crop((0, 0, back_width_px, th1))
    print(f"[Step1] 封底生成完成: {back_img.size}")

    # ── Step 2: 生成书脊 ──
    # 画布 = [书脊空白(spine_width_px)] + [封面左边缘(spine_width_px*3)]
    # 用封面左边缘做参考，书脊应和封面边缘色彩自然衔接
    edge_w = min(cw, spine_width_px * 4)  # 封面左侧边缘参考宽度
    edge_img = cover.crop((0, 0, edge_w, page_height_px))

    print(f"\n[Step2] 生成书脊 {spine_width_px}x{page_height_px}...")
    canvas_b2, mask_b2, tw2, th2 = make_canvas_and_mask(
        edge_img, spine_width_px, fill_on_left=True
    )
    raw2 = flux_generate(canvas_b2, mask_b2, prompt_spine, seed + 1, steps)
    result2 = resize_to(raw2, tw2, th2)
    spine_img = result2.crop((0, 0, spine_width_px, th2))
    print(f"[Step2] 书脊生成完成: {spine_img.size}")

    return back_img, spine_img, cover

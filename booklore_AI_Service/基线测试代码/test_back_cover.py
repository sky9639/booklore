"""
封底+书脊 整合测试脚本
存放位置：E:\AI\booklore_AI\test_back_cover.py

输出3张图：
  output_back.png          单独封底（含文字）
  output_spine.png         单独书脊（含文字）
  output_full_preview.png  封面+书脊+封底完整预览

用法：
  python test_back_cover.py cover.jpg --title "书名" --author "作者" --desc "简介" --spine-mm 4.74
"""

import os, sys, io, re, argparse, textwrap, base64, time
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfyui_flux_outpaint import flux_generate, make_canvas_and_mask, resize_to

JANUS_URL = "http://127.0.0.1:8788"
SIZE_MAP  = {"A4": (794, 1123), "A5": (559, 794), "B5": (665, 945)}
DPI       = 96  # 96dpi

FALLBACK_STYLE = (
    "seamless extension of book cover art, "
    "same color palette and illustration style, "
    "atmospheric background, professional book design"
)

# ─── 字体 ────────────────────────────────────────────────────────────────────

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
    ("C:/Windows/Fonts/msyhbd.ttc",  "C:/Windows/Fonts/msyh.ttc"),
    ("C:/Windows/Fonts/simsunb.ttf", "C:/Windows/Fonts/simsun.ttc"),
]

def load_font(size, bold=False):
    for bold_p, norm_p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(bold_p if bold else norm_p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

# ─── Janus ───────────────────────────────────────────────────────────────────

def get_style_from_janus(image_path, book_info, target="back"):
    try:
        requests.get(f"{JANUS_URL}/health", timeout=4).raise_for_status()
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(f"{JANUS_URL}/analyze", json={
            "image_base64": b64,
            "book_title":   book_info.get("title", ""),
            "authors":      book_info.get("authors", []),
            "categories":   book_info.get("categories", []),
            "description":  book_info.get("description", ""),
            "target":       target,
        }, timeout=90)
        style = resp.json().get("prompt", "").strip()
        if style:
            print(f"[Janus] 完整输出:\n{style}")
            return style
    except Exception as e:
        print(f"[Janus] 不可用: {e}")
    return FALLBACK_STYLE


def parse_janus_to_tags(style: str) -> str:
    """清洗 Janus 编号列表，只保留前4行（风格+色调+光照），丢弃内容词。"""
    lines = [l.strip() for l in style.strip().splitlines() if l.strip()]
    tags = []
    for line in lines:
        clean = re.sub(r'^[0-9]+[.)\s]+', '', line).strip()
        if clean and len(tags) < 4:
            tags.append(clean.lower())
    return ", ".join(tags) if tags else style[:150]

# ─── 文字合成（完全照搬 ai_generator.py 定稿逻辑）────────────────────────────

def draw_text_shadowed(draw, pos, text, font, fill=(255,255,255), shadow=(0,0,0), offset=2):
    x, y = pos
    for dx in (-offset, 0, offset):
        for dy in (-offset, 0, offset):
            if dx == 0 and dy == 0:
                continue
            draw.text((x+dx, y+dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def make_gradient_overlay(size, start_ratio=0.40):
    w, h    = size
    start_y = int(h * start_ratio)
    arr     = np.zeros((h, w, 4), dtype=np.uint8)
    if h > start_y:
        rows      = np.arange(h - start_y, dtype=np.float32)
        progress  = rows / (h - start_y)
        alpha_col = (185 * (progress ** 1.4)).astype(np.uint8)
        arr[start_y:, :, 3] = alpha_col[:, np.newaxis]
    return Image.fromarray(arr, mode="RGBA")


def composite_back(img: Image.Image, book_info: dict) -> Image.Image:
    img  = img.convert("RGBA")
    w, h = img.size
    gradient = make_gradient_overlay((w, h), start_ratio=0.40)
    img      = Image.alpha_composite(img, gradient).convert("RGB")
    draw     = ImageDraw.Draw(img)

    mx     = int(w * 0.08)
    mr     = w - int(w * 0.08)
    max_tw = mr - mx
    y      = int(h * 0.50)

    # 书名
    title     = book_info.get("title") or "Unknown Title"
    font_size = int(w * 0.070)
    font      = load_font(font_size, bold=True)
    while font_size > int(w * 0.026):
        if draw.textbbox((0, 0), title, font=font)[2] <= max_tw:
            break
        font_size -= 2
        font = load_font(font_size, bold=True)
    draw_text_shadowed(draw, (mx, y), title, font, fill=(255,255,255), shadow=(0,0,0), offset=2)
    y += draw.textbbox((0, 0), title, font=font)[3] + int(h * 0.016)

    # 作者
    authors = book_info.get("authors", [])
    if authors:
        a_str  = "by " + ", ".join(authors[:3]) if all(c.isascii() for c in authors[0]) else ", ".join(authors[:3])
        font_a = load_font(int(w * 0.029))
        draw_text_shadowed(draw, (mx, y), a_str, font_a, fill=(255,225,130), shadow=(0,0,0), offset=1)
        y += draw.textbbox((0, 0), a_str, font=font_a)[3] + int(h * 0.018)

    # 虚线分隔
    dash, gap, lx = 16, 7, mx
    while lx < mr - dash:
        draw.line([(lx, y+2), (lx+dash, y+2)], fill=(180,180,180), width=1)
        lx += dash + gap
    y += int(h * 0.026)

    # 简介
    desc     = book_info.get("description") or "A captivating story that will keep you turning pages."
    font_b   = load_font(int(w * 0.025))
    avg_cw   = max(1, int(w * 0.025 * 0.55))
    max_char = max(20, max_tw // avg_cw)
    line_h   = int(h * 0.033)
    for line in textwrap.fill(desc, width=max_char).split("\n"):
        if y + line_h > int(h * 0.95):
            draw_text_shadowed(draw, (mx, y), "…", font_b, fill=(190,190,190), shadow=(0,0,0), offset=1)
            break
        draw_text_shadowed(draw, (mx, y), line, font_b, fill=(225,225,225), shadow=(0,0,0), offset=1)
        y += line_h

    return img


def composite_spine(spine_img: Image.Image, book_info: dict) -> Image.Image:
    """
    书脊文字合成（V2.0基线）：rotate(-90) 横向写字 rotate(+90)
    旋转后：rw=原高(长度方向), rh=原宽(书脊宽度方向)
    主标题在长度方向和宽度方向均居中。
    """
    sw, sh = spine_img.size
    if sw < 5:
        return spine_img

    rotated = spine_img.rotate(-90, expand=True)
    rw, rh  = rotated.size   # rw=长度方向, rh=书脊宽度方向

    font_size = max(6, int(rh * 0.70))
    font_t    = load_font(font_size, bold=True)

    full_title = book_info.get("title") or ""
    main_title = full_title.split(":")[0].strip() if ":" in full_title else full_title

    draw = ImageDraw.Draw(rotated)

    max_text_w = int(rw * 0.96)
    while font_size > 6:
        bbox = draw.textbbox((0, 0), main_title, font=font_t)
        if bbox[2] - bbox[0] <= max_text_w:
            break
        font_size -= 1
        font_t = load_font(font_size, bold=True)

    bbox_t  = draw.textbbox((0, 0), main_title, font=font_t)
    tw_main = bbox_t[2] - bbox_t[0]
    th_main = bbox_t[3] - bbox_t[1]

    tx = max(0, (rw - tw_main) // 2)
    ty = max(0, (rh - th_main) // 2)

    overlay = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([(0, 0), (rw, rh)], fill=(0, 0, 0, 80))
    rotated = Image.alpha_composite(rotated.convert("RGBA"), overlay).convert("RGB")
    draw    = ImageDraw.Draw(rotated)

    draw.text((tx, ty), main_title, font=font_t, fill=(255, 255, 255))

    return rotated.rotate(90, expand=True)

def build_back_canvas(cover: Image.Image, page_w: int, page_h: int):
    """封底画布：crop策略，封面左侧原尺寸放右边，左边为生成区。mask右边缘羽化。"""
    cw      = cover.width
    ref_w   = min(cw, page_w)
    ref_img = cover.crop((0, 0, ref_w, page_h))
    canvas_b, mask_b, total_w, total_h = make_canvas_and_mask(
        ref_img, page_w, fill_on_left=True
    )
    # mask 右边缘羽化 12px，消除噪点条
    mask_img = Image.open(io.BytesIO(mask_b)).convert("L")
    mask_arr = np.array(mask_img, dtype=np.float32)
    for dx in range(12):
        x = page_w - 1 - dx
        if 0 <= x < mask_arr.shape[1]:
            mask_arr[:, x] *= (dx / 12)
    mb = io.BytesIO()
    Image.fromarray(mask_arr.astype(np.uint8)).save(mb, "PNG")
    return canvas_b, mb.getvalue(), total_w, total_h


def build_spine_canvas(cover: Image.Image, spine_px_gen: int, page_h: int):
    """书脊画布：封面左边缘(spine_px_gen*4宽)放右边，左边为生成区。"""
    cw     = cover.width
    edge_w = min(cw, spine_px_gen * 4)
    edge_img = cover.crop((0, 0, edge_w, page_h))
    canvas_b, mask_b, total_w, total_h = make_canvas_and_mask(
        edge_img, spine_px_gen, fill_on_left=True
    )
    return canvas_b, mask_b, total_w, total_h

# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="封底+书脊整合测试")
    parser.add_argument("image",               help="封面图片路径")
    parser.add_argument("--title",   default="", help="书名")
    parser.add_argument("--author",  default="", help="作者")
    parser.add_argument("--desc",    default="", help="简介")
    parser.add_argument("--genre",   default="", help="类型")
    parser.add_argument("--size",    choices=["A4","A5","B5"], default="A5")
    parser.add_argument("--steps",   type=int,   default=20)
    parser.add_argument("--seed",    type=int,   default=-1)
    parser.add_argument("--spine-mm",type=float, default=4.74, help="书脊宽度mm")
    parser.add_argument("--no-janus",action="store_true", help="跳过Janus")
    parser.add_argument("--no-text", action="store_true", help="跳过文字合成")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"[错误] 找不到: {args.image}"); sys.exit(1)

    page_w, page_h = SIZE_MAP[args.size]
    seed    = args.seed if args.seed != -1 else int(time.time() * 1000) % (2**32)
    out_dir = os.path.dirname(os.path.abspath(args.image))

    book_info = {
        "title":       args.title or os.path.splitext(os.path.basename(args.image))[0],
        "authors":     [args.author] if args.author else [],
        "description": args.desc,
        "categories":  [args.genre] if args.genre else [],
    }

    # 书脊像素（定稿逻辑：mm→px，不足150px强制放大生成后缩回）
    spine_px_real = max(1, int(args.spine_mm * page_h / 210))
    SPINE_GEN_MIN = 150
    spine_px_gen  = max(SPINE_GEN_MIN, spine_px_real)

    print("=" * 60)
    print(f"  封底+书脊 整合测试")
    print(f"  封面: {args.image}")
    print(f"  书名: {book_info['title']}")
    print(f"  尺寸: {args.size} ({page_w}x{page_h}px)")
    print(f"  书脊: {args.spine_mm}mm → {spine_px_real}px（生成用{spine_px_gen}px）")
    print(f"  Steps: {args.steps}  Seed: {seed}")
    print("=" * 60)

    # 1. 加载封面
    cover_orig = Image.open(args.image).convert("RGB")
    scale = page_h / cover_orig.height
    cw    = int(cover_orig.width * scale)
    cover = cover_orig.resize((cw, page_h), Image.LANCZOS)
    print(f"[封面] 缩放后: {cw}x{page_h}px")

    # 2. Janus 分析
    if args.no_janus:
        style = FALLBACK_STYLE
        print("[Janus] 跳过，使用 fallback")
    else:
        style = get_style_from_janus(args.image, book_info, target="back")

    style_tags = parse_janus_to_tags(style)

    # 3. 封底 prompt
    back_prompt = (
        f"{style_tags}, "
        f"seamless book cover background extension, "
        f"open sky and landscape, no characters, no text, no logos, "
        f"lower half plain and open for text, "
        f"same art style and color temperature as reference image"
    )
    print(f"\n[封底Prompt] {back_prompt[:120]}...\n")

    # 4. 生成封底
    print("[FLUX] 开始生成封底...")
    canvas_b, mask_b, total_w, total_h = build_back_canvas(cover, page_w, page_h)
    t0      = time.time()
    raw     = flux_generate(canvas_b, mask_b, back_prompt, seed, args.steps)
    print(f"[FLUX] 封底生成完成，耗时 {time.time()-t0:.1f}s")
    result   = resize_to(raw, total_w, total_h)
    back_raw = result.crop((0, 0, page_w, total_h))

    # 5. 封底文字合成
    if args.no_text:
        back_final = back_raw
    else:
        back_final = composite_back(back_raw, book_info)
        print("[文字] 封底文字合成完成")

    # 6. 书脊 prompt
    spine_prompt = (
        f"{style_tags}, "
        f"seamless narrow vertical spine extension of book cover left edge, "
        f"exact same background color and texture, simple continuation, no new elements"
    )
    print(f"\n[书脊Prompt] {spine_prompt[:120]}...\n")

    # 7. 生成书脊
    print(f"[FLUX] 开始生成书脊（生成宽={spine_px_gen}px）...")
    spine_canvas_b, spine_mask_b, spine_tw, spine_th = build_spine_canvas(
        cover, spine_px_gen, page_h
    )
    t0 = time.time()
    spine_raw_bytes = flux_generate(spine_canvas_b, spine_mask_b, spine_prompt, seed + 1000, args.steps)
    print(f"[FLUX] 书脊生成完成，耗时 {time.time()-t0:.1f}s")

    spine_result = resize_to(spine_raw_bytes, spine_tw, spine_th)
    spine_gen    = spine_result.crop((0, 0, spine_px_gen, page_h))

    # 8. 书脊文字合成：在放大尺寸(spine_px_gen)上合成
    # output_spine.png 保持放大尺寸（可读），output_full_preview.png 才缩回真实宽度
    # 原版逻辑：先缩回真实尺寸，再在真实尺寸上合成文字
    if spine_px_gen != spine_px_real:
        spine_real = spine_gen.resize((spine_px_real, page_h), Image.LANCZOS)
    else:
        spine_real = spine_gen

    if args.no_text:
        spine_final = spine_real
    else:
        spine_final = composite_spine(spine_real, book_info)
        print("[文字] 书脊文字合成完成")

    # 9. 输出3张图
    back_path  = os.path.join(out_dir, "output_back.png")
    spine_path = os.path.join(out_dir, "output_spine.png")
    full_path  = os.path.join(out_dir, "output_full_preview.png")

    back_final.save(back_path)
    spine_final.save(spine_path)

    full_w   = page_w + spine_px_real + cw
    full_img = Image.new("RGB", (full_w, page_h), (200, 200, 200))
    full_img.paste(back_final,  (0, 0))
    full_img.paste(spine_final, (page_w, 0))
    full_img.paste(cover,       (page_w + spine_px_real, 0))
    d = ImageDraw.Draw(full_img)
    d.line([(page_w, 0), (page_w, page_h)],                         fill=(60,60,60), width=1)
    d.line([(page_w+spine_px_real, 0), (page_w+spine_px_real, page_h)], fill=(60,60,60), width=1)
    full_img.save(full_path)

    print(f"\n{'='*60}")
    print(f"  ✓ output_back.png          单独封底（含文字）")
    print(f"  ✓ output_spine.png         单独书脊（含文字）")
    print(f"  ✓ output_full_preview.png  封面+书脊+封底完整预览")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
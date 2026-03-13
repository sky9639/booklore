"""
FLUX Outpainting 封底+书脊测试 V1.0
存放位置：E:\AI\booklore_AI\test_flux_outpaint.py

用法：
  python test_flux_outpaint.py cover.jpg
  python test_flux_outpaint.py cover.jpg "Who Is Bill Gates" --spine-width 10 --size A5
  python test_flux_outpaint.py cover.jpg "三体" --no-janus
"""

import os, sys, argparse, textwrap, io, base64
import requests
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfyui_flux_outpaint import outpaint_cover

JANUS_URL = "http://127.0.0.1:8788"

SIZE_MAP = {"A4": (794, 1123), "A5": (559, 794), "B5": (665, 945)}

FALLBACK_STYLE = (
    "seamless extension of book cover art, "
    "same color palette and illustration style, "
    "atmospheric background, professional book design"
)

# ──────────────────────────────────────────
# 书籍信息
# ──────────────────────────────────────────


# 测试用内置书籍数据（网络不通或搜不到时自动使用）
BUILTIN_BOOKS = {
    "who is bill gates": {
        "title": "Who Is Bill Gates?",
        "authors": ["Patricia Brennan Demuth"],
        "description": (
            "Bill Gates, co-founder of Microsoft Corporation, is one of the most "
            "influential figures in the history of personal computing. From his early "
            "days as a programming prodigy to building a software empire, this is the "
            "remarkable story of a visionary who changed the world."
        ),
        "categories": ["Biography", "Technology", "History"],
        "found": True,
    },
    "三体": {
        "title": "三体",
        "authors": ["刘慈欣"],
        "description": (
            "文化大革命期间，一个秘密军事项目向宇宙发出了地球文明存在的信号。"
            "四光年外，一个濒临灭亡的外星文明接收到这个信号，决定入侵地球。"
            "这是一场关乎人类命运的史诗级对决。"
        ),
        "categories": ["Science Fiction", "Chinese Literature"],
        "found": True,
    },
}


def fetch_book_info(title):
    if not title:
        return {"title": "", "authors": [], "description": "", "categories": [], "found": False}

    # 先查内置数据
    key = title.strip().lower()
    for builtin_key, builtin_data in BUILTIN_BOOKS.items():
        if builtin_key in key or key in builtin_key:
            print(f"[书籍信息] 使用内置数据: {builtin_data['title']}")
            return builtin_data

    strategies = list(dict.fromkeys(filter(None, [
        title,
        title.split(":")[0].strip(),
        title.split("·")[0].strip(),
        " ".join(title.split()[:3]),
    ])))

    for i, query in enumerate(strategies):
        try:
            print(f"[Open Library] 搜索({i+1}): {query}")
            resp = requests.get(
                "https://openlibrary.org/search.json",
                params={"title": query, "limit": 3,
                        "fields": "title,author_name,first_sentence,subject"},
                timeout=10,
                headers={"User-Agent": "Booklore/2.0"},
            )
            docs = resp.json().get("docs", [])
            if not docs:
                continue
            doc = docs[0]
            authors = doc.get("author_name", [])
            categories = (doc.get("subject") or [])[:5]
            description = ""
            fs = doc.get("first_sentence")
            if fs:
                description = fs if isinstance(fs, str) else fs.get("value", "")
            if not description and categories:
                description = f"A compelling story exploring {', '.join(categories[:3])}."
            print(f"[Open Library] ✓ {doc.get('title', title)}")
            return {"title": doc.get("title", title), "authors": authors,
                    "description": description, "categories": categories, "found": True}
        except Exception as e:
            print(f"[Open Library] 失败: {e}")

    # 网络失败降级：至少保留书名
    print(f"[书籍信息] 网络不通，使用书名: {title}")
    return {"title": title, "authors": [], "description": "", "categories": [], "found": False}



# ──────────────────────────────────────────
# Janus 分析
# ──────────────────────────────────────────

def get_style(image_path, book_info):
    try:
        requests.get(f"{JANUS_URL}/health", timeout=4).raise_for_status()
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(f"{JANUS_URL}/analyze", json={
            "image_base64": b64,
            "book_title":  book_info.get("title", ""),
            "authors":     book_info.get("authors", []),
            "categories":  book_info.get("categories", []),
            "description": book_info.get("description", ""),
            "target": "back",
        }, timeout=60)
        style = resp.json().get("prompt", "")
        if style:
            print(f"[Janus] ✓ {style[:100]}...")
            return style
    except Exception as e:
        print(f"[Janus] 不可用: {e}")
    return FALLBACK_STYLE


# ──────────────────────────────────────────
# 构建 FLUX Outpaint prompt
# ──────────────────────────────────────────

def build_outpaint_prompt(style, book_info, target="back"):
    genre = ", ".join(book_info.get("categories", [])[:2])

    if target == "spine":
        prompt = (
            f"{style}. "
            f"Seamlessly extend the book cover edge to the left as a narrow spine strip. "
            f"{''+genre+' style, ' if genre else ''}"
            f"Exact same background color, texture and pattern as the cover left edge. "
            f"Simple vertical continuation, no new elements, seamless transition."
        )
    else:
        prompt = (
            f"{style}. "
            f"Seamlessly extend the book cover scene to the left as a back cover. "
            f"{''+genre+' style, ' if genre else ''}"
            f"Continue the background scene and atmosphere from the cover. "
            f"Lower half should be calm and relatively plain for text placement. "
            f"Maintain exact same art style, lighting, color temperature. "
            f"No characters in center, no title text, natural continuation."
        )
    return prompt


def composite_spine(spine_img: Image.Image, book_info: dict) -> Image.Image:
    """
    在书脊图上叠加竖排书名和作者。
    做法：在旋转后的宽图上写文字，再旋转回来裁切。
    """
    sw, sh = spine_img.size
    # 如果书脊太窄（<20px），跳过文字，直接返回
    if sw < 20:
        return spine_img

    # 旋转90度，变成横向写文字再转回来
    rotated = spine_img.rotate(-90, expand=True)  # 现在是 sh × sw
    rw, rh = rotated.size   # rw=sh(高), rh=sw(宽)

    draw = ImageDraw.Draw(rotated)

    # 字号根据书脊宽度（旋转后的高度 rh）决定
    font_size  = max(10, int(rh * 0.55))
    font_small = max(8,  int(rh * 0.38))

    title   = book_info.get("title") or ""
    authors = book_info.get("authors", [])
    author_str = ("  " + ", ".join(authors[:2])) if authors else ""

    font_t = load_font(font_size, bold=True)
    font_a = load_font(font_small)

    # 自动缩小书名直到适合宽度（留 5% padding）
    max_text_w = int(rw * 0.90)
    while font_size > 8:
        bbox = draw.textbbox((0, 0), title, font=font_t)
        if bbox[2] - bbox[0] <= max_text_w:
            break
        font_size -= 1
        font_t = load_font(font_size, bold=True)

    # 书名居中
    bbox_t = draw.textbbox((0, 0), title, font=font_t)
    tw = bbox_t[2] - bbox_t[0]
    tx = max(0, (rw - tw) // 2)
    ty = int(rh * 0.08)

    # 半透明背景条
    overlay = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([(0, ty - 4), (rw, ty + (bbox_t[3] - bbox_t[1]) + 4)],
                 fill=(0, 0, 0, 100))
    rotated = Image.alpha_composite(rotated.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(rotated)

    draw.text((tx, ty), title, font=font_t, fill=(255, 255, 255))

    # 作者（如果书脊够宽）
    if author_str and sw >= 30:
        bbox_a = draw.textbbox((0, 0), author_str, font=font_a)
        aw = bbox_a[2] - bbox_a[0]
        ax = max(0, (rw - aw) // 2)
        ay = ty + (bbox_t[3] - bbox_t[1]) + int(rh * 0.06)
        if ay + (bbox_a[3] - bbox_a[1]) < rh * 0.95:
            draw.text((ax, ay), author_str, font=font_a, fill=(220, 220, 220))

    # 转回竖向
    result = rotated.rotate(90, expand=True)
    return result


def _img_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ──────────────────────────────────────────
# 文字合成（封底）
# ──────────────────────────────────────────

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/arial.ttf"),
    ("C:/Windows/Fonts/msyhbd.ttc",   "C:/Windows/Fonts/msyh.ttc"),
    ("C:/Windows/Fonts/simsunb.ttf",  "C:/Windows/Fonts/simsun.ttc"),
]

def load_font(size, bold=False):
    for bold_p, norm_p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(bold_p if bold else norm_p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_text_shadowed(draw, pos, text, font, fill=(255,255,255), shadow=(0,0,0), offset=2):
    """文字带多方向阴影，不需要背景框也清晰可读。"""
    x, y = pos
    for dx in (-offset, 0, offset):
        for dy in (-offset, 0, offset):
            if dx == 0 and dy == 0:
                continue
            draw.text((x+dx, y+dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def make_gradient_overlay(size, start_ratio=0.40):
    """从透明到半透明黑色的垂直渐变，让文字区域自然变暗融入背景。"""
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    start_y = int(h * start_ratio)
    pixels = overlay.load()
    for y in range(start_y, h):
        progress = (y - start_y) / (h - start_y)
        alpha = int(185 * (progress ** 1.4))   # 缓动曲线，过渡自然
        for x in range(w):
            pixels[x, y] = (0, 0, 0, alpha)
    return overlay


def composite_back(img_bytes, book_info):
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    w, h = img.size

    # 1. 渐变暗色遮罩 — 完全融入背景，无任何硬边
    gradient = make_gradient_overlay((w, h), start_ratio=0.40)
    img = Image.alpha_composite(img, gradient).convert("RGB")
    draw = ImageDraw.Draw(img)

    mx     = int(w * 0.08)
    mr     = w - int(w * 0.08)
    max_tw = mr - mx
    y      = int(h * 0.50)

    # 2. 书名 — 白色粗体 + 黑色阴影
    title = book_info.get("title") or "Unknown Title"
    size  = int(w * 0.070)
    font  = load_font(size, bold=True)
    while size > int(w * 0.026):
        if draw.textbbox((0,0), title, font=font)[2] <= max_tw:
            break
        size -= 2
        font = load_font(size, bold=True)
    draw_text_shadowed(draw, (mx, y), title, font,
                       fill=(255, 255, 255), shadow=(0,0,0), offset=2)
    y += draw.textbbox((0,0), title, font=font)[3] + int(h * 0.016)

    # 3. 作者 — 暖金色细字
    authors = book_info.get("authors", [])
    if authors:
        a_str  = "by " + ", ".join(authors[:3])
        font_a = load_font(int(w * 0.029))
        draw_text_shadowed(draw, (mx, y), a_str, font_a,
                           fill=(255, 225, 130), shadow=(0,0,0), offset=1)
        y += draw.textbbox((0,0), a_str, font=font_a)[3] + int(h * 0.018)

    # 4. 虚线分隔（点状，比实线轻盈）
    dash, gap, lx = 16, 7, mx
    while lx < mr - dash:
        draw.line([(lx, y+2), (lx+dash, y+2)], fill=(180, 180, 180), width=1)
        lx += dash + gap
    y += int(h * 0.026)

    # 5. 简介 — 浅灰白小字
    desc = (book_info.get("description") or
            "A captivating story that will keep you turning pages.")
    font_b   = load_font(int(w * 0.025))
    avg_cw   = max(1, int(w * 0.025 * 0.55))
    max_char = max(20, max_tw // avg_cw)
    line_h   = int(h * 0.033)
    for line in textwrap.fill(desc, width=max_char).split("\n"):
        if y + line_h > int(h * 0.95):
            draw_text_shadowed(draw, (mx, y), "…", font_b,
                               fill=(190,190,190), shadow=(0,0,0), offset=1)
            break
        draw_text_shadowed(draw, (mx, y), line, font_b,
                           fill=(225, 225, 225), shadow=(0,0,0), offset=1)
        y += line_h

    return img


# ──────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("title", nargs="?", default="")
    parser.add_argument("--spine-width", type=float, default=10.0, help="书脊宽度mm")
    parser.add_argument("--size", choices=["A4","A5","B5"], default="A5")
    parser.add_argument("--no-janus", action="store_true")
    parser.add_argument("--steps", type=int, default=20, help="FLUX采样步数")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"[错误] 找不到: {args.image}"); sys.exit(1)

    page_w, page_h = SIZE_MAP[args.size]
    # 书脊像素（150DPI 预览分辨率）
    # 真实书脊像素（用于最终裁切和文字合成）
    spine_px_real = max(1, int(args.spine_width * page_h / 210))
    # FLUX 生成时使用的书脊像素（放大到至少 150px，保证生成质量）
    SPINE_GEN_MIN = 150
    spine_px_gen  = max(SPINE_GEN_MIN, spine_px_real)
    spine_px = spine_px_gen   # 传给 outpaint_cover 的是生成尺寸

    print("=" * 60)
    print(f"  FLUX Outpainting 封底+书脊测试")
    print(f"  尺寸: {args.size} ({page_w}x{page_h}px)")
    print(f"  书脊: {args.spine_width}mm (真实 {spine_px_real}px，生成用 {spine_px_gen}px 后裁切)")
    print(f"  FLUX steps: {args.steps}")
    print("=" * 60)

    # 1. 书籍信息
    book_info = fetch_book_info(args.title)

    # 2. 风格分析
    style = FALLBACK_STYLE if args.no_janus else get_style(args.image, book_info)

    # 3. 构建 prompt（封底和书脊用不同 prompt）
    prompt_back  = build_outpaint_prompt(style, book_info, target="back")
    prompt_spine = build_outpaint_prompt(style, book_info, target="spine")
    print(f"\n[Prompt Back]  {prompt_back[:120]}...")
    print(f"[Prompt Spine] {prompt_spine[:120]}...\n")

    # 4. 两步 FLUX Outpainting
    try:
        back_img, spine_img, cover_img = outpaint_cover(
            cover_path     = args.image,
            prompt_back    = prompt_back,
            prompt_spine   = prompt_spine,
            back_width_px  = page_w,
            spine_width_px = spine_px_gen,
            page_height_px = page_h,
            steps          = args.steps,
        )
    except Exception as e:
        print(f"[错误] Outpainting 失败: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    fh = page_h

    # ── 封底叠加文字 ──
    back_with_text = composite_back(_img_to_bytes(back_img), book_info)

    # ── 书脊叠加竖排文字（在真实宽度上处理） ──
    spine_real      = spine_img.resize((spine_px_real, fh), Image.LANCZOS)
    spine_with_text = composite_spine(spine_real, book_info)

    # ── 拼接：[封底] + [书脊(真实宽)] + [封面] ──
    cover_w = cover_img.width
    total_w = page_w + spine_px_real + cover_w
    spread  = Image.new("RGB", (total_w, fh), (255, 255, 255))

    spread.paste(back_with_text,  (0,                         0))
    spread.paste(spine_with_text, (page_w,                    0))
    spread.paste(cover_img,       (page_w + spine_px_real,    0))

    # 分隔线
    d = ImageDraw.Draw(spread)
    d.line([(page_w,                 0), (page_w,                 fh)], fill=(160,160,160), width=1)
    d.line([(page_w + spine_px_real, 0), (page_w + spine_px_real, fh)], fill=(160,160,160), width=1)

    # ── 保存 ──
    spread_path = os.path.join(out_dir, "cover_spread.png")
    spread.save(spread_path)

    print(f"\n[拼接] 封底({page_w}px) + 书脊({spine_px_real}px) + 封面({cover_w}px) = {total_w}x{fh}px")
    print("\n" + "=" * 60)
    print(f"  ✓ cover_spread.png    完整展开图 {fw}x{fh}px")
    print(f"  ✓ debug_back.png      封底单图   {back_w}x{fh}px")
    print(f"  ✓ debug_spine.png     书脊单图   {spine_px_real}x{fh}px (真实宽度)")
    print(f"  ✓ debug_flux_raw.png  FLUX原始图 (无文字)")
    print("=" * 60)

if __name__ == "__main__":
    main()

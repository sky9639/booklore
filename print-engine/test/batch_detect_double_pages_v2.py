#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF双页批量检测工具 v2 - 基于宽高比主判据 + 中缝亮度辅助判据

规则：
1. 宽高比 < 1.30：直接判定为单页
2. 宽高比 >= 1.30 且中间亮度比 >= 1.15：判定为双页
3. 宽高比 >= 1.34：即使没有明显中缝，也判定为双页（适配纯色跨页图）

输出：
- 导出检测到的双页图片
- 生成 txt 报告
- 控制台打印逐页判断依据

使用方法：
    python batch_detect_double_pages_v2.py "your.pdf"
    python batch_detect_double_pages_v2.py "your.pdf" "output_dir"
"""

import io
import os
import sys
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import numpy as np
from PIL import Image


ASPECT_RATIO_MIN = 1.30
ASPECT_RATIO_STRONG = 1.34
CENTER_WIDTH_RATIO = 0.10
BRIGHTNESS_THRESHOLD = 1.15
RENDER_DPI = 144


def detect_center_gutter(image: Image.Image,
                         center_width_ratio: float = CENTER_WIDTH_RATIO,
                         brightness_threshold: float = BRIGHTNESS_THRESHOLD) -> Dict:
    """检测中间区域是否明显比两侧更亮。"""
    gray = image.convert("L")
    img_array = np.array(gray)

    height, width = img_array.shape

    center_start = int(width * (0.5 - center_width_ratio / 2))
    center_end = int(width * (0.5 + center_width_ratio / 2))
    left_end = int(width * 0.3)
    right_start = int(width * 0.7)

    center_region = img_array[:, center_start:center_end]
    left_region = img_array[:, :left_end]
    right_region = img_array[:, right_start:]

    center_brightness = float(np.mean(center_region))
    left_brightness = float(np.mean(left_region))
    right_brightness = float(np.mean(right_region))
    side_brightness = (left_brightness + right_brightness) / 2
    brightness_ratio = center_brightness / side_brightness if side_brightness > 0 else 1.0

    if brightness_ratio >= 1.30:
        confidence = "高"
    elif brightness_ratio >= brightness_threshold:
        confidence = "中"
    elif brightness_ratio >= 1.05:
        confidence = "低"
    else:
        confidence = "无"

    return {
        "center_brightness": center_brightness,
        "left_brightness": left_brightness,
        "right_brightness": right_brightness,
        "side_brightness": side_brightness,
        "brightness_ratio": brightness_ratio,
        "has_center_gutter": brightness_ratio >= brightness_threshold,
        "gutter_confidence": confidence,
    }



def get_main_image_from_page(doc: fitz.Document, page: fitz.Page) -> Tuple[Image.Image, str]:
    """优先提取页面主图；没有嵌入图时，回退为整页渲染。"""
    images = page.get_images(full=True)

    main_image: Optional[Image.Image] = None
    max_area = 0

    for img in images:
        xref = img[0]
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            width, height = pil_img.size
            area = width * height

            if area > max_area:
                max_area = area
                main_image = pil_img
        except Exception:
            continue

    if main_image is not None:
        return main_image, "embedded_image"

    pix = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
    rendered = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    return rendered, "rendered_page"



def classify_page(image: Image.Image) -> Dict:
    """按 v2 规则分类页面。"""
    width, height = image.size
    aspect_ratio = width / height if height else 0
    gutter = detect_center_gutter(image)
    brightness_ratio = gutter["brightness_ratio"]

    reasons: List[str] = []
    decision = "single"
    confidence = "高"

    if aspect_ratio < ASPECT_RATIO_MIN:
        decision = "single"
        confidence = "高"
        reasons.append(f"宽高比 {aspect_ratio:.3f} < {ASPECT_RATIO_MIN:.2f}，判定为单页")
    else:
        reasons.append(f"宽高比 {aspect_ratio:.3f} >= {ASPECT_RATIO_MIN:.2f}，进入双页候选")

        if brightness_ratio >= BRIGHTNESS_THRESHOLD:
            decision = "double"
            confidence = "高" if brightness_ratio >= 1.30 else "中"
            reasons.append(
                f"中间亮度比 {brightness_ratio:.3f} >= {BRIGHTNESS_THRESHOLD:.2f}，存在中缝特征"
            )
        elif aspect_ratio >= ASPECT_RATIO_STRONG:
            decision = "double"
            confidence = "中"
            reasons.append(
                f"中间亮度比 {brightness_ratio:.3f} < {BRIGHTNESS_THRESHOLD:.2f}，但宽高比 {aspect_ratio:.3f} >= {ASPECT_RATIO_STRONG:.2f}，按纯色/无明显中缝双页处理"
            )
        else:
            decision = "single"
            confidence = "中"
            reasons.append(
                f"中间亮度比 {brightness_ratio:.3f} < {BRIGHTNESS_THRESHOLD:.2f}，且宽高比 {aspect_ratio:.3f} < {ASPECT_RATIO_STRONG:.2f}，判定为单页"
            )

    return {
        "decision": decision,
        "confidence": confidence,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "brightness_ratio": brightness_ratio,
        "gutter_confidence": gutter["gutter_confidence"],
        "reasons": reasons,
    }



def save_report(report_path: str,
                pdf_name: str,
                total_pages: int,
                double_pages: List[Dict],
                single_pages: List[Dict]) -> None:
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("PDF双页检测报告 v2\n")
        f.write("=" * 80 + "\n")
        f.write(f"文件: {pdf_name}\n")
        f.write(f"总页数: {total_pages}\n")
        f.write(f"检测到双页: {len(double_pages)} 页\n")
        f.write(f"检测到单页: {len(single_pages)} 页\n")
        f.write("\n")
        f.write("判定规则:\n")
        f.write(f"1. 宽高比 < {ASPECT_RATIO_MIN:.2f}：单页\n")
        f.write(f"2. 宽高比 >= {ASPECT_RATIO_MIN:.2f} 且中间亮度比 >= {BRIGHTNESS_THRESHOLD:.2f}：双页\n")
        f.write(f"3. 宽高比 >= {ASPECT_RATIO_STRONG:.2f}：即使中间亮度不足，也按双页处理\n")
        f.write("\n")

        if double_pages:
            f.write("双页页码:\n")
            f.write("  " + ", ".join(str(item["page_num"]) for item in double_pages) + "\n\n")

            f.write("双页详细列表:\n")
            for item in double_pages:
                f.write(
                    f"- 第 {item['page_num']} 页 | 尺寸 {item['width']}x{item['height']} | "
                    f"宽高比 {item['aspect_ratio']:.3f} | 中间亮度比 {item['brightness_ratio']:.3f} | "
                    f"置信度 {item['confidence']} | 来源 {item['source_type']}\n"
                )
                for reason in item["reasons"]:
                    f.write(f"    判断依据: {reason}\n")
                if item.get("output_path"):
                    f.write(f"    导出图片: {item['output_path']}\n")
                f.write("\n")

        if single_pages:
            f.write("单页摘要:\n")
            for item in single_pages:
                f.write(
                    f"- 第 {item['page_num']} 页 | 尺寸 {item['width']}x{item['height']} | "
                    f"宽高比 {item['aspect_ratio']:.3f} | 中间亮度比 {item['brightness_ratio']:.3f} | "
                    f"置信度 {item['confidence']}\n"
                )



def batch_detect_pdf(pdf_path: str, output_dir: Optional[str] = None):
    if not os.path.exists(pdf_path):
        print(f"❌ 文件不存在: {pdf_path}")
        return [], []

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(pdf_path), f"{base_name}_double_detect_v2")
    os.makedirs(output_dir, exist_ok=True)

    images_dir = os.path.join(output_dir, "double_pages")
    os.makedirs(images_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    double_pages: List[Dict] = []
    single_pages: List[Dict] = []

    print(f"📄 PDF文件: {os.path.basename(pdf_path)}")
    print(f"📊 总页数: {total_pages}")
    print("=" * 80)

    for page_index in range(total_pages):
        page = doc[page_index]
        page_num = page_index + 1

        try:
            image, source_type = get_main_image_from_page(doc, page)
            result = classify_page(image)

            page_data = {
                "page_num": page_num,
                "source_type": source_type,
                **result,
            }

            if result["decision"] == "double":
                output_path = os.path.join(images_dir, f"{base_name}_page{page_num}_double.jpg")
                image.save(output_path, quality=95)
                page_data["output_path"] = output_path
                double_pages.append(page_data)

                print(
                    f"✂️  第 {page_num}/{total_pages} 页 -> 双页 | "
                    f"宽高比 {result['aspect_ratio']:.3f} | "
                    f"亮度比 {result['brightness_ratio']:.3f} | "
                    f"依据: {'；'.join(result['reasons'])}"
                )
            else:
                single_pages.append(page_data)
                print(
                    f"✓  第 {page_num}/{total_pages} 页 -> 单页 | "
                    f"宽高比 {result['aspect_ratio']:.3f} | "
                    f"亮度比 {result['brightness_ratio']:.3f} | "
                    f"依据: {'；'.join(result['reasons'])}"
                )
        except Exception as e:
            print(f"⚠️  第 {page_num}/{total_pages} 页检测失败: {e}")

    doc.close()

    report_path = os.path.join(output_dir, f"{base_name}_report_v2.txt")
    save_report(report_path, os.path.basename(pdf_path), total_pages, double_pages, single_pages)

    print("\n" + "=" * 80)
    print("📊 检测汇总")
    print("=" * 80)
    print(f"总页数: {total_pages}")
    print(f"双页: {len(double_pages)} 页")
    print(f"单页: {len(single_pages)} 页")
    if double_pages:
        print("双页页码: " + ", ".join(str(item["page_num"]) for item in double_pages))
    else:
        print("双页页码: 无")
    print(f"双页图片目录: {images_dir}")
    print(f"报告文件: {report_path}")

    return double_pages, single_pages


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python batch_detect_double_pages_v2.py <pdf_path> [output_dir]")
        sys.exit(1)

    input_pdf = sys.argv[1]
    input_output_dir = sys.argv[2] if len(sys.argv) >= 3 else None
    batch_detect_pdf(input_pdf, input_output_dir)

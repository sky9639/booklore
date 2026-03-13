"""
============================================================
Booklore Janus Vision API  V1.1
存放位置：E:\AI\booklore_AI\janus_api.py

职责：
  接收封面图 + 书籍元数据
  → 用 Janus-Pro-7B 分析封面风格
  → 返回适合 ComfyUI SDXL + IP-Adapter 使用的英文 prompt

运行方式：双击 启动Janus_API.bat
端口：8788
============================================================
"""

import base64
import io
import os
import traceback

import torch
from flask import Flask, jsonify, request
from PIL import Image
from transformers import AutoModelForCausalLM

# ==============================
# 配置
# ==============================

MODEL_PATH = os.environ.get(
    "JANUS_MODEL_PATH",
    r"E:\AI\ComfyUI_windows_portable_nvidia_cu128\ComfyUI\models\deepseek\Janus-Pro-7B"  # 模型在ComfyUI目录，脚本在booklore_AI
)
PORT = int(os.environ.get("JANUS_PORT", 8788))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

print(f"[Janus API] Loading model from: {MODEL_PATH}")
print(f"[Janus API] Device: {DEVICE}")

# ==============================
# 加载模型
# ==============================

from janus.models import MultiModalityCausalLM, VLChatProcessor

processor: VLChatProcessor = VLChatProcessor.from_pretrained(MODEL_PATH)
tokenizer = processor.tokenizer

# RTX 5090 32GB：直接 bfloat16 加载，全程只占 ~14GB
model: MultiModalityCausalLM = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
    low_cpu_mem_usage=True,
).to(DEVICE).eval()

print(f"[Janus API] Model loaded on {DEVICE} | bfloat16 | ~14GB VRAM")
print("[Janus API] Model loaded successfully!")

# ==============================
# Flask App
# ==============================

app = Flask(__name__)


def analyze_cover(
    image: Image.Image,
    book_title: str,
    authors: list[str],
    categories: list[str],
    description: str,
    target: str,
) -> str:
    authors_str = ", ".join(authors) if authors else "Unknown"
    categories_str = ", ".join(categories) if categories else ""

    if target == "spine":
        target_desc = (
            f"a narrow vertical book spine strip that seamlessly continues "
            f"from the right edge of this front cover. "
            f"The spine will contain the title '{book_title}' and author '{authors_str}' "
            f"printed vertically."
        )
    else:
        target_desc = (
            f"a book back cover that seamlessly extends leftward from this front cover. "
            f"It should mirror the visual world of the cover, with a clean text area "
            f"in the center for synopsis text."
        )

    conversation = [
        {
            "role": "<|User|>",
            "content": (
                f"<image_placeholder>\n"
                f"This is the front cover of a book.\n"
                f"Title: {book_title}\n"
                f"Author: {authors_str}\n"
                f"Genre: {categories_str}\n"
                f"Description: {(description or '')[:300]}\n\n"
                f"Study this cover image carefully and extract:\n"
                f"1. Art style (e.g. watercolor, photorealistic, flat illustration, oil painting)\n"
                f"2. Color palette (dominant colors, warm/cool tones)\n"
                f"3. Mood and atmosphere (e.g. cozy, mysterious, dramatic, playful)\n"
                f"4. Lighting style (e.g. soft diffused, dramatic shadows, golden hour)\n"
                f"5. Key visual textures and elements\n\n"
                f"Then write a ComfyUI image generation prompt (comma-separated tags, "
                f"English only, no sentences, no explanations) for: {target_desc}\n\n"
                f"The prompt must ensure perfect visual continuity with the front cover. "
                f"Start directly with the style tags."
            ),
            "images": [image],
        },
        {
            "role": "<|Assistant|>",
            # 强引导前缀：让 Janus 直接续写 tag 格式的 prompt，而非自然语言描述
            "content": "Prompt:\n",
        },
    ]

    prepare_inputs = processor(
        conversations=conversation,
        images=[image],
        force_batchify=True,
    ).to(next(model.parameters()).device)

    inputs_embeds = model.prepare_inputs_embeds(**prepare_inputs)

    outputs = model.language_model.generate(
        inputs_embeds=inputs_embeds,
        attention_mask=prepare_inputs.attention_mask,
        pad_token_id=tokenizer.eos_token_id,
        bos_token_id=tokenizer.bos_token_id,
        eos_token_id=tokenizer.eos_token_id,
        max_new_tokens=300,   # prompt 不需要太长，300 够了
        do_sample=True,
        temperature=0.4,      # 降低随机性，让 prompt 更稳定精准
        top_p=0.9,
        use_cache=True,
    )

    answer = tokenizer.decode(outputs[0].cpu().tolist(), skip_special_tokens=True)

    # 截取 "Prompt:\n" 之后的内容，去掉前缀和多余的自然语言
    if "Prompt:" in answer:
        answer = answer.split("Prompt:", 1)[-1].strip()

    # 如果仍然有多余换行段落，只取第一段（tag 行）
    first_para = answer.split("\n\n")[0].strip()
    if len(first_para) > 30:
        answer = first_para

    return answer.strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "device": DEVICE, "model": MODEL_PATH})


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        image_b64 = data.get("image_base64")
        if not image_b64:
            return jsonify({"error": "image_base64 is required"}), 400

        target = data.get("target", "back")
        if target not in ("spine", "back"):
            return jsonify({"error": "target must be 'spine' or 'back'"}), 400

        img_bytes = base64.b64decode(image_b64)
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        prompt = analyze_cover(
            image=image,
            book_title=data.get("book_title", ""),
            authors=data.get("authors", []),
            categories=data.get("categories", []),
            description=data.get("description", ""),
            target=target,
        )

        print(f"[Janus API] Generated prompt for {target}: {prompt[:100]}...")
        return jsonify({"prompt": prompt, "target": target})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print(f"[Janus API] Starting on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT, debug=False)
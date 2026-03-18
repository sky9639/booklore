#!/usr/bin/env python3
"""
claude_analyzer.py - Claude API 封面风格分析模块
版本: V2.0 (从 E:\AI\booklore_AI_Service 迁移)

功能:
- 使用 Claude Sonnet 4.6 分析封面风格
- 生成封底和书脊的 Prompt
- 推荐 IP-Adapter 权重和生成步数
- 支持缓存机制减少 API 调用

优化:
- 图片自动缩放到 800px 降低 Token 消耗
- 精简 Prompt 文本
- 限制输出长度到 512 tokens
"""

import base64
import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

import anthropic
from PIL import Image

logger = logging.getLogger(__name__)


class ClaudeAnalyzer:
    """Claude API 封面分析器"""

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.anthropic.com",
        model: str = "claude-sonnet-4-6",
        cache_dir: Optional[str] = None,
        cache_ttl: int = 3600,
    ):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = cache_ttl

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Claude] 缓存已启用: {self.cache_dir} (TTL: {cache_ttl}s)")

        self.client = anthropic.Anthropic(api_key=api_key, base_url=api_url)

    def _generate_cache_key(self, cover_bytes: bytes, book_info: Dict) -> str:
        """生成缓存键"""
        img_hash = hashlib.md5(cover_bytes).hexdigest()
        key_data = {
            "image_hash": img_hash,
            "title": book_info.get("title", ""),
            "categories": sorted(book_info.get("categories", [])),
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache(self, cache_key: str) -> Optional[Dict]:
        """从缓存读取"""
        if not self.cache_dir:
            return None

        cache_file = self.cache_dir / f"{cache_key}.json"
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) > self.cache_ttl:
                cache_file.unlink()
                return None
            logger.info(f"[Claude] 缓存命中: {cache_key[:8]}")
            return data.get("result")
        except Exception as e:
            logger.warning(f"[Claude] 缓存读取失败: {e}")
            return None

    def _set_cache(self, cache_key: str, result: Dict):
        """写入缓存"""
        if not self.cache_dir:
            return

        try:
            cache_file = self.cache_dir / f"{cache_key}.json"
            data = {"timestamp": time.time(), "result": result}
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[Claude] 缓存写入失败: {e}")

    def analyze_cover(
        self, cover_image_bytes: bytes, book_info: Dict, request_id: str = "", target: str = "back"
    ) -> Dict:
        """
        分析封面并生成 Prompt

        Args:
            cover_image_bytes: 封面图片字节
            book_info: 书籍信息 {"title": str, "categories": list, ...}
            request_id: 请求 ID (用于日志追踪)

        Returns:
            {
                "style_analysis": str,
                "back_cover_prompt": str,
                "spine_prompt": str,
                "ipadapter_weight": float,
                "recommended_steps": int
            }
        """
        # 缓存已禁用 - 每次都重新分析以获得不同效果
        # cache_key = self._generate_cache_key(cover_image_bytes, book_info)
        # cached = self._get_cache(cache_key)
        # if cached:
        #     logger.info(f"[{request_id}] 使用缓存的分析结果")
        #     return cached

        try:
            # 图片预处理: 缩放到 800px 降低 Token 消耗
            img = Image.open(io.BytesIO(cover_image_bytes))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            max_size = 800
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # 转换为 JPEG 压缩
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            optimized_bytes = buf.getvalue()
            cover_b64 = base64.b64encode(optimized_bytes).decode("utf-8")

            logger.info(
                f"[{request_id}] 图片优化: {len(cover_image_bytes)/1024:.1f}KB -> {len(optimized_bytes)/1024:.1f}KB"
            )

            # 优化版 Prompt（System + User 分离）
            title = book_info.get("title", "Unknown")
            categories = ", ".join(book_info.get("categories", []))

            # 获取 target 参数（从函数签名传入，默认 "back"）
            target = book_info.get("target", "back")

            # System Prompt（根据target区分）
            if target == "spine":
                system_prompt = """你是一个专业的儿童绘本封面分析专家。你的任务是分析封面图片的视觉风格，并生成用于 AI 图像生成的 Prompt。

🔴 关键要求：必须准确描述封面左边缘实际存在的具体视觉图案！

重点关注：
1. **具体图案** - 仔细观察封面左边缘，描述你看到的实际图案、纹理、装饰元素
2. 封面左边缘的色彩和纹理
3. 背景的延续性
4. 整体风格的一致性

要求：
- 描述必须具体、准确，基于实际观察
- 避免使用泛泛的词汇如"decorative elements"
- 用英文准确命名你看到的图案

输出格式（JSON）：
{
  "style_prompt": "详细的风格描述 Prompt，用于生成书脊。必须包含你观察到的具体图案描述，完全延续封面左边缘的色彩和纹理，简单垂直延续，无新元素",
  "negative_prompt": "负面 Prompt",
  "analysis": "简要分析"
}"""
            else:  # back
                system_prompt = """你是一个专业的儿童绘本封面分析专家。你的任务是分析封面图片的视觉风格，并生成用于 AI 图像生成的 Prompt。

🔴 关键要求：必须准确描述封面上实际存在的具体视觉图案！

重点关注：
1. **具体图案** - 仔细观察封面，描述你看到的实际图案、纹理、装饰元素
2. 艺术风格 - 基于实际观察判断
3. 色彩方案 - 描述实际的主色调、配色、饱和度
4. 光影效果 - 描述实际的光源方向、明暗对比
5. 纹理质感 - 描述实际的笔触、材质
6. **文字风格** - 仔细观察封面上的标题和作者文字（如果有）：
   - 标题文字的颜色（用英文颜色词描述，如white, golden, red, blue等）
   - 标题文字的风格特征（如bold粗体, elegant优雅, playful活泼, serif衬线, sans-serif无衬线等）
   - 是否有描边效果（outline）、阴影效果（shadow）、发光效果���glow）
   - 作者文字的颜色和风格
   - 如果封面没有明显的文字，返回null

要求：
- 描述必须具体、准确，基于实际观察
- 避免使用泛泛的词汇如"decorative elements"
- 用英文准确命名你看到的图案

输出格式（JSON）：
{
  "style_prompt": "详细的风格描述 Prompt，用于生成封底。必须包含你观察到的具体图案描述，延续封面风格，下半部分留白适合放文字，无人物",
  "negative_prompt": "负面 Prompt",
  "analysis": "简要分析",
  "text_style": {
    "title_color": "颜色描述或null",
    "title_style": "风格描述或null",
    "title_effects": "效果描述（如has shadow, has outline）或null",
    "author_color": "颜色描述或null",
    "author_style": "风格描述或null",
    "description_color": "建议的简介文字颜色（基于整体配色）",
    "description_style": "建议的简介文字风格"
  }
}"""

            # User Prompt
            if target == "spine":
                user_prompt = f"""请分析这张封面图片，生成用于 AI 生成书脊的 Prompt。

书名: {title}

要求：
1. Prompt 必须用英文
2. 🔴 仔细观察封面左边缘，准确描述你看到的实际视觉图案
3. 书脊是窄条形，强调边缘的无缝延续
4. 避免描述具体内容（人物、物体），只描述风格和图案

请以 JSON 格式输出。"""
            else:  # back
                user_prompt = f"""请分析这张封面图片，生成用于 AI 生成封底的 Prompt。

书名: {title}

要求：
1. Prompt 必须用英文
2. 🔴 仔细观察封面，准确描述你看到的实际视觉图案
3. 详细描述视觉风格特征
4. 强调色彩、光影、纹理的连续性
5. 避免描述具体内容（人物、物体），只描述风格和图案

请�� JSON 格式输出。"""

            start_time = time.time()
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,  # 从 512 提升到 1024
                system=system_prompt,  # 添加 System Prompt
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": cover_b64,
                                },
                            },
                            {"type": "text", "text": user_prompt},
                        ],
                    }
                ],
            )

            elapsed = time.time() - start_time
            usage = message.usage
            logger.info(
                f"[{request_id}] Claude API: {elapsed:.2f}s | "
                f"Input: {usage.input_tokens} tokens | "
                f"Output: {usage.output_tokens} tokens"
            )

            # 解析 JSON
            response_text = message.content[0].text.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            result = json.loads(response_text)

            # 添加 Token 统计信息到结果中
            result["token_usage"] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
            }

            logger.info(
                f"[{request_id}] 风格分析: {result.get('analysis', '')[:80]}..."
            )
            logger.info(
                f"[{request_id}] Style Prompt: {result.get('style_prompt', '')[:80]}..."
            )
            logger.info(
                f"[{request_id}] Token 消耗: {result['token_usage']['total_tokens']} "
                f"(输入: {result['token_usage']['input_tokens']}, "
                f"输出: {result['token_usage']['output_tokens']})"
            )

            # 缓存已禁用
            # self._set_cache(cache_key, result)

            return result

        except json.JSONDecodeError as e:
            logger.error(f"[{request_id}] JSON 解析失败: {e}")
            return self._get_default_analysis()
        except Exception as e:
            logger.error(f"[{request_id}] Claude API 错误: {e}", exc_info=True)
            return self._get_default_analysis()

    def _get_default_analysis(self) -> Dict:
        """返回默认分析结果"""
        return {
            "style_prompt": "seamless extension, natural continuation, open space for text, decorative elements",
            "negative_prompt": "blurry, low quality, distorted, text, watermark, signature, ugly, deformed, noisy, artifacts, jpeg artifacts, oversaturated, undersaturated",
            "analysis": "Unable to analyze, using default settings",
            "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
        }

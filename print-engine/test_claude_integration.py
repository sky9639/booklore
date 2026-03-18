#!/usr/bin/env python3
"""
test_claude_integration.py - 测试 Claude API 集成

用法:
    python test_claude_integration.py
"""

import sys
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from claude_analyzer import ClaudeAnalyzer
from PIL import Image
import io


def test_claude_analyzer():
    """测试 Claude 分析器"""
    print("=" * 60)
    print("测试 Claude API 集成")
    print("=" * 60)

    # 从环境变量读取配置
    from dotenv import load_dotenv
    import os

    load_dotenv("booklore.env")

    api_key = os.getenv("CLAUDE_API_KEY", "")
    api_url = os.getenv("CLAUDE_API_URL", "https://api.anthropic.com")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    if not api_key:
        print("❌ CLAUDE_API_KEY 未配置")
        return False

    print(f"✅ API Key: {api_key[:20]}...")
    print(f"✅ API URL: {api_url}")
    print(f"✅ Model: {model}")
    print()

    # 初始化分析器
    analyzer = ClaudeAnalyzer(
        api_key=api_key,
        api_url=api_url,
        model=model,
        cache_dir="./cache",
        cache_ttl=3600,
    )

    print("✅ Claude 分析器已初始化")
    print()

    # 创建测试图片（纯色图片）
    test_img = Image.new("RGB", (800, 1200), color=(100, 150, 200))
    buf = io.BytesIO()
    test_img.save(buf, "PNG")
    test_bytes = buf.getvalue()

    print(f"✅ 测试图片已创建: {len(test_bytes)} bytes")
    print()

    # 测试分析
    book_info = {
        "title": "Test Book",
        "categories": ["children's book", "fantasy"],
    }

    print("🔄 调用 Claude API 分析封面...")
    try:
        result = analyzer.analyze_cover(test_bytes, book_info, "TEST-001")
        print()
        print("✅ 分析成功！")
        print()
        print("分析结果:")
        print(f"  风格分析: {result.get('style_analysis', '')[:80]}...")
        print(f"  封底 Prompt: {result.get('back_cover_prompt', '')[:80]}...")
        print(f"  书脊 Prompt: {result.get('spine_prompt', '')[:80]}...")
        print(f"  IP-Adapter 权重: {result.get('ipadapter_weight', 0.85)}")
        print(f"  推荐步数: {result.get('recommended_steps', 20)}")
        print()

        # 测试缓存
        print("🔄 测试缓存机制...")
        result2 = analyzer.analyze_cover(test_bytes, book_info, "TEST-002")
        print("✅ 缓存测试成功（应该从缓存读取）")
        print()

        return True

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_claude_analyzer()
    print("=" * 60)
    if success:
        print("✅ 所有测试通过！")
        print()
        print("下一步:")
        print("  1. 重建 Docker 镜像: docker-compose build print-engine")
        print("  2. 重启容器: docker-compose up -d print-engine")
        print("  3. 查看日志: docker-compose logs -f print-engine")
        sys.exit(0)
    else:
        print("❌ 测试失败，请检查配置")
        sys.exit(1)

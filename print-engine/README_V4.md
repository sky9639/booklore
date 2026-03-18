# Booklore Print Engine V4.0 - 最终版本说明

**日期**: 2026-03-14
**版本**: V4.0 (SDXL + IP-Adapter + Claude API)
**状态**: ✅ 已部署并验证成功

---

## 🎯 核心方案

### 完整技术栈
1. **风格分析**: Claude Sonnet 4.6
2. **图像生成**: SDXL + IP-Adapter Plus (ViT-H)
3. **风格迁移**: IP-Adapter 权重 0.7-0.95（Claude 动态推荐）
4. **缓存机制**: 基于 MD5 的文件缓存，TTL 1小时

---

## 📊 性能指标

### 生成时间
- Claude 分析: 3-5秒
- 封底生成: 10-15秒
- 书脊生成: 3-5秒
- **总计**: 20-25秒

### Token 消耗（已优化）
- 输入 Token: ~1,200 tokens
  - 图片（800px）: ~1,000 tokens
  - 文本 Prompt: ~200 tokens
- 输出 Token: ~300 tokens
- **总计**: ~1,500 tokens/次
- **成本**: $0.008/次 (约 ¥0.06)

### 优化措施
- 图片缩放: 1024px → 800px（节省 37.5% 图片 Token）
- Prompt 精简: 中文 → 英文（节省 60% 文本 Token）
- 输出限制: max_tokens=512
- 缓存机制: 相同封面重复调用 0 成本

---

## 🔧 配置说明

### booklore.env
```bash
# ComfyUI 服务地址
COMFYUI_API_URL=http://ROG:8188

# Claude API 配置
CLAUDE_API_KEY=sk-cy5HUW4NwOI4Do0YkxXVHgePDTb186VBM3AcqMbhrgSPKaJT
CLAUDE_API_URL=http://newapi.200m.997555.xyz
CLAUDE_MODEL=claude-sonnet-4-6

# 缓存配置
CACHE_ENABLED=True
CACHE_DIR=./cache
CACHE_TTL_SECONDS=3600
```

### 必需的 ComfyUI 模型
- **SDXL Base**: `sd_xl_base_1.0.safetensors`
- **SDXL VAE**: `sdxl_vae.safetensors`
- **IP-Adapter**: `sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors`
- **CLIP**: `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`

---

## 📋 API 参数

### 必填参数
- `book_path`: 书籍路径（用于读取封面）
- 封面图片通过 `cover_selected` 从文件系统读取

### 可选参数及默认值
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `book_title` | `""` | 书名（用于文字合成） |
| `authors` | `[]` | 作者列表 |
| `description` | `""` | 简介 |
| `categories` | `["children's book"]` | 书籍分类（影响风格分析） |
| `trim_size` | `"A5"` | 页面尺寸 |
| `spine_width_mm` | `4.74` | 书脊宽度 |
| `target` | `"all"` | 生成目标（all/spine/back） |

---

## 🔍 关键技术细节

### 为什么使用 SDXL + IP-Adapter？
1. **IP-Adapter 的作用**:
   - 提取封面的视觉特征（装饰元素、纹理、色彩）
   - 在生成时融合这些特征
   - 确保封底包含封面的装饰元素

2. **与 FLUX 的对比**:
   - FLUX: 纯 inpainting，只根据 text prompt 生成
   - SDXL + IP-Adapter: 可以"看到"封面，复制视觉风格
   - 结果: SDXL 生成的封底包含装饰元素，FLUX 只能匹配色系

### Claude API 的作用
1. **风格分析**: 识别封面的艺术风格、色彩、元素
2. **Prompt 生成**: 为 SDXL 生成精准的英文 Prompt
3. **权重推荐**: 根据封面复杂度推荐 IP-Adapter 权重
4. **步数推荐**: 推荐合适的生成步数（通常 20 步）

### 画布构建策略
- **封底**: 封面左侧裁剪 + 左侧生成区（各占 50%）
- **书脊**: 封面左边缘 + 窄条生成区（边缘宽度 = 书脊宽度 × 4）
- **Mask 羽化**: 12px 羽化消除交界噪点

---

## 🚀 部署流程

### 1. 更新代码
代码已直接更新到 NAS: `\\NAS\software\booklore\print-engine`

### 2. 重建 Docker 镜像
```bash
cd /vol2/1000/software/docker-compose/booklore
docker-compose stop print-engine
docker-compose build --no-cache print-engine
docker-compose up -d print-engine
```

### 3. 验证日志
```bash
docker-compose logs -f print-engine
```

期望看到:
```
[Claude] 分析器已初始化: claude-sonnet-4-6
[Claude] 缓存已启用: ./cache (TTL: 3600s)
[ComfyUI] 任务已提交: xxx
[AI-xxxxx] Token 消耗: 1500 tokens (输入: 1200, 输出: 300)
```

---

## ✅ 验证结果

### 测试环境
- **本地测试**: E:\AI\booklore_AI_Service ✅ 通过
- **线上环境**: NAS print-engine ✅ 通过

### 测试结果
- ✅ 封底包含封面的装饰元素
- ✅ 色彩和风格完全一致
- ✅ 不是纯色背景
- ✅ 书脊自然衔接
- ✅ 总耗时 20-25 秒
- ✅ Token 统计准确

---

## 📝 代码结构

### 核心文件
```
print-engine/
├── claude_analyzer.py          # Claude API 分析模块
├── ai_generator.py              # 主生成逻辑
├── app.py                       # FastAPI 服务
├── booklore.env                 # 配置文件
└── requirements.txt             # Python 依赖
```

### 关键函数
- `ClaudeAnalyzer.analyze_cover()`: Claude 风格分析
- `_build_sdxl_ipadapter_workflow()`: SDXL + IP-Adapter 工作流
- `_run_workflow_simple()`: ComfyUI 任务提交和轮询
- `generate_ai_material()`: 主生成入口

---

## 🔄 与本地测试环境的一致性

| 组件 | 本地测试 | 线上环境 | 状态 |
|------|----------|----------|------|
| 风格分析 | Claude Sonnet 4.6 | Claude Sonnet 4.6 | ✅ 一致 |
| 生成模型 | SDXL | SDXL | ✅ 一致 |
| IP-Adapter | ✅ 有 | ✅ 有 | ✅ 一致 |
| 封面参考 | ✅ 传入 | ✅ 传入 | ✅ 一致 |
| 权重控制 | Claude 推荐 | Claude 推荐 | ✅ 一致 |
| categories 默认 | `["children's book"]` | `["children's book"]` | ✅ 一致 |
| Token 统计 | ✅ 有 | ✅ 有 | ✅ 一致 |

---

## 📈 成本分析

### 单次调用成本
- Claude API: $0.008/次
- ComfyUI: 免费（本地部署）
- **总成本**: $0.008/次 (约 ¥0.06)

### 缓存效果
- 首次调用: $0.008
- 缓存命中: $0（1小时内）
- 预计节省: 30-50%（取决于重复率）

### 月度成本估算
- 假设每天生成 100 次
- 缓存命中率 40%
- 实际调用: 60 次/天
- 月度成本: 60 × 30 × $0.008 = **$14.4/月** (约 ¥100)

---

## 🎓 经验总结

### 成功因素
1. ✅ 使用 SDXL + IP-Adapter 而非 FLUX
2. ✅ 封面作为参考图传入 IP-Adapter
3. ✅ Claude 动态推荐权重和步数
4. ✅ 通用默认参数，无偏向性
5. ✅ 完善的 Token 统计和日志

### 避免的坑
1. ❌ 不要使用 FLUX（无 IP-Adapter 支持）
2. ❌ 不要写死某本书的参数
3. ❌ 不要忘记传入封面参考图
4. ❌ 不要使用固定的 IP-Adapter 权重

---

## 📞 维护说明

### 日志位置
```bash
docker-compose logs -f print-engine
```

### 缓存管理
```bash
# 查看缓存统计
curl http://NAS:5800/cache/stats

# 清理过期缓存
curl -X POST http://NAS:5800/cache/clear \
  -H "Content-Type: application/json" \
  -d '{"type": "expired"}'
```

### 常见问题
1. **生成效果差**: 检查 IP-Adapter 模型是否正确加载
2. **Token 消耗高**: 检查图片是否正确缩放到 800px
3. **缓存未命中**: 检查封面图片是否有变化

---

**最后更新**: 2026-03-14
**维护状态**: ✅ 生产就绪
**测试状态**: ✅ 已验证通过

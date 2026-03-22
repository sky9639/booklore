# Print Engine - PDF格式化服务

基于内容边界的智能PDF格式化服务，用于将PDF缩放到标准尺寸（A4/A5/B5）并自动去除白边。

## 核心功能

### PDF智能格式化
- **内容边界检测**：智能检测每页实际内容边界（文字+图片）
- **自动去除白边**：自动裁剪页面白边，确保内容充满整个页面
- **非等比拉伸**：支持非等比拉伸以100%充满目标页面，无裁切、无白边
- **多种标准尺寸**：支持A4、A5、B5等标准打印尺寸
- **进度回调**：实时推送处理进度，支持Web界面展示

### 安全机制
- 格式化前自动创建带时间戳的备份
- 处理失败时自动恢复原文件
- 处理成功后自动清理备份

### 其他功能
- AI驱动的封面设计（Claude API）
- 封面图片提取
- PDF页面分析
- 拼版工作台集成

## 技术架构

### 核心技术栈
- **FastAPI**: Web框架
- **PyMuPDF (fitz)**: PDF内容边界检测和格式化
- **PyPDF2**: PDF基础操作
- **Pillow**: 图像处理
- **Claude API**: AI封面设计

### 格式化技术方案

#### V2.0 方案（当前）
```
1. 使用 PyMuPDF 检测内容边界（文字块+图片）
2. 将内容区域渲染为高分辨率图片（2倍zoom）
3. 使用 insert_image(keep_proportion=False) 实现非等比拉伸
4. 确保内容100%充满目标页面，无任何白边
```

**关键参数：**
- `keep_proportion=False`: 强制非等比拉伸，忽略原始宽高比
- `zoom=2.0`: 2倍分辨率渲染，保证输出质量
- `MARGIN_THRESHOLD=5.0mm`: 边距小于5mm视为已充满

## 安装

### Docker方式（推荐）

```bash
# 构建镜像
docker build -t print-engine .

# 运行容器
docker run -d -p 5800:5000 print-engine

# 或使用docker-compose
docker-compose up -d
```

### 本地安装

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app:app --host 0.0.0.0 --port 5000
```

## 使用方法

### API接口

#### 1. PDF格式化

```bash
POST /api/resize-pdf
Content-Type: application/json

{
  "book_path": "/path/to/book.pdf",
  "target_size": "A5"
}
```

**响应：**
```json
{
  "success": true,
  "new_size": {
    "width_mm": 148,
    "height_mm": 210
  }
}
```

#### 2. 带进度的PDF格式化

```bash
POST /api/resize-pdf-progress
Content-Type: application/json

{
  "book_path": "/path/to/book.pdf",
  "target_size": "A5"
}
```

**响应：** Server-Sent Events (SSE)
```
data: {"progress": 20, "stage": "正在处理第 1/10 页...", "current_page": 1, "total_pages": 10}

data: {"progress": 100, "stage": "格式化完成！"}
```

### 命令行工具

#### 检测白边
```bash
python detect_white_margins.py <pdf_path> [page_numbers...]

# 示例：检测第1,2,3页
python detect_white_margins.py book.pdf 1 2 3
```

#### 测试格式化
```bash
python test_resize.py <pdf_path> [target_size]

# 示例：格式化为A5
python test_resize.py book.pdf A5
```

## 支持的标准尺寸

| 尺寸 | 宽度 (mm) | 高度 (mm) |
|------|-----------|-----------|
| A4   | 210       | 297       |
| A5   | 148       | 210       |
| B5   | 176       | 250       |

## 开发指南

### 项目结构

```
print-engine/
├── app.py                    # FastAPI主应用
├── pdf_resizer.py            # PDF格式化核心模块
├── detect_white_margins.py   # 白边检测工具
├── test_resize.py            # 格式化测试工具
├── ai_generator.py           # AI封面生成
├── claude_analyzer.py        # Claude API集成
├── cover_extractor.py        # 封面提取
├── layout_engine.py          # 布局引擎
├── material_manager.py       # 素材管理
├── workspace_manager.py      # 工作区管理
├── requirements.txt          # Python依赖
├── Dockerfile                # Docker配置
└── README.md                 # 本文档
```

### 核心模块说明

#### pdf_resizer.py

**主要类：** `PdfResizer`

**核心方法：**
- `resize()`: 执行PDF格式化
- `_detect_content_bbox()`: 检测页面内容边界
- `_resize_with_pymupdf()`: 使用PyMuPDF执行格式化

**使用示例：**
```python
from pdf_resizer import PdfResizer

def progress_callback(data):
    print(f"[{data['progress']}%] {data['stage']}")

resizer = PdfResizer("book.pdf", "A5", progress_callback)
result = resizer.resize()

if result['success']:
    print(f"格式化成功: {result['new_size']}")
else:
    print(f"格式化失败: {result['error']}")
```

### 配置环境变量

创建 `.env` 文件：
```env
ANTHROPIC_API_KEY=your_claude_api_key
```

## 性能优化

### 已实施的优化

1. **高分辨率渲染**
   - 使用2倍zoom渲染内容，确保输出质量
   - 避免像素化问题

2. **内存管理**
   - 及时关闭PyMuPDF文档对象
   - 使用临时文件避免内存溢出

3. **错误处理**
   - 每页独立处理，单页失败不影响其他页
   - 失败时自动恢复备份

### 性能建议

- 大型PDF（>100页）建议使用进度回调，避免超时
- 生产环境建议使用异步任务队列（如Celery）
- 建议设置合理的超时时间（默认120秒）

## 故障排查

### 常见问题

**Q: 格式化后内容丢失？**
A: 检查PyMuPDF版本，确保使用 `keep_proportion=False` 参数

**Q: 白边未完全去除？**
A: 检查 `MARGIN_THRESHOLD` 设置，默认5mm以下视为充满

**Q: 处理速度慢？**
A: 大文件建议降低zoom值（默认2.0），或使用异步处理

### 日志级别

```python
import logging
logging.basicConfig(level=logging.DEBUG)  # 开发环境
logging.basicConfig(level=logging.INFO)   # 生产环境
```

## 版本历史

### V2.0 (2026-03-19)
- ✅ 实现内容边界检测
- ✅ 完全去除白边（100%充满）
- ✅ 支持非等比拉伸
- ✅ 优化渲染质量（2倍zoom）

### V1.0 (2026-03-18)
- 初始版本
- 基础PDF格式化功能

## 许可证

内部使用

## 联系方式

技术支持：开发团队
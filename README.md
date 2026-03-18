```bash
cd /vol2/1000/software/booklore  # 进入工程根目录，确保操作路径正确
git pull origin dev               # 拉取远程dev分支最新代码，避免本地与远程冲突
git commit -a -m "备注本次修改的内容"  # -a自动暂存所有已追踪文件的修改/删除，无需单独git add；-m后跟本次修改的备注信息（需替换）
git push origin dev               # 将本地提交的修改推送到GitHub的dev分支，完成同步
```

# Booklore 工程说明
## 重要配置路径
- 容器编排配置（实际使用）：/vol2/1000/software/docker-compose/booklore/docker-compose.yml
- 本目录下的 docker-compose.yml 已废弃，请勿使用！

## 核心目录说明
- booklore-api/：Spring Boot 后端源码
- booklore-ui/：Angular 前端源码
- print-engine/：Python 打印引擎源码
- shared/：共享数据目录

# Booklore Print Workspace — 完整方案手册 V2.0

> **基线冻结日期：2026-03-15**
> 本手册覆盖从 AI 生图到前端拼版工作台的完整技术方案，适用于二次开发交接。
>
> **V2.0 重大更新（2026-03-15）：**
> - ✅ SSE 实时进度推送已上线（替代同步等待方案）
> - ✅ 前端实时日志显示，完整记录生成过程
> - ✅ 代码全面优化：增强鲁棒性、可维护性、容错性
> - ✅ 进度条与日志区域 UI 优化，完美对齐拼版预览
> - ✅ Token 消耗实时显示
> - ✅ 自动滚动到最新日志
>
> V1.1 修正：Docker挂载路径更正、ai_generator.py状态更正、Janus模型位置说明补充、PrintEngineClient超时配置补充

---

## 一、项目概述

Booklore 是一个 NAS 自托管的电子书管理系统。**Print Workspace（拼版工作台）** 是其中的实体书印刷模块，实现：

```
电子书 PDF → AI 生成书脊/封底 → 拼版预览 → 生成400DPI印刷PDF → 下载送印
```

整个方案横跨三个物理节点：
- **NAS（Synology）** — 主应用服务器，运行 Docker 容器群
- **Windows 工作站（RTX 5090）** — 本地 AI 推理节点，运行 Janus API + ComfyUI
- **浏览器客户端** — Angular 前端

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    浏览器 Angular 前端                        │
│  print-workspace.component (V1.9)                           │
│  material-slot.component (V1.4)                             │
│  pdf-viewer.component                                        │
│  workspace-state.service (V1.3)                             │
│  material.service (V1.2)                                     │
│  print.service (V1.3)                                        │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP  /api/v1/print/...
┌──────────────────────▼──────────────────────────────────────┐
│                NAS — Spring Boot Backend                     │
│  PrintController.java        REST接口层                      │
│  PrintEngineClient.java      HTTP转发到print-engine          │
│    ├─ restTemplate   (timeout 45s)  普通接口                 │
│    └─ aiRestTemplate (timeout 300s) AI生成专用               │
│  PrintRequest.java           请求DTO                         │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP  :5000
┌──────────────────────▼──────────────────────────────────────┐
│           NAS — print-engine (Python FastAPI Docker)        │
│  app.py                主路由                                │
│  workspace_manager.py  .print目录 / workspace.json读写       │
│  material_manager.py   素材文件管理                          │
│  layout_engine.py      拼版布局 / PDF生成                    │
│  cover_extractor.py    PDF封面提取                           │
│  ai_generator.py (V2.0) ✅ FLUX Outpainting方案（已上线）    │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP  :8788 / :8188
┌──────────────────────▼──────────────────────────────────────┐
│          Windows 工作站 — AI推理节点（局域网 192.168.1.167）  │
│                                                              │
│  【Janus 环境 — conda: janus】                               │
│  janus_api.py (V1.1)     封面风格分析 Flask API (:8788)      │
│  Janus-Pro-7B            视觉理解模型（conda环境内）          │
│                                                              │
│  【ComfyUI 环境 — python_embeded】                           │
│  comfyui_flux_outpaint.py (V2.0)  FLUX生成客户端             │
│  test_flux_outpaint.py (V1.0)     本地测试主程序             │
│  ComfyUI                 推理引擎（端口8188）                 │
│  FLUX.1-dev              图像生成模型                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、代码文件清单与版本基线

### 3.1 Windows AI 节点

#### ComfyUI 模型文件（E:\AI\ComfyUI_windows_portable_nvidia_cu128\models\）

| 路径 | 大小 | 说明 |
|------|------|------|
| `unet\flux1-dev.safetensors` | 24GB | FLUX.1-dev 主模型，需HF授权下载 |
| `vae\ae.safetensors` | 335MB | VAE 解码器 |
| `clip\clip_l.safetensors` | 246MB | CLIP-L 文本编码器 |
| `clip\t5xxl_fp8_e4m3fn.safetensors` | 4.5GB | T5 文本编码器 **fp8版**（必须用此版本） |

#### Booklore AI 脚本（E:\AI\booklore_AI\）

| 文件名 | 版本 | 状态 | 职责 |
|--------|------|------|------|
| `comfyui_flux_outpaint.py` | **V2.0** | ✅ 冻结 | FLUX Outpainting 两步生成客户端 |
| `test_flux_outpaint.py` | **V1.0** | ✅ 冻结 | 本地测试入口，含文字合成+拼接 |
| `janus_api.py` | **V1.1** | ✅ 冻结 | Janus-Pro-7B 封面风格分析 Flask API |
| `启动ComfyUI.bat` | — | ✅ 冻结 | ComfyUI 启动脚本（RTX 5090优化参数） |
| `启动Janus_API.bat` | — | ✅ 冻结 | Janus API 启动脚本 |

#### Janus-Pro-7B 模型位置

Janus 模型**不在** ComfyUI 的 models 目录，它是独立的 conda 环境，模型由 HuggingFace 自动缓存：

```
conda 环境名：  janus
模型缓存路径：  C:\Users\{用户名}\.cache\huggingface\hub\models--deepseek-ai--Janus-Pro-7B\
启动方式：      conda activate janus  →  python janus_api.py
对外端口：      8788
```

首次运行 `janus_api.py` 时自动从 HuggingFace 下载并缓存，后续启动直接读本地缓存。

### 3.2 NAS print-engine（/vol2/1000/software/booklore/print-engine/）

| 文件名 | 版本 | 状态 | 职责 |
|--------|------|------|------|
| `app.py` | **V2.0** | ✅ 当前线上 | FastAPI 主路由 + SSE 进度推送 + 异步任务管理 |
| `workspace_manager.py` | V1.0 | ✅ 当前线上 | .print 目录管理，workspace.json 读写 |
| `material_manager.py` | V1.0 | ✅ 当前线上 | 素材文件存取，history 管理 |
| `layout_engine.py` | V1.0 | ✅ 当前线上 | 拼版布局计算，印刷 PDF 生成 |
| `cover_extractor.py` | V1.0 | ✅ 当前线上 | 从 PDF 提取封面图 |
| `ai_generator.py` | **V2.1** | ✅ 当前线上 | FLUX Outpainting + 详细进度回调 + 输入参数日志 |
| `booklore.env` | V1.0 | ✅ 当前线上 | AI 渠道配置（参考 booklore.env.example） |

### 3.3 NAS Spring Boot Backend

| 文件名 | 版本 | 状态 | 职责 |
|--------|------|------|------|
| `PrintController.java` | V1.1 | ✅ 当前线上 | 拼版相关 REST 接口，素材上传/删除/选择/AI生成 |
| `PrintEngineClient.java` | **V1.2** | ✅ 当前线上 | HTTP 转发到 print-engine，含双RestTemplate超时配置 |
| `PrintRequest.java` | V1.0 | ✅ 当前线上 | 拼版请求 DTO |

### 3.4 Angular 前端

| 文件名 | 版本 | 状态 | 职责 |
|--------|------|------|------|
| `print-workspace.component.ts` | **V2.0** | ✅ 冻结 | 拼版工作台主组件 + SSE 处理 + 日志管理 |
| `print-workspace.component.html` | **V2.0** | ✅ 冻结 | 工作台模板 + 日志区域 |
| `print-workspace.component.scss` | **V2.0** | ✅ 冻结 | 工作台样式 + 进度条 + 日志样式 |
| `material-slot.component.ts` | **V1.4** | ✅ 冻结 | 素材槽组件（封面/书脊/封底通用卡片） |
| `workspace-state.service.ts` | **V1.3** | ✅ 冻结 | 工作台状态管理（BehaviorSubject） |
| `material.service.ts` | **V1.2** | ✅ 冻结 | 素材上传/AI生成 HTTP 服务 |
| `print.service.ts` | **V1.3** | ✅ 冻结 | 预览/PDF生成/参数保存 HTTP 服务 |
| `pdf-viewer.component.ts` | V1.0 | ✅ 当前线上 | PDF.js 印刷预览页面 |

---

## 四、.print 目录结构与 workspace.json

### 目录结构

```
{书籍PDF所在目录}/
├── BookName.pdf
└── .print/
    ├── workspace.json          ← 工作台状态（核心）
    ├── cover/                  ← 封面素材
    │   └── cover_20240101_120000.jpg
    ├── spine/                  ← 书脊素材
    │   └── ai_spine_20240103_150000.png
    ├── back/                   ← 封底素材
    │   └── ai_back_20240103_150000.png
    └── preview/                ← 预览图（可重新生成）
        └── preview_layout.png
```

### workspace.json 完整结构

```json
{
  "book_name": "Who Is Bill Gates?",
  "trim_size": "A5",
  "page_count": 108,
  "paper_thickness": 0.06,
  "spine_width_mm": 6.48,
  "cover": {
    "selected": "cover_20240101_120000.jpg",
    "history": ["cover_20240101_120000.jpg", "cover_20231201_080000.jpg"]
  },
  "spine": {
    "selected": "ai_spine_20240103_150000.png",
    "history": ["ai_spine_20240103_150000.png", "spine_20240101_120000.png"]
  },
  "back": {
    "selected": "ai_back_20240103_150000.png",
    "history": ["ai_back_20240103_150000.png"]
  },
  "preview_path": "/path/to/.print/preview/preview_layout.png",
  "pdf_path": "/path/to/.print/layout_print.pdf",
  "updated_at": "2024-01-03T15:00:00.000000"
}
```

**核心规则：**
- `selected` 存文件名（不含路径），前端通过 asset 接口加载
- `history` 最多保留5条，最新在最前
- AI 生成和手工上传更新 workspace.json 的逻辑完全一致

---

## 五、AI 生图方案详解（FLUX Outpainting）

### 5.1 核心原理

**不重新生成，而是物理延续封面：**
- 封面放在画布右侧，左侧留白
- 白色 mask 告诉 FLUX：左侧需填充，右侧保留
- FLUX inpaint 自然延续封面的色彩/纹理/光影

### 5.2 为什么分两步

一次性生成整张展开图时，书脊在1262px宽的画布里只占12%，FLUX 注意力机制完全忽略，书脊消失。

```
❌ 一步方案（失败）：
画布 = [封底(559px)] + [书脊(150px)] + [封面(553px)] = 1262px
→ FLUX 忽略12%的书脊区域，封底直接贴封面

✅ 两步方案（当前基线）：
Step1: 画布 = [封底空白(559px)] + [封面左侧参考(559px)] → 各50%，FLUX正常处理
Step2: 画布 = [书脊空白(150px)] + [封面左边缘参考(600px)] → 专注生成窄条
Step3: Python PIL 直接拼接三张图，坐标100%精确
```

### 5.3 书脊像素放大策略

```python
spine_px_real = int(spine_mm * page_h / 210)  # 真实像素，如 38px（10mm@A5）
spine_px_gen  = max(150, spine_px_real)        # 生成像素，最小150px

# 生成完成后 resize 回真实尺寸
spine_img.resize((spine_px_real, page_h), Image.LANCZOS)
```

FLUX 处理宽度 < 100px 的窄条效果极差，放大生成后缩小是唯一可行方案。

### 5.4 Prompt 策略

**封底：**
```
{style}. Seamlessly extend the book cover scene to the left as a back cover.
Continue the background scene and atmosphere from the cover.
Lower half should be calm and relatively plain for text placement.
No characters in center, no title text, natural continuation.
```

**书脊：**
```
{style}. Seamlessly extend the book cover edge to the left as a narrow spine strip.
Exact same background color, texture and pattern as the cover left edge.
Simple vertical continuation, no new elements, seamless transition.
```

### 5.5 FLUX ComfyUI 工作流关键参数

```python
UNETLoader:          flux1-dev.safetensors, weight_dtype=fp8_e4m3fn_fast
VAELoader:           ae.safetensors
DualCLIPLoader:      clip_l.safetensors + t5xxl_fp8_e4m3fn.safetensors, type=flux
VAEEncodeForInpaint: grow_mask_by=0  # 不扩展边缘，避免坐标偏移
KSampler:            euler, simple, cfg=1.0, denoise=1.0, steps=20
FluxGuidance:        guidance=3.5
```

---

## 六、Windows AI 节点配置

### 6.1 硬件环境

| 项目 | 配置 |
|------|------|
| GPU | RTX 5090，32GB VRAM |
| CUDA | 12.8 |
| ComfyUI 路径 | `E:\AI\ComfyUI_windows_portable_nvidia_cu128\` |
| 项目路径 | `E:\AI\booklore_AI\` |

### 6.2 ComfyUI 启动参数（最终确认版）

```bat
.\python_embeded\python.exe -s ComfyUI\main.py ^
  --windows-standalone-build ^
  --highvram ^
  --bf16-unet ^
  --fp16-vae ^
  --fast ^
  --disable-smart-memory ^
  --listen 0.0.0.0
```

| 参数 | 作用 |
|------|------|
| `--highvram` | 不自动卸载模型，常驻显存 |
| `--bf16-unet` | UNet 用 bfloat16，省显存+提速 |
| `--fp16-vae` | VAE 用 float16（5090不需要fp32） |
| `--fast` | 启用 PyTorch kernel 融合优化，GPU真正高效计算而非空转等待 |
| `--disable-smart-memory` | 彻底禁用自动卸载，与 highvram 叠加确保模型常驻 |
| `--listen 0.0.0.0` | 允许局域网访问，NAS 调用此参数必须存在 |

### 6.3 显存分配

```
FLUX dev (fp8):    ~12GB
T5 fp8:            ~ 4.5GB
VAE:               ~ 1GB
推理中间状态:      ~ 8GB
合计:              ~25.5GB  ✓ 小于 32GB

Janus-Pro-7B:      ~ 8GB（独立进程，与ComfyUI分时使用GPU）
```

### 6.4 已解决的历史坑

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| os error 1455 | 24GB safetensors mmap加载，Windows虚拟地址空间不足 | E盘页面文件设为 65536MB，重启 |
| CUDA OOM | T5 fp16(9GB) + FLUX(24GB) > 32GB | 改用 t5xxl_fp8_e4m3fn(4.5GB) |
| 书脊生成消失 | 书脊在整张画布占比12%，FLUX注意力忽略 | 改为两步分开生成 |
| 拼接坐标错位 | 依赖FLUX输出坐标不稳定 | 改为Python PIL直接拼接 |
| GPU 100%满载但生成慢 | 缺少--fast，GPU在空转等待kernel调度而非真正计算 | 添加 --fast --disable-smart-memory |

---

## 七、PrintEngineClient 超时配置

```java
// 普通接口（init / preview / generate / saveParams）
restTemplate    = buildRestTemplate(10_000, 45_000);   // readTimeout = 45s

// AI 生成专用（FLUX Outpainting 两步合计约 3-5 分钟）
aiRestTemplate  = buildRestTemplate(10_000, 300_000);  // readTimeout = 300s
```

| 方法 | RestTemplate | 超时 |
|------|-------------|------|
| `initWorkspace` | restTemplate | 45s |
| `preview` | restTemplate | 45s |
| `generate` | restTemplate | 45s |
| `saveParams` | restTemplate | 45s |
| `aiGenerate` | **aiRestTemplate** | **300s** |
| `aiGenerateStart` | restTemplate | 45s（异步启动，立即返回task_id） |

> **关于浏览器关闭后任务是否继续：**
> ComfyUI 收到任务后独立执行直到完成，不受浏览器连接影响。
> print-engine 会等待 ComfyUI 结果并自动保存文件、更新 workspace.json。
> 浏览器关闭只影响前端能否收到本次响应，**文件和 workspace.json 会正确更新**，
> 重新打开拼版工作台刷新后即可看到新生成的素材。

---

## 八、后端 API 接口清单

### Spring Boot（/api/v1/print/）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/{bookId}/workspace/init` | 初始化工作台，自动获取封面 |
| POST | `/{bookId}/workspace/upload/{category}` | 手工上传素材（cover/spine/back） |
| POST | `/{bookId}/select?category=&filename=` | 切换选中素材 |
| DELETE | `/{bookId}/material?category=&filename=` | 删除素材 |
| POST | `/{bookId}/preview` | 生成预览图 |
| POST | `/{bookId}/pdf` | 生成印刷 PDF |
| GET | `/{bookId}/pdf/view` | inline 查看 PDF（供 PDF.js） |
| GET | `/{bookId}/pdf/download` | 强制下载 PDF |
| GET | `/{bookId}/asset/{category}/{filename}` | 读取素材图片 |

### print-engine FastAPI（:5000）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/workspace/init` | 初始化 workspace.json |
| POST | `/workspace/upload/{category}` | 保存素材文件 |
| POST | `/workspace/params` | 保存成书参数（trim_size等） |
| POST | `/preview` | 生成预览图 |
| POST | `/generate` | 生成印刷 PDF |
| POST | `/ai-generate` | FLUX生成书脊/封底，返回PNG bytes |
| POST | `/workspace/ai-generate/start` | 异步启动AI生成（预留SSE方案） |

### Windows AI 节点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `:8788/health` | Janus API 健康检查 |
| POST | `:8788/analyze` | 封面风格分析，返回 prompt 文字 |
| GET | `:8188/` | ComfyUI Web UI |
| POST | `:8188/prompt` | 提交生成任务 |
| GET | `:8188/history/{prompt_id}` | 查询任务状态 |
| GET | `:8188/view` | 下载生成图片 |

---

## 九、booklore.env AI 渠道配置

支持三种 AI 渠道，通过 `AI_PROVIDER` 切换：

| 渠道 | 值 | 适用场景 |
|------|-----|---------|
| 官方 API | `official` | Anthropic + OpenAI 各自 Key |
| 302AI 聚合代理 | `302ai` | 一个 Key 同时用 Claude+GPT |
| 本地模型 | `local` | 离线/隐私场景 |
| **本地 FLUX**（当前使用） | — | 通过 JANUS_API_URL + COMFYUI_API_URL 指向Windows工作站，零API费用 |

当前实际生效的关键配置：
```env
JANUS_API_URL=http://192.168.1.167:8788
COMFYUI_API_URL=http://192.168.1.167:8188
```

---

## 十、本地测试用法

```cmd
cd E:\AI\booklore_AI

# 基础测试（跳过Janus，用固定风格描述）
python test_flux_outpaint.py cover.jpg "Who Is Bill Gates" --no-janus

# 完整测试（带Janus风格分析）
python test_flux_outpaint.py cover.jpg "Who Is Bill Gates"

# 中文书籍，自定义书脊宽度
python test_flux_outpaint.py cover.jpg "三体" --spine-width 12.5 --size A5

# 快速测试（减少步数）
python test_flux_outpaint.py cover.jpg "三体" --steps 10 --no-janus
```

内置测试书籍（无需网络）：
- `"who is bill gates"` → *Who Is Bill Gates?*（Patricia Brennan Demuth）
- `"三体"` → *三体*（刘慈欣）

输出：`cover_spread.png`（完整展开图，封底+书脊+封面）

---

## 十一、待完成工作

| 优先级 | 任务 | 说明 |
|--------|------|------|
| 🟢 低 | 端到端集成测试 | Angular → NAS → Windows FLUX → 返回完整流程验证 |
| 🟢 低 | 性能监控 | 添加生成时间统计、成功率监控 |

**已完成（V2.0）：**
- ✅ SSE 异步进度推送
- ✅ 前端实时日志显示
- ✅ 代码优化与重构
- ✅ UI 布局优化

---

## 十二、Docker 部署说明

```yaml
# print-engine 容器挂载路径（正确路径）
volumes:
  - /vol2/1000/software/booklore/print-engine:/app

# 修改代码后重新部署
docker compose build print-engine
docker restart print-engine
```

---

## 十三、关键配置速查

```
NAS IP:                  192.168.1.x（按实际）
Windows AI 节点 IP:      192.168.1.167
Janus API 端口:          8788
ComfyUI 端口:            8188
print-engine 端口:       5000（HTTP）
print-engine SSE 端口:   5800（前端直连，绕过nginx超时）
Spring Boot 端口:        6060

print-engine 代码���径:   /vol2/1000/software/booklore/print-engine/
.print 目录位置:         {书籍PDF目录}/.print/
workspace.json 路径:     {书籍PDF目录}/.print/workspace.json
印刷PDF路径:             {书籍PDF目录}/.print/layout_print.pdf

SSE 配置:
  轮询间隔:   0.1s（后端）
  心跳间隔:   10s
  超时时间:   20分钟
  进度回调延迟: 0.15s（确保状态捕获）

PrintEngineClient 超时（已废弃同步方案）:
  普通接口:   readTimeout = 45s
  AI生成接口: 已改为异步SSE，无需长超时
```

---

## 十四、V2.0 更新日志（2026-03-15）

### 核心功能

**SSE 实时进度推送：**
- ✅ 前端通过 EventSource 连接 SSE 流
- ✅ 后端异步任务管理，子线程执行生成
- ✅ 实时推送进度、阶段、Token 消耗
- ✅ 心跳机制保持连接活跃（每10秒）
- ✅ 20分钟超时保护

**前端实时日志：**
- ✅ 时间 + 进度 + 详细步骤三列显示
- ✅ 自动滚动到最新日志
- ✅ 重要节点高亮显示
- ✅ 输入参数完整记录（书名、作者、封面路径、尺寸等）
- ✅ Token 消耗实时显示

### 代码优化

**后端 Python (app.py, ai_generator.py)：**
- ✅ 完整的函数文档字符串（docstring）
- ✅ 增强的错误处理和边界检查
- ✅ 任务状态锁保护（避免并发问题）
- ✅ SSE 轮询间隔优化（0.3s → 0.1s）
- ✅ 进度回调延迟机制（0.15s，确保状态捕获）
- ✅ 超时机制（20分钟）
- ✅ 删除重复代码和冗余逻辑

**前端 TypeScript (print-workspace.component.ts)：**
- ✅ 提取辅助方法（handleAiSuccess、handleAiError、extractErrorMessage、handleSseMessage）
- ✅ 增加完整的 JSDoc 注释
- ✅ 增强的错误处理和空值检查
- ✅ ViewChild 元素存在性检查
- ✅ 防重复点击检查
- ✅ SSE 连接状态检查
- ✅ JSON 解析异常捕获

**样式 SCSS (print-workspace.component.scss)：**
- ✅ 删除未使用的旧样式
- ✅ 添加清晰的分区注释
- ✅ 统一代码格式和缩进
- ✅ 优化日志区域高度计算（calc(100vh - 130px)）

### UI 优化

- ✅ 进度条移到日志标题行右侧，宽度撑满
- ✅ 进度条样式符合 booklore 风格（深蓝色渐变）
- ✅ 百分比居中显示在进度条内部
- ✅ 日志区域高度与拼版预览完美对齐
- ✅ 日志字号增大（11px → 13px）
- ✅ 日志间距优化（8px → 4px）
- ✅ 去掉成功消息单独行，避免高度变化

### 性能优化

- ✅ SSE 轮询间隔缩短（0.3s → 0.1s），减少状态丢失
- ✅ 进度回调添加延迟（0.15s），确保 SSE 捕获所有状态
- ✅ 前端 ChangeDetectorRef 手动触发，确保 UI 及时更新
- ✅ 自动滚动延迟（50ms），确保 DOM 更新后再滚动

### 鲁棒性提升

- ✅ 增加 task_id 存在性检查
- ✅ 增加 cover_selected 安全访问（使用 .get()）
- ✅ 增加任务状态锁保护，避免并发问题
- ✅ 增加超时机制（20分钟）防止任务无限挂起
- ✅ 增加 SSE 连接断开检测和错误处理
- ✅ 增加 workspace 空值检查
- ✅ 增加 ViewChild 元素存在性检查

---

**备份说明：** 原 README.md 已备份为 README.md.backup_20260315


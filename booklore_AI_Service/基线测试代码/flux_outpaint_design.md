# FLUX Outpainting 书脊+封底生成方案 — 详细交接文档

## 一、方案背景与核心思路

### 为什么用 Outpainting，而不是重新生成？

早期方案（已废弃）使用 SDXL + IP-Adapter，把封面当"风格参考"来重新生成书脊和封底。
结果是 AI 把封面重新画了一遍（独立构图），书脊/封底和封面完全不像同一本书。

**Outpainting 方案的核心思路：**
- 把封面图像放在画布的右侧，左侧留白作为"待填充区域"
- 用一张二值 mask 告诉 FLUX：右侧=保留（黑色），左侧=填充（白色）
- FLUX 的 inpaint 能力会**物理延续**封面的背景、色彩、纹理、光影
- 效果等同于"把封面画布向左扩展"，天然一致

---

## 二、为什么分两步，而不是一次生成？

### 失败的一步方案
一开始尝试一次性生成整张展开图：
```
画布 = [封底空白(559px)] + [书脊空白(150px)] + [封面(553px)] = 1262px 宽
```
**问题：书脊在 1262px 宽的画布里只占 150px（约12%），FLUX 的注意力机制完全忽略了这么窄的区域。**
生成结果里书脊根本不存在——封底直接和封面拼在一起，中间没有书脊。

### 两步方案的设计
**Step1 专门生成封底**，画布 = [封底空白] + [封面左侧参考]，两块各约50%，FLUX正常处理。
**Step2 专门生成书脊**，画布 = [书脊空白] + [封面左边缘参考×4倍宽]，专注生成窄条衔接。
**Step3 Python PIL 直接拼接三张独立图**，坐标100%精确，不依赖 FLUX 的位置感知。

---

## 三、文件说明

### 文件位置
```
E:\AI\booklore_AI\
├── comfyui_flux_outpaint.py   ← FLUX生成客户端（核心）
└── test_flux_outpaint.py      ← 测试主程序（文字合成+拼接+入口）
```

### comfyui_flux_outpaint.py — 负责什么
- 构建 ComfyUI FLUX inpaint 工作流 JSON
- 生成画布（canvas）和遮罩（mask）
- 上传到 ComfyUI，轮询等待结果
- 两步调用 FLUX，返回三张 PIL Image（封底、书脊、封面）

### test_flux_outpaint.py — 负责什么
- 命令行入口（argparse）
- 从 Open Library 查询书籍信息（书名、作者、简介、分类）
- 调用 Janus API 分析封面风格（可用 `--no-janus` 跳过）
- 构建封底和书脊各自的 FLUX prompt
- 调用 comfyui_flux_outpaint.py 生成图片
- 封底文字合成（书名、作者、简介、渐变遮罩）
- 书脊文字合成（竖排书名、作者）
- 最终拼接输出 cover_spread.png

---

## 四、comfyui_flux_outpaint.py 详解

### 4.1 FLUX ComfyUI 工作流节点

```python
def build_flux_inpaint_workflow(canvas_fn, mask_fn, prompt, seed, steps=20, guidance=3.5):
```

使用的 ComfyUI 节点链：
```
UNETLoader          → 加载 flux1-dev.safetensors (fp8_e4m3fn_fast 量化)
VAELoader           → 加载 ae.safetensors
DualCLIPLoader      → clip_l.safetensors + t5xxl_fp8_e4m3fn.safetensors (flux模式)
LoadImage(canvas)   → 加载画布图片
LoadImage(mask)     → 加载遮罩图片
ImageToMask         → 从mask图红色通道提取遮罩
VAEEncodeForInpaint → 编码画布+遮罩为latent，grow_mask_by=0（不扩展边缘）
CLIPTextEncode      → 正向prompt
CLIPTextEncode("")  → 空负向prompt（FLUX不需要负向）
FluxGuidance        → guidance=3.5
KSampler            → euler采样器，simple调度，cfg=1.0，denoise=1.0，steps=20
VAEDecode           → 解码latent为图片
SaveImage           → 保存到ComfyUI output目录
```

**关键参数说明：**
- `weight_dtype="fp8_e4m3fn_fast"` — RTX 5090 32GB显存，FLUX dev 24GB + T5 fp8 4.5GB 能装下
- `grow_mask_by=0` — 不扩展遮罩边缘，避免边缘坐标偏移
- `cfg=1.0` — FLUX dev 特性，cfg必须为1.0（不像SDXL用7.0）
- `guidance=3.5` — 通过FluxGuidance节点控制引导强度

### 4.2 画布和遮罩生成

```python
def make_canvas_and_mask(bg_img, fill_w, fill_on_left=True):
```

**生成规则：**
- 画布（canvas）：右侧放已有图片（封面或封面裁边），左侧填灰色(200,200,200)
- 遮罩（mask）：黑色=保留原始内容，白色=让FLUX填充
  - 左侧填充区域 → 白色（255）
  - 右侧参考区域 → 黑色（0）

```
canvas:  [  灰色填充区(fill_w)  |  封面参考图(bg_img)  ]
mask:    [  白色(255)=填充      |  黑色(0)=保留        ]
```

### 4.3 两步生成主入口

```python
def outpaint_cover(cover_path, prompt_back, prompt_spine,
                   back_width_px, spine_width_px, page_height_px,
                   seed=-1, steps=20):
    → 返回 (back_img, spine_img, cover_img) 三张 PIL Image
```

**Step1 封底生成：**
```python
ref_w   = min(cw, back_width_px)         # 取封面宽度和封底宽度中较小值
ref_img = cover.crop((0,0, ref_w, page_height_px))  # 封面左侧裁片作参考

# 画布 = [封底空白(back_width_px)] + [封面左侧参考(ref_w)]
# 两块比例各约50%，FLUX能充分理解参考内容
canvas_b, mask_b, tw1, th1 = make_canvas_and_mask(ref_img, back_width_px)
raw1     = flux_generate(canvas_b, mask_b, prompt_back, seed, steps)
result1  = resize_to(raw1, tw1, th1)     # 修正FLUX可能输出的尺寸偏差
back_img = result1.crop((0,0, back_width_px, th1))  # 只取左侧封底部分
```

**Step2 书脊生成：**
```python
edge_w   = min(cw, spine_width_px * 4)  # 封面左边缘参考宽度=书脊的4倍
edge_img = cover.crop((0,0, edge_w, page_height_px))

# 画布 = [书脊空白(spine_width_px)] + [封面左边缘参考(edge_w)]
# 书脊生成时用放大尺寸(≥150px)，保证FLUX能看清细节
canvas_b2, mask_b2, tw2, th2 = make_canvas_and_mask(edge_img, spine_width_px)
raw2      = flux_generate(canvas_b2, mask_b2, prompt_spine, seed+1, steps)
result2   = resize_to(raw2, tw2, th2)
spine_img = result2.crop((0,0, spine_width_px, th2))
```

---

## 五、test_flux_outpaint.py 详解

### 5.1 命令行用法

```cmd
# 基础用法（A5，书脊10mm，自动查书名）
python test_flux_outpaint.py cover.jpg "Who Is Bill Gates"

# 不用Janus（用固定风格描述，离线环境）
python test_flux_outpaint.py cover.jpg "Who Is Bill Gates" --no-janus

# 指定书脊宽度和开本
python test_flux_outpaint.py cover.jpg "三体" --spine-width 12.5 --size A5

# 减少步数加速测试
python test_flux_outpaint.py cover.jpg "三体" --steps 10 --no-janus
```

### 5.2 书脊像素计算（重要）

```python
spine_px_real = max(1, int(args.spine_width * page_h / 210))
# A5页高794px，210mm对应794px，所以 mm → px = spine_mm * 794/210

SPINE_GEN_MIN = 150   # FLUX生成最小有效宽度
spine_px_gen  = max(SPINE_GEN_MIN, spine_px_real)
# 如果真实书脊只有38px（10mm），强制放大到150px给FLUX生成
# 生成完后再 resize 回真实 38px
```

**设计原因：** FLUX 在处理宽度 < 100px 的窄条时效果极差，强制放大生成后缩小是唯一可行方案。

### 5.3 Prompt 策略

封底和书脊使用不同的 prompt 策略：

**封底 prompt：**
```python
f"{style}. "
f"Seamlessly extend the book cover scene to the left as a back cover. "
f"Continue the background scene and atmosphere from the cover. "
f"Lower half should be calm and relatively plain for text placement. "
f"Maintain exact same art style, lighting, color temperature. "
f"No characters in center, no title text, natural continuation."
```

**书脊 prompt：**
```python
f"{style}. "
f"Seamlessly extend the book cover edge to the left as a narrow spine strip. "
f"Exact same background color, texture and pattern as the cover left edge. "
f"Simple vertical continuation, no new elements, seamless transition."
```

书脊 prompt 更强调"简单延续"，因为书脊本来就应该是纯色或简单纹理，不需要复杂内容。

### 5.4 封底文字合成（composite_back）

处理流程：
1. **渐变遮罩** — 从图片40%高度处开始，向下逐渐变暗（最深约185/255透明度）
   - 用缓动曲线（progress^1.4）使过渡自然，无硬边
2. **书名** — 白色粗体，带黑色多方向阴影（不用背景框，直接叠在渐变上）
   - 字号从页宽7%开始，自动缩小直到适合宽度
3. **作者** — 暖金色细字（#FFE182），同样带阴影
4. **虚线分隔** — 点状虚线，比实线轻盈
5. **简介** — 浅灰白小字，自动换行，超出高度95%则截断加"…"

### 5.5 书脊文字合成（composite_spine）

处理流程：
1. 书脊图旋转 -90° → 变成横向宽图，方便写水平文字
2. 自动计算字号（书脊宽度的55%和38%）
3. 书名自动缩小直到适合画面宽度
4. 在旋转图上叠加半透明黑色背景条
5. 写书名（白色）和作者（浅灰）
6. 再旋转回 +90° → 恢复竖向书脊

### 5.6 最终拼接

```python
# 拼接顺序（从左到右）
spread.paste(back_with_text,  (0,                          0))  # 封底+文字
spread.paste(spine_with_text, (page_w,                     0))  # 书脊+文字(真实宽度)
spread.paste(cover_img,       (page_w + spine_px_real,     0))  # 封面原图

# 坐标精确：
# 封底结束位置 = page_w
# 书脊结束位置 = page_w + spine_px_real
# 封面起始位置 = page_w + spine_px_real
# 总宽          = page_w + spine_px_real + cover_w
```

---

## 六、Windows 环境配置

### ComfyUI 启动参数
```cmd
.\python_embeded\python.exe -s ComfyUI\main.py ^
  --windows-standalone-build ^
  --highvram ^
  --bf16-unet ^
  --fp16-vae ^
  --fast ^
  --disable-smart-memory
```

### 已下载模型（E:\AI\ComfyUI_windows_portable_nvidia_cu128\）
```
models/unet/flux1-dev.safetensors          (24GB, 需HF授权)
models/vae/ae.safetensors                  (335MB)
models/clip/clip_l.safetensors             (246MB)
models/clip/t5xxl_fp8_e4m3fn.safetensors   (4.5GB ← 必须用fp8版，fp16会OOM)
```

### GPU 显存分配（RTX 5090 32GB）
```
FLUX dev (fp8):    约 12GB
T5 fp8:            约  4.5GB
VAE:               约  1GB
推理中间状态:       约  8GB
合计:              约 25.5GB  < 32GB ✓
```

### 已解决的问题
- **os error 1455（页面文件太小）**：E盘页面文件设为65536MB，重启解决
- **CUDA OOM**：改用t5xxl_fp8版本（从9GB降到4.5GB）解决
- **书脊生成丢失**：改为两步分开生成，每步各占画布50%解决
- **输出坐标错位**：改为Python PIL直接拼接，不再依赖FLUX感知位置解决

---

## 七、Janus 风格分析（可选）

Janus-Pro 跑在同一台 Windows 机器上，端口8788：
```
GET  http://192.168.1.167:8788/health   → 健康检查
POST http://192.168.1.167:8788/analyze  → 分析封面风格
  body: { image_base64, book_title, authors, categories, description, target }
  返回: { prompt: "..." }  ← 风格描述文本，作为FLUX prompt的开头
```

用 `--no-janus` 时使用内置 FALLBACK_STYLE：
```python
FALLBACK_STYLE = (
    "seamless extension of book cover art, "
    "same color palette and illustration style, "
    "atmospheric background, professional book design"
)
```

---

## 八、输出文件

运行后在脚本同目录生成：
```
cover_spread.png   ← 完整展开图（封底+书脊+封面），可直接发印刷厂
```

---

## 九、后续集成计划（NAS print-engine）

这套逻辑最终需要集成到 NAS 上的 `ai_generator.py`，流程：

```
Angular 前端 → Spring Boot PrintController
  → POST /api/v1/print/{bookId}/workspace/ai-generate?target=back|spine
  → print-engine (NAS FastAPI) POST /ai-generate
  → 调用 comfyui_flux_outpaint.outpaint_cover()（Windows ComfyUI IP: 192.168.1.167:8188）
  → 生成图片 bytes
  → 保存到 .print/back/ 或 .print/spine/
  → 更新 workspace.json（selected + history，与手工上传逻辑完全一致）
  → 返回 workspace JSON 给前端
```

**关键约束：** AI生成后更新 workspace.json 必须与手工上传走完全相同的逻辑（selected指向新文件，history插入最前并限制5条）。

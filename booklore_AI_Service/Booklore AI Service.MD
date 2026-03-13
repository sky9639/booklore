# Booklore AI Service (External Vision & Generation)

本模块是 **Booklore** 系统中负责视觉分析与图像生成的独立 AI 插件。由于模型推理对显存要求较高，本模块设计为 **独立于 NAS 部署**，需运行在具备高性能显卡的 PC 环境下。

## ⚠️ 硬件与部署环境要求
* **计算设备**：建议部署在配备 **NVIDIA RTX 5090 (32GB VRAM)** 或同级别显卡的 Windows/Linux PC 上。
* **显存占用**：
    * **Janus-Pro-7B**: 运行约占用 14GB 显存。
    * **FLUX.1-Dev**: 执行 Outpainting 任务建议保留充足显存。
* **软件环境**：Anaconda/Miniconda, Python 3.10+, CUDA 12.1+。

## 🧠 依赖模型清单
根据代码配置，本项目运行需提前下载并配置以下模型：

| 模型分类 | 模型名称 | 代码引用路径 (示例) | 功能说明 |
| :--- | :--- | :--- | :--- |
| **多模态理解** | **Janus-Pro-7B** | `.../Janus-Pro-7B` | 分析封面视觉元素，生成描述性 Prompt。 |
| **图像生成** | **flux1-dev.safetensors** | `unet_name` | 核心生成模型，负责封底和书脊的像素扩充。 |
| **VAE** | **ae.safetensors** | `vae_name` | 用于图像空间的编解码。 |
| **文本编码** | **clip_l.safetensors** | `clip_name1` | 基础文本编码器。 |
| **文本编码** | **t5xxl_fp8_e4m3fn.safetensors** | `clip_name2` | 高质量 T5 编码器，提升生成准确度。 |

## 📦 核心组件说明

### 1. Janus Vision API (`janus_api.py`)
* **模型**：DeepSeek Janus-Pro-7B。
* **职责**：接收封面图，通过视觉模型分析画面风格、色彩构图及环境元素，返回适合 ComfyUI 使用的英文 Prompt 标签。
* **默认端口**：`8788`。

### 2. FLUX Outpainting Client (`comfyui_flux_outpaint.py`)
* **后端**：需连接 ComfyUI API (`127.0.0.1:8188`)。
* **职责**：
    * **Step 1 (封底)**: 将封面图向左扩展生成“封底”内容。
    * **Step 2 (书脊)**: 提取封面左边缘，生成衔接自然的“书脊”窄条。
* **核心逻辑**：基于 FLUX.1-Dev 的 Inpainting 流程。

### 3. 自动化启动脚本 (`Janus_API.bat`)
* **功能**：一键激活名为 `janus` 的 Conda 环境，自动清理 GPU 显存残留，并启动 Flask 服务。

## 🚀 启动指南

### 环境准备
```bash
# 创建并激活环境
conda create -n janus python=3.10
conda activate janus
# 安装核心依赖
pip install torch torchvision transformers flask pillow requests
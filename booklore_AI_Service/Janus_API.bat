@echo off
chcp 65001 >nul
title Booklore Janus Vision API

echo ================================================
echo   Booklore Janus Vision API
echo   模型：Janus-Pro-7B
echo   端口：8788
echo ================================================
echo.

:: 激活 conda 环境
call conda activate janus
if errorlevel 1 (
    echo [错误] 无法激活 conda 环境 janus，请确认环境已创建
    pause
    exit /b 1
)

echo [OK] conda 环境 janus 已激活
echo.

:: 启动前清理 GPU 显存残留
echo [清理] 清理 GPU 显存缓存...
python -c "import torch; torch.cuda.empty_cache(); print('[清理] GPU 显存已清理，当前占用:', round(torch.cuda.memory_allocated()/1024**3, 2), 'GB')"
echo.

:: 切换到 booklore_AI 目录
cd /d E:\AI\booklore_AI_Service

:: 启动 Janus API
echo [启动] janus_api.py ...
echo [提示] 首次启动需要加载模型，约需 30-60 秒，请耐心等待
echo [提示] 启动成功后显示 "Running on http://0.0.0.0:8788"
echo.
python janus_api.py

if errorlevel 1 (
    echo.
    echo [错误] Janus API 异常退出，请检查上方错误信息
    pause
)
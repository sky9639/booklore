#!/bin/bash
# 验证 Docker 容器内的代码是否更新

echo "=========================================="
echo "验证 Docker 容器代码更新"
echo "=========================================="

# 1. 检查源代码
echo ""
echo "[1] 检查源代码中的权重..."
grep "ipadapter_weight.*1.0" //NAS/software/booklore/print-engine/claude_analyzer.py | head -2

# 2. 停止容器
echo ""
echo "[2] 停止容器..."
cd /vol2/1000/software/docker-compose/booklore
docker-compose stop print-engine

# 3. 删除旧镜像
echo ""
echo "[3] 删除旧镜像..."
docker rmi booklore-print-engine -f

# 4. 重新构建（不使用缓存）
echo ""
echo "[4] 重新构建镜像（无缓存）..."
docker-compose build --no-cache print-engine

# 5. 启动容器
echo ""
echo "[5] 启动容器..."
docker-compose up -d print-engine

# 6. 等待容器启动
echo ""
echo "[6] 等待容器启动..."
sleep 5

# 7. 验证容器内代码
echo ""
echo "[7] 验证容器内代码..."
docker exec booklore-print-engine-1 grep "ipadapter_weight.*1.0" /app/claude_analyzer.py | head -2

echo ""
echo "=========================================="
echo "验证完成！"
echo "=========================================="

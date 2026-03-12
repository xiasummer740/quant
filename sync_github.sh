#!/bin/bash
PROJECT_DIR="/var/www/quant.taikon.top"
cd $PROJECT_DIR

echo "=========================================="
echo "🚀 Quant V7.1.0 - 防截断开源同步向导"
echo "=========================================="

read -p "👤 请输入您的 GitHub 用户名 (如 xiasummer740): " GITHUB_USER
read -p "🔑 请粘贴您的 GitHub Token (无显示，直接回车): " -s RAW_TOKEN
echo ""

CLEAN_TOKEN=$(echo -n "$RAW_TOKEN" | tr -d '\r\n ')

if [ -z "$GITHUB_USER" ] || [ -z "$CLEAN_TOKEN" ]; then
    echo "❌ 错误：用户名或 Token 不能为空！"
    exit 1
fi

git config --global --add safe.directory $PROJECT_DIR
git config --global user.email "quantbot@taikon.top"
git config --global user.name "QuantBot"

git init
git add backend/main.py frontend/index.html sync_github.sh data/
git commit -m "🚀 Release V7.1.0: Prevent Vue ReferenceError & Unpkg Fix"
git branch -M main

git remote remove origin 2>/dev/null
git remote add origin "https://${GITHUB_USER}:${CLEAN_TOKEN}@github.com/xiasummer740/quant.git"

echo "[INFO] 正在发射修复版代码到 GitHub..."
git push -u origin main -f

echo "✅ 同步成功！"

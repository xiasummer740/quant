#!/bin/bash
PROJECT_DIR="/var/www/quant"
cd $PROJECT_DIR

echo "=========================================="
echo "🚀 Quant V11.0.0 - 全域漫游防污染同步向导"
echo "=========================================="

read -p "👤 请输入您的 GitHub 用户名 (如 xiasummer740): " GITHUB_USER </dev/tty
read -p "🔑 请粘贴您的 GitHub Token (ghp_开头，无显示直接回车): " -s RAW_TOKEN </dev/tty
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

# [核心防线] 强制清除已追踪的数据库文件，防止旧密码传到 GitHub
git rm -r --cached data/*.db 2>/dev/null
git rm -r --cached data/*.sqlite3 2>/dev/null

git add backend/main.py frontend/index.html install.sh sync_github.sh .gitignore README.md
git commit -m "🚀 Release V11.0.0: Auto SSL for Cloudflare & Nginx Multi-Tenant Safe Routing"
git branch -M main

git remote remove origin 2>/dev/null
git remote add origin "https://${GITHUB_USER}:${CLEAN_TOKEN}@github.com/xiasummer740/quant.git"

echo "[INFO] 正在发射纯净版代码到 GitHub..."
git push -u origin main -f

echo "=========================================="
echo "✅ 同步成功！包含你私人信息的数据库已被物理隔离，不会上传。"
echo "=========================================="

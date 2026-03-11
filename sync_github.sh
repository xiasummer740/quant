#!/bin/bash
PROJECT_DIR="/var/www/quant.taikon.top"
cd $PROJECT_DIR

echo "=========================================="
echo "🚀 Quant V5.3.1 - GitHub 源码同步向导"
echo "=========================================="
echo "为了防止 SSH 剪贴板溢出吞没您的输入，我们采用了安全的独立进程。"

read -p "👤 请输入您的 GitHub 用户名 (如 xiasummer740): " GITHUB_USER
read -p "🔑 请粘贴您的 GitHub Token (ghp_开头，输入时屏幕不会显示字符，直接回车): " -s RAW_TOKEN
echo ""

# 斩杀可能存在的隐藏回车符或空格
CLEAN_TOKEN=$(echo -n "$RAW_TOKEN" | tr -d '\r\n ')

if [ -z "$GITHUB_USER" ] || [ -z "$CLEAN_TOKEN" ]; then
    echo "❌ 错误：用户名或 Token 不能为空，同步被取消！"
    exit 1
fi

echo "[INFO] 正在初始化 Git 仓库并打包脱敏源码..."
git config --global --add safe.directory $PROJECT_DIR
git config --global user.email "quantbot@taikon.top"
git config --global user.name "QuantBot"

git init
git add backend/main.py frontend/index.html install.sh sync_github.sh README.md data/
git commit -m "🚀 Release V5.3.1: Vue Template Scope Fix & Interactive Sync"
git branch -M main

git remote remove origin 2>/dev/null
git remote add origin "https://${GITHUB_USER}:${CLEAN_TOKEN}@github.com/xiasummer740/quant.git"

echo "[INFO] 身份验证就绪，正在发射代码到 GitHub..."
git push -u origin main -f

echo "=========================================="
echo "✅ 同步成功！请前往您的 GitHub 页面验收！"
echo "=========================================="

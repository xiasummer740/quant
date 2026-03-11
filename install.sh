#!/bin/bash
echo "=========================================="
echo "🚀 欢迎使用 Quant Global AI Platform V5.3 一键安装向导"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
  echo "❌ 错误: 请使用 root 权限执行此脚本 (sudo bash install.sh)"
  exit
fi

read -p "👉 请输入您计划绑定的访问域名 (例如 quant.example.com，如果没有域名请直接按回车): " USER_DOMAIN
if [ -z "$USER_DOMAIN" ]; then
    USER_DOMAIN="localhost"
    echo "[提示] 您没有输入域名，将使用 localhost 作为默认配置。"
else
    echo "[提示] 您的域名已记录为: $USER_DOMAIN"
fi

echo "📦 正在安装系统基础依赖 (Python3, Git, Curl)..."
apt update && apt install -y python3-pip python3-venv curl

echo "🐍 正在创建并配置 Python 独立虚拟环境..."
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic requests apscheduler

echo "📂 正在创建 SQLite 数据库持久化目录..."
mkdir -p data
chmod -R 777 data

echo "⚙️ 正在将量化引擎注册为系统后台服务..."
CURRENT_DIR=$(pwd)

cat << SERVICE > /etc/systemd/system/quant-api.service
[Unit]
Description=Quant AI Backend API
After=network.target

[Service]
User=root
WorkingDirectory=$CURRENT_DIR/backend
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable quant-api
systemctl restart quant-api

echo "=========================================="
echo "🎉 部署已全部完成！引擎已在后台启动！"
echo "=========================================="
echo "🌐 【网络配置指南】"
echo "请在您的 Nginx 配置文件中加入以下内容来绑定您的域名:"
echo "----------------------------------------"
echo "server {"
echo "    listen 80;"
echo "    server_name $USER_DOMAIN;"
echo ""
echo "    location / {"
echo "        root $CURRENT_DIR/frontend;"
echo "        index index.html;"
echo "        try_files \$uri \$uri/ /index.html;"
echo "    }"
echo ""
echo "    location /api/ {"
echo "        proxy_pass http://127.0.0.1:8000;"
echo "        proxy_set_header Host \$host;"
echo "        proxy_set_header X-Real-IP \$remote_addr;"
echo "    }"
echo "}"
echo "----------------------------------------"
echo "配置完成后执行 'nginx -s reload' 即可访问！"
echo "=========================================="
echo "🔐 初始控制台登录密码为: admin123"
echo "🔐 初始系统设置解锁密码: admin123"
echo "⚠️  (登入系统后请务必在底部的【系统配置】中独立修改双重密码)"
echo "=========================================="

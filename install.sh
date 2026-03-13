#!/bin/bash
echo "=========================================="
echo "🚀 欢迎使用 Quant Global AI Platform V10.1 一键安装向导"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
  echo "❌ 错误: 请使用 root 权限执行此脚本 (sudo bash install.sh)"
  exit
fi

# [全自动 Nginx 接管逻辑]
read -p "👉 1/1 请输入您计划绑定的访问域名 (例如 quant.example.com，如果没有域名请直接按回车): " USER_DOMAIN </dev/tty
if [ -z "$USER_DOMAIN" ]; then
    USER_DOMAIN="_"
    echo "[提示] 您没有输入域名，将使用服务器公网 IP 直接访问。"
else
    echo "[提示] 您的域名已记录为: $USER_DOMAIN"
fi

echo "📦 正在安装系统基础依赖 (Python3, Git, Curl, Nginx)..."
apt update && apt install -y python3-pip python3-venv curl nginx

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

echo "🌐 正在自动配置 Nginx 反向代理..."
rm -f /etc/nginx/sites-enabled/default

cat << NGINX_CONF > /etc/nginx/sites-available/quant.conf
server {
    listen 80;
    server_name $USER_DOMAIN;

    location / {
        root $CURRENT_DIR/frontend;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX_CONF

ln -sf /etc/nginx/sites-available/quant.conf /etc/nginx/sites-enabled/
systemctl restart nginx

echo "=========================================="
echo "🎉 部署已全部完成！引擎与 Nginx 已在后台启动！"
echo "=========================================="
if [ "$USER_DOMAIN" != "_" ]; then
    echo "👉 请立刻打开浏览器访问: http://$USER_DOMAIN"
else
    echo "👉 请立刻打开浏览器访问您的服务器公网 IP 地址。"
fi
echo "=========================================="
echo "🔐 初始控制台登录密码为: admin123"
echo "🔐 初始系统设置解锁密码: admin123"
echo "⚠️  (登入系统后请务必在底部的【系统配置】中独立修改双重密码)"
echo "=========================================="

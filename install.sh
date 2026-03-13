#!/bin/bash
echo "=========================================="
echo "🚀 欢迎使用 Quant Global AI Platform V24.0 一键安装向导"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
  echo "❌ 错误: 请使用 root 权限执行此脚本 (sudo bash install.sh)"
  exit
fi

read -p "👉 1/1 请输入您计划绑定的访问域名 (如 quant.taikon.top，无域名请按回车): " USER_DOMAIN </dev/tty
if [ -z "$USER_DOMAIN" ]; then
    USER_DOMAIN="_"
    echo "[提示] 您没有输入域名，将使用服务器公网 IP 直接访问。"
else
    echo "[提示] 您的域名已记录为: $USER_DOMAIN"
fi

echo "📦 正在安装系统基础依赖 (Python3, Git, Nginx, OpenSSL)..."
apt update && apt install -y python3-pip python3-venv curl nginx openssl

echo "🔐 正在为您生成用于 Cloudflare 完全模式通讯的 SSL 证书..."
mkdir -p /etc/ssl/private /etc/ssl/certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/quant_selfsigned.key \
    -out /etc/ssl/certs/quant_selfsigned.crt \
    -subj "/C=CN/ST=State/L=City/O=QuantEngine/CN=$USER_DOMAIN" 2>/dev/null

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
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable quant-api
systemctl restart quant-api

echo "🌐 正在自动配置 Nginx 并注入 300s 防超时装甲..."
rm -f /etc/nginx/sites-enabled/default

cat << NGINX_CONF > /etc/nginx/sites-available/quant.conf
server {
    listen 80;
    listen 443 ssl;
    server_name $USER_DOMAIN;

    ssl_certificate /etc/ssl/certs/quant_selfsigned.crt;
    ssl_certificate_key /etc/ssl/private/quant_selfsigned.key;

    location / {
        root $CURRENT_DIR/frontend;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
NGINX_CONF

ln -sf /etc/nginx/sites-available/quant.conf /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

echo "=========================================="
echo "🎉 部署已全部完成！引擎与 Nginx 已在后台启动！"
echo "=========================================="
if [ "$USER_DOMAIN" != "_" ]; then
    echo "👉 请立刻打开浏览器访问: http://$USER_DOMAIN (使用 Cloudflare 请直接访问 https)"
else
    echo "👉 请立刻打开浏览器访问您的服务器公网 IP 地址。"
fi
echo "=========================================="
echo "🔐 初始控制台登录密码为: admin123"
echo "🔐 初始系统设置解锁密码: admin123"
echo "⚠️  (登入系统后请务必修改双重密码)"
echo "=========================================="

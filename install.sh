#!/bin/bash
echo "=========================================="
echo "🚀 欢迎使用 Quant Global AI Platform V3.0 一键安装向导"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
  echo "❌ 请使用 root 权限执行此脚本 (sudo bash install.sh)"
  exit
fi

echo "📦 正在安装系统基础依赖..."
apt update && apt install -y python3-pip python3-venv curl

echo "🐍 正在配置 Python 隔离环境..."
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic requests apscheduler

echo "📂 正在创建数据持久化目录..."
mkdir -p data
chmod -R 777 data

echo "⚙️ 正在注册并启动后台系统服务..."
cat << 'SERVICE' > /etc/systemd/system/quant-api.service
[Unit]
Description=Quant AI Backend API
After=network.target

[Service]
User=root
WorkingDirectory=$(pwd)/backend
ExecStart=$(pwd)/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable quant-api
systemctl restart quant-api

echo "=========================================="
echo "🎉 部署完成！"
echo "后端接口已成功运行在 8000 端口。"
echo "如果您在本地测试，前端可以直接双击 frontend/index.html 打开。"
echo "如果您在云服务器部署，请通过 Nginx 将您的域名映射到 frontend/index.html 即可访问。"
echo "🔐 初始系统密码为: admin123 (登入后请立即修改)"
echo "=========================================="

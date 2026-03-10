# Quant Global AI Platform V2.1.1 🚀

这是一个顶级的事件驱动型量化交易系统。它通过抓取全球宏观经济数据、机构研报预期以及社交舆情热度，利用大语言模型（如 DeepSeek, GPT-4）进行多因子共振分析，并自动挖掘出潜力个股，最后结合 Python 实时获取的均线等技术面数据动态计算买卖区间。

## 🌟 核心特性
- **📰 全息舆情矩阵**：自动抓取并对新闻打标签（突发公告 / 机构研报 / 舆情热度）。
- **🧠 12D 深度透视引擎**：对单只股票进行 12 个维度（宏观、基本面、资金、机构等）的实时 AI 穿透解析，并附带明确的技术面价格依据。
- **📊 专业级盘口数据墙**：K 线图内置媲美专业炒股软件的盘口数据（利用腾讯高速行情 API，彻底告别被墙的雅虎）。
- **🧭 资本罗盘防线**：支持设置“大/中/小盘股”偏好，以及日均成交资金量红线，AI 选股严守纪律。
- **🤖 盘中全自动巡航**：设定倒计时，解放双手，自动完成 `抓取 -> 推演 -> 算价 -> 存库 -> 微信/TG垂直战报推送` 全链路。
- **🛡️ 纯净前端防黑屏架构**：采用极简纯净的原生 Vue 加载架构，避免与任何广告拦截器发生冲突。

---

## 🛠️ 一键 Bash 部署教程

无论您是部署在 HK (香港) 还是美国 (US) VPS，只需复制以下整段代码，在终端中粘贴并回车，即可全自动完成部署（包括前后端与环境搭建）。

~~~bash
#!/bin/bash
apt update && apt install -y python3-pip python3-venv git curl
mkdir -p /var/www/quant.taikon.top
cd /var/www/quant.taikon.top

# 获取最新开源代码
git clone https://github.com/xiasummer740/quant.git .

# 配置 Python 虚拟环境与依赖
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic requests apscheduler

# 创建持久化数据库目录
mkdir -p /var/www/quant.taikon.top/data
chmod 777 /var/www/quant.taikon.top/data

# 注册并启动 Systemd 服务
cat << 'SERVICE' > /etc/systemd/system/quant-api.service
[Unit]
Description=Quant AI Backend API
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/quant.taikon.top/backend
ExecStart=/var/www/quant.taikon.top/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable quant-api
systemctl restart quant-api

echo "🎉 部署完成！"
echo "后端接口运行在 8000 端口。"
echo "前端页面请通过 Nginx 将您的域名映射到 /var/www/quant.taikon.top/frontend/index.html 即可访问。"
~~~

---

## 🔐 默认账号密码
- 初始密码：`admin123`
- *安全提示：部署成功并进入系统后，请立刻在【⚙️系统配置】的底端修改门禁密码。修改后 `admin123` 将永久失效！*

## ⚙️ 配置文件持久化说明
系统基于后端的 SQLite 进行配置持久化（数据文件位于 `data/quant.db`）。
由于所有用户的敏感数据（如 API Key, WxPusher UID）已在代码中被设为空字符串 `''` 进行脱敏处理，**您可以在任意电脑或手机上访问配置好的域名，修改后实时保存至云端服务器，无需每换一台设备就重新配置一次。**

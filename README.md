# 🌐 Global Quant AI (全球多模态量化投研中心)

这是一款基于 **大模型 (LLM) + 多模态视觉 (Vision) + 全球舆情雷达 + 多因子量价模型** 的顶级 A 股量化交易中枢系统。
系统采用“云端 AI 大脑 (VPS) + 移动端极速推送 + 本地自动化交易 (QMT/RPA)” 的分布式解耦架构。

## 🎯 核心特性 (Core Features)

* **🌍 7x24 全球宏观映射**：双总线并发监听财联社国内快讯与新浪 7x24 海外宏观动态，AI 自动完成“海外大事件 -> A股对应受惠板块”的跨市场物理降维映射。
* **🧠 多模态沙盒推演**：支持直接上传券商研报截图、K线图表，调用 Gemini 1.5 Pro / GLM-4V 视觉大模型进行底层逻辑拆解与胜率评分。
* **🛡️ 资产级物理熔断**：内置 API Token 实时监控油表，超过每日设定的消耗阈值（防恶意消耗/死循环）立即物理拔网线停机；内置上证指数 MA20 大盘风控，熊市单边下跌自动熔断锁仓。
* **🔬 Pandas 多因子严选**：不仅评估 AI 情绪，更叠加基本面 (PE<50, PB<5) 与高级技术面 (MA20+MACD共振 / KDJ+BOLL极限防追高) 的双重过滤。
* **👥 散户情绪共振**：每 5 分钟静默抓取东方财富/雪球全网热度榜，寻找“游资点火+散户跟风+AI逻辑”的终极共振标的。
* **📱 移动端保姆级辅助**：通过 Telegram / WxPusher 实现毫秒级买单推送，并动态计算提供建仓价、止损位 (MA20下浮)、止盈位 (BOLL上轨)。

## 📂 核心目录结构及详细释义 (Project Structure)

~~~text
quant_system/
├── 云端核心引擎 (部署于 Linux VPS)
│   ├── main.py                 # 🚀 核心后端守护进程 (FastAPI + AkShare + LLM API + Redis Pub/Sub)
│   ├── index.html              # 📊 前端商业级多标签控制台 (Vue3 + TailwindCSS, 0路由纯静态高防泄露)
│   ├── db_maintenance.py       # 🧹 数据库自维护脚本 (保留30天历史信号，防止MongoDB膨胀)
│   ├── system_maintenance.sh   # 🛠️ 系统级大扫除脚本 (清理Nginx日志/Systemd日志/APT缓存)
│   └── .gitignore              # 🔒 Git 脱敏配置文件
│
└── 本地实盘四肢 (部署于 Windows 个人电脑，按需二选一)
    ├── 路线一：全自动 QMT 机构接口
    │   ├── real_qmt_full.py    # 💼 华西证券 QMT 全真投研端实盘打单脚本 (依赖 xtquant)
    │   ├── start_hidden.vbs    # 👻 VBS 隐形启动器 (后台无黑窗口静默监听云端 Redis)
    │   └── stop_hidden.bat     # 🔪 进程猎杀器 (安全精准终结本地 QMT 监听进程)
    │
    └── 路线二：零门槛 RPA 散户通道
        └── ths_rpa_receiver.py # 🤖 同花顺 PC 独立下单客户端 RPA 模拟键鼠自动化买入 (依赖 easytrader)
~~~

## ⚙️ 快速部署与启动 (Quick Start)

### 1. 云端大脑部署 (Linux Ubuntu 22.04+)
~~~bash
# 激活虚拟环境并安装极客依赖
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn motor akshare pandas pydantic python-dotenv openai zhipuai requests aiohttp google-generativeai anthropic redis pytz python-multipart

# 启动核心后台
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
~~~

### 2. 挂载自动化清理守护进程 (CronJob)
~~~bash
crontab -e
# 添加以下任务，每天凌晨 3 点自动清理冗余数据保护服务器磁盘
0 3 * * * /var/www/quant_system/system_maintenance.sh
~~~

## ⚠️ 免责声明 (Disclaimer)
本项目源码仅供量化代码学习、AI 大模型金融场景应用交流。不构成任何投资建议，请在沙盒环境下充分回测后谨慎使用于实盘资金。

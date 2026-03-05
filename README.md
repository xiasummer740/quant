# 🌐 Global Quant AI (全球多模态量化投研中心)

这是一款基于 **大模型 (LLM) + 多模态视觉 (Vision) + 全球舆情雷达 + 多因子量价模型** 的顶级 A 股量化交易中枢系统。
系统采用“云端 AI 大脑 (VPS) + 移动端极速推送 + 本地自动化交易 (QMT/RPA)” 的分布式解耦架构。

## 🎯 核心特性 (Core Features)

* **🌍 7x24 全球宏观映射**：双总线并发监听财联社国内快讯与新浪 7x24 海外宏观动态，AI 自动完成跨市场物理降维映射。
* **🧠 多模态沙盒推演**：支持直接上传券商研报截图、K线图表，调用视觉大模型进行底层逻辑拆解与胜率评分。
* **🛡️ 资产级物理熔断**：内置 API Token 实时监控油表；内置上证指数 MA20 大盘风控，熊市单边下跌自动熔断锁仓。
* **🔬 Pandas 多因子严选**：不仅评估 AI 情绪，更叠加基本面 (PE<50, PB<5) 与高级技术面 (MA20+MACD / KDJ+BOLL) 的双重过滤。
* **👥 散户情绪共振**：每 5 分钟静默抓取东方财富/雪球全网热度榜，寻找“游资点火+散户跟风+AI逻辑”的终极共振标的。
* **📱 移动端保姆级辅助**：通过 Telegram / WxPusher 实现毫秒级买单推送，并动态计算提供建仓价、止损位 (MA20)、止盈位 (BOLL上轨)。

## 📝 路线一：每日 3 分钟标准作业流程 (SOP)

为资金在 5 万以下的量化玩家量身定制的“手机半自动”极客流程：

~~~text
⏰ 盘前 (09:00-09:15) | 耗时 1 分钟
1. 登入 Web UI，确认引擎状态为 🟢 运行中。
2. 查看【跨市场情报侦测日志】，验收昨夜全球宏观(美联储/外盘)对今日 A 股的推演映射。
3. 关闭“无视休盘”开关，恢复交易时段智能休眠以节省 API Token。

📱 盘中 (09:15-15:00) | 耗时 1 分钟
1. 关闭炒股软件，杜绝人工盯盘，交由云端 VPS 与大模型接管情绪风控与多因子算力。
2. 仅在收到微信 WxPusher 报警推送时掏出手机。
3. 依照推送的详细战报，在同花顺 APP 中精准买入，并立刻根据推送的【🛑止损位】与【🎯止盈位】挂入条件单，随后锁屏离手。

📊 盘后 (15:30 以后) | 耗时 1 分钟
1. 进入 Web 控制台【🧪 沙盒与回测】页，一键运行 7 日历史绩效回测。
2. 评估 AI 喊单的 3 日内最高涨幅与极值回撤。
3. 依据报表胜率，决定次日是否在配置页收紧风控（如开启大盘熔断或技术面极值过滤）。
~~~

## 📂 核心目录结构及详细释义 (Project Structure)

~~~text
quant_system/
├── 云端核心引擎 (部署于 Linux VPS)
│   ├── main.py                 # 🚀 核心后端守护进程 (FastAPI + AkShare + LLM API + Redis)
│   ├── index.html              # 📊 前端商业级多标签控制台 (Vue3 + TailwindCSS, 纯静态防泄露)
│   ├── db_maintenance.py       # 🧹 数据库自维护脚本 (保留30天历史信号)
│   ├── system_maintenance.sh   # 🛠️ 系统级大扫除脚本 (清理Nginx/Systemd日志/APT缓存)
│   └── .gitignore              # 🔒 Git 脱敏配置文件
│
└── local_node_templates/ (本地实盘四肢模板，部署于 Windows)
    ├── qmt_receiver_template.py # 💼 华西证券 QMT 全真投研端实盘打单脚本 (依赖 xtquant)
    ├── ths_rpa_template.py      # 🤖 同花顺 PC 独立下单客户端 RPA 自动化买入 (依赖 easytrader)
    └── install_windows_env.bat  # 📦 Windows Python 本地环境一键安装包
~~~

## ⚙️ 快速部署 (Quick Start)

~~~bash
# 激活虚拟环境并安装极客依赖
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn motor akshare pandas pydantic python-dotenv openai zhipuai requests aiohttp google-generativeai anthropic redis pytz python-multipart

# 启动核心后台
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
~~~

## ⚠️ 免责声明 (Disclaimer)
本项目源码仅供量化代码学习、AI 大模型金融场景应用交流。不构成任何投资建议，请在沙盒环境下充分回测后谨慎使用于实盘资金。

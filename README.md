# 🌐 Global Quant AI (全球多模态量化投研中心)

这是一款基于 **大模型 (LLM) + 多模态视觉 (Vision) + 全球舆情雷达 + 多因子量价模型** 的顶级 A 股量化交易中枢系统。
系统采用“云端 AI 大脑 (VPS) + 移动端极速推送 + 本地自动化交易 (QMT/RPA)” 的分布式解耦架构。

## 🎯 核心特性 (Core Features)

* **💰 资金面门槛定制**：内置细分价格区间档位快选。物理隔离科创板(688)、创业板(300)、北交所权限。获取板块全体成分股后，再进行资金漏斗过滤！
* **🌍 7x24 全球宏观映射**：采用富途牛牛/华尔街见闻双总线并发监听，无视海外IP防火墙，大模型仅被允许输出标准字典板块，100%匹配命中！
* **🛡️ 资产级物理熔断**：内置 API Token 实时监控油表；大盘跌破 MA20 自动熔断锁仓。AI 决策全透明打印。
* **🔬 Pandas 多因子严选**：不仅评估 AI 情绪 (>0.7) 与胜率 (>80%)，更叠加基本面 (PE/PB) 与高级技术面 (MACD金叉/无破位) 过滤。
* **📱 移动端保姆级辅助**：动态计算提供建仓价、止损位 (MA20)、止盈位 (BOLL上轨)，微信/Telegram 极速推送，每次精选最多5只优股防轰炸。

## 📝 每日 3 分钟标准作业流程 (SOP)

~~~text
⏰ 盘前 (09:00-09:15) | 耗时 1 分钟
1. 登入 Web UI，确认引擎状态为 🟢 运行中。
2. 查看【跨市场情报侦测日志】，验收昨夜全球宏观(美联储/外盘)对今日 A 股的推演映射。
3. 关闭“无视休盘”开关，恢复交易时段智能休眠以节省 API Token。

📱 盘中 (09:15-15:00) | 耗时 1 分钟
1. 仅在收到微信报警推送时掏出手机，彻底告别情绪盯盘。
2. 依照推送战报中的建议价位买入，并立刻挂入条件单 (止损/止盈位)，随后锁屏离手。

📊 盘后 (15:30 以后) | 耗时 1 分钟
1. 进入 Web 控制台【🧪 沙盒与回测】页，一键运行 7 日历史绩效回测，评估历史胜率。
~~~

## 📂 核心目录结构及详细释义 (Project Structure)

~~~text
quant_system/
├── 云端核心引擎 (部署于 Linux VPS)
│   ├── main.py                 # 🚀 核心后端守护进程 (FastAPI + AkShare + LLM API + Redis)
│   ├── index.html              # 📊 前端商业级多标签控制台 (Vue3 + TailwindCSS)
│   └── .gitignore              # 🔒 Git 脱敏配置文件
│
└── local_node_templates/ (本地实盘四肢模板)
    ├── qmt_receiver_template.py # 💼 券商 QMT 全真投研端实盘打单脚本
    ├── ths_rpa_template.py      # 🤖 同花顺独立下单客户端 RPA 自动化买入
    └── install_windows_env.bat  # 📦 Windows 本地环境一键安装包
~~~

## ⚙️ 快速部署 (Quick Start)

~~~bash
# 激活虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn motor akshare pandas pydantic python-dotenv openai zhipuai requests aiohttp google-generativeai anthropic redis pytz python-multipart

# 启动核心后台
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
~~~

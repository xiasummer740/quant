from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import os
import json
import requests
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI(title="Quant Engine API V8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, mode=0o777)
DB_PATH = os.path.join(DATA_DIR, "quant.db")

scheduler = BackgroundScheduler()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analysis_results (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS news_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS deep_analysis_history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, code TEXT, name TEXT, content TEXT)''')
    
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('console_password', 'admin123')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('settings_password', 'admin123')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('session_token', 'init_token_xyz')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('watchlist', '[]')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('preferred_sectors', '🔥 当下市场最热题材/板块 (AI自动捕捉)')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_price', '1.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_price', '200.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_buy_distance', '5.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('refresh_interval', '300')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cap_preference', '全部')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_volume', '0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('trading_style', '中长线')")
    
    conn.commit()
    conn.close()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in ["/api/login", "/api/verify_settings", "/api/verify"]:
        auth_header = request.headers.get("Authorization")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        token_row = c.execute("SELECT value FROM settings WHERE key='session_token'").fetchone()
        conn.close()
        valid_token = token_row[0] if token_row else "invalid"
        if not auth_header or auth_header != f"Bearer {valid_token}":
            return JSONResponse(status_code=401, content={"detail": "Unauthorized: 门禁拦截"})
    return await call_next(request)

class LoginReq(BaseModel):
    password: str

@app.post("/api/login")
def login_console(req: LoginReq):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    pwd_row = c.execute("SELECT value FROM settings WHERE key='console_password'").fetchone()
    real_pwd = pwd_row[0] if pwd_row else "admin123"
    
    if req.password == real_pwd:
        new_token = secrets.token_hex(16)
        c.execute("REPLACE INTO settings (key, value) VALUES ('session_token', ?)", (new_token,))
        conn.commit()
        conn.close()
        return {"status": "success", "token": new_token}
    conn.close()
    return {"status": "error", "message": "控制台密码错误"}

@app.post("/api/verify_settings")
def verify_settings_pwd(req: LoginReq):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    pwd_row = c.execute("SELECT value FROM settings WHERE key='settings_password'").fetchone()
    conn.close()
    real_pwd = pwd_row[0] if pwd_row else "admin123"
    if req.password == real_pwd: return {"status": "success"}
    return {"status": "error", "message": "配置核心密码错误"}

@app.get("/api/verify")
def verify_token(request: Request):
    auth_header = request.headers.get("Authorization")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    token_row = c.execute("SELECT value FROM settings WHERE key='session_token'").fetchone()
    conn.close()
    valid_token = token_row[0] if token_row else "invalid"
    if auth_header and auth_header == f"Bearer {valid_token}": return {"status": "success"}
    return JSONResponse(status_code=401, content={"detail": "Invalid Token"})

class PwdChangeReq(BaseModel):
    pwd_type: str
    old_pwd: str
    new_pwd: str

@app.post("/api/change_password")
def change_password(req: PwdChangeReq):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    target_key = 'console_password' if req.pwd_type == 'console' else 'settings_password'
    pwd_row = c.execute(f"SELECT value FROM settings WHERE key='{target_key}'").fetchone()
    real_pwd = pwd_row[0] if pwd_row else "admin123"
    
    if req.old_pwd == real_pwd:
        c.execute(f"REPLACE INTO settings (key, value) VALUES ('{target_key}', ?)", (req.new_pwd,))
        if req.pwd_type == 'console':
            c.execute("REPLACE INTO settings (key, value) VALUES ('session_token', 'reset_token')")
        conn.commit()
        conn.close()
        return {"status": "success"}
    conn.close()
    return {"status": "error", "message": "原密码错误"}

def send_push(json_str: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        settings = {row[0]: row[1] for row in c.execute("SELECT key, value FROM settings").fetchall()}
        conn.close()

        data = json.loads(json_str)
        sector = data.get("sector", "N/A")
        prob = data.get("probability", "N/A")
        style = data.get("trading_style", "中长线")
        stocks_list = data.get("stocks", [])
        
        msg_lines = [
            f"📈 【量化策略已更新】",
            f"🎯 优选板块: {sector}",
            f"🧭 交易风格: {style}",
            f"📊 板块热度: {prob}",
            "━━━━━━━━━━━━━━━━"
        ]

        if not stocks_list:
            msg_lines.append("⚠️ 无符合风控要求的个股")
        else:
            for s in stocks_list:
                name = s.get('name', '未知')
                code = s.get('code', '未知')
                cp = s.get('current_price', '获取中')
                br = s.get('buy_range', '计算中')
                st = s.get('sell_target', '计算中')
                tp = s.get('take_profit_target', '格局持有')
                ind_prob = s.get('probability', prob)
                
                msg_lines.append(f"🔥 【{name}】 ({code}) [个股胜率:{ind_prob}]")
                msg_lines.append(f"   💵 现价: {cp}")
                msg_lines.append(f"   💰 买入: {br}")
                msg_lines.append(f"   ⚠️ 止损: {st}")
                msg_lines.append(f"   🚀 目标: {tp}")
                msg_lines.append("--------------------")

        msg_body = "\n".join(msg_lines)
        
        tg_token = settings.get("tg_bot_token", "").strip()
        tg_chat_id = settings.get("tg_chat_id", "").strip()
        if tg_token and tg_chat_id:
            try: requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", data={"chat_id": tg_chat_id, "text": msg_body}, timeout=5)
            except: pass

        wechat_key = settings.get("wechat_webhook", "").strip()
        if wechat_key:
            try: requests.post(f"https://sctapi.ftqq.com/{wechat_key}.send", data={"title": f"📈 {style}-{sector}策略已更新", "desp": msg_body}, timeout=5)
            except: pass

        wxpusher_token = settings.get("wxpusher_app_token", "").strip()
        wxpusher_uid = settings.get("wxpusher_uid", "").strip()
        if wxpusher_token and wxpusher_uid:
            try:
                wp_url = "https://wxpusher.zjiecode.com/api/send/message"
                wp_payload = {"appToken": wxpusher_token, "content": msg_body, "summary": f"📈 {style}-{sector}量化更新", "contentType": 1, "uids": [wxpusher_uid]}
                requests.post(wp_url, json=wp_payload, headers={'Content-Type': 'application/json'}, timeout=5)
            except: pass
    except: pass

def is_market_relevant(text: str) -> bool:
    keywords = ['股', '市', '券商', '央行', '外汇', '经济', '利好', '利空', '涨停', '跌停', '指数', '美联储', '利率', 'CPI', '大盘', '主力', '资金', '财报', '重组', '政策', '部委', '发改委', '国务院', '补贴', '关税', '制裁', '贸易战', '原油', '黄金', '新能源', '半导体', 'AI', '算力', '地产', '证监会', 'IPO', '融资', '减持', '增持', '汇率', '降息', '降准', '订单', '中标', '研发', '突破', '会议', '规划', '非农', '热议', '评级', '目标价']
    for kw in keywords:
        if kw in text: return True
    return False

def get_news_type(title: str) -> str:
    if any(k in title for k in ['公告', '停牌', '复牌', '财报', '重组', '中标', '立案', '新规']): return "突发公告/政策"
    elif any(k in title for k in ['研报', '评级', '买入', '增持', '目标价', '预测', '机构认为']): return "机构研报预期"
    elif any(k in title for k in ['热议', '股吧', '雪球', '网友', '炸板', '跳水', '涨停', '疯抢', '恐慌']): return "社交舆情热度"
    return "宏观与行业事件"

def internal_fetch_news():
    raw_news = []
    filtered_news = []
    headers = {'User-Agent': 'Mozilla/5.0 Chrome/122.0.0.0 Safari/537.36', 'Referer': 'https://finance.sina.com.cn/'}
    
    try:
        url_macro = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152"
        res_macro = requests.get(url_macro, headers=headers, timeout=10)
        feed_macro = res_macro.json().get("result", {}).get("data", {}).get("feed", {}).get("list", [])
    except: feed_macro = []

    try:
        url_ashare = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=153"
        res_ashare = requests.get(url_ashare, headers=headers, timeout=10)
        feed_ashare = res_ashare.json().get("result", {}).get("data", {}).get("feed", {}).get("list", [])
    except: feed_ashare = []
        
    all_feeds = feed_macro + feed_ashare
    seen_ids = set()
    
    for item in all_feeds:
        doc_id = item.get("id", "")
        if doc_id in seen_ids: continue
        seen_ids.add(doc_id)
        
        raw_text = item.get("rich_text", "") or item.get("text", "")
        clean_text = re.sub(r'<[^>]+>', '', raw_text)
        link = item.get("docurl", "")
        if not link or link.strip() == "": link = item.get("short_url", "https://finance.sina.com.cn/7x24/")
        pubDate = item.get("create_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        if clean_text:
            raw_news.append({"title": clean_text[:200], "link": link, "pubDate": pubDate, "source": "新浪7x24实时源"})

    try:
        em_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
        em_url = "https://reportapi.eastmoney.com/report/list?pageSize=20&pageNo=1&qType=0"
        res_em = requests.get(em_url, headers=em_headers, timeout=5)
        reports = res_em.json().get("data", [])
        for r in reports:
            title = f"【研报覆盖】{r.get('title')} - 真实机构:{r.get('orgSName')} 给出真实评级:{r.get('emRatingName')}"
            link = f"https://data.eastmoney.com/report/zw_stock.jshtml?encodeUrl={r.get('infoCode')}"
            pubDate = r.get('publishDate', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            if 'T' in pubDate: pubDate = pubDate.replace('T', ' ')
            raw_news.append({"title": title, "link": link, "pubDate": pubDate, "source": "东财研报直连"})
    except: pass
        
    seen_titles = set()
    for news in raw_news:
        if is_market_relevant(news['title']):
            t_key = news['title'][:20]
            if t_key not in seen_titles:
                seen_titles.add(t_key)
                news['type'] = get_news_type(news['title'])
                filtered_news.append(news)
            
    filtered_news = sorted(filtered_news, key=lambda x: x['pubDate'], reverse=True)[:45]
    if not filtered_news: return {"status": "error", "message": "未能获取到任何有效全息资讯。"}

    try:
        clean_news_json = json.dumps(filtered_news, ensure_ascii=False)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM news_cache")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO news_cache (timestamp, content) VALUES (?, ?)", (timestamp, clean_news_json))
        conn.commit()
        conn.close()
        return {"status": "success", "data": f"✅ 成功构建全息情报矩阵，含研报/公告/舆情共 {len(filtered_news)} 条。", "raw_snippet": str(filtered_news[:1])}
    except Exception as e: return {"status": "error", "message": f"数据入库异常: {str(e)}"}

def format_ticker(ticker: str) -> str:
    num_match = re.search(r'\d+', ticker)
    eng_match = re.search(r'[A-Za-z]+', ticker)
    clean_ticker = ""
    if num_match:
        code = num_match.group()
        if len(code) == 6:
            if code.startswith('6') or code.startswith('9'): t_code = f"sh{code}"
            else: t_code = f"sz{code}"
        elif len(code) == 5: t_code = f"hk{code}"
        elif len(code) <= 4: t_code = f"hk{code.zfill(5)}"
        else: t_code = code
        return t_code
    elif eng_match: return f"us{eng_match.group().lower()}"
    return ticker

@app.get("/api/quote/{ticker}")
def get_quick_quote(ticker: str):
    t_code = format_ticker(ticker)
    try:
        res = requests.get(f"http://qt.gtimg.cn/q={t_code}", timeout=5)
        if res.status_code == 200 and '="~' not in res.text:
            data_str = res.text.split('="')[1].split('";')[0]
            cols = data_str.split('~')
            if len(cols) > 40:
                price = float(cols[3])
                prev = float(cols[4])
                open_price = float(cols[5])
                volume = float(cols[36]) * 100
                high = float(cols[33])
                low = float(cols[34])
                market_cap = cols[45] 
                pe = cols[39] 
                pb = cols[46] 
                change_percent = float(cols[32])
                
                turnover = cols[38] if len(cols)>38 and cols[38] else '--'
                amplitude = cols[43] if len(cols)>43 and cols[43] else '--'
                vol_ratio = cols[49] if len(cols)>49 and cols[49] else '--'
                
                mc_str = f"{market_cap}亿" if market_cap and market_cap != "" else "--"
                
                return {
                    "status": "success", 
                    "price": round(price, 2), 
                    "change_percent": change_percent,
                    "market_cap": mc_str,
                    "pe": pe if pe else '--',
                    "pb": pb if pb else '--',
                    "volume": volume,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "prev": prev,
                    "turnover": turnover,
                    "amplitude": amplitude,
                    "vol_ratio": vol_ratio
                }
    except Exception as e: pass
    
    try:
        y_code = ticker
        if t_code.startswith("sh"): y_code = t_code[2:] + ".SS"
        elif t_code.startswith("sz"): y_code = t_code[2:] + ".SZ"
        elif t_code.startswith("hk"): y_code = t_code[2:] + ".HK"
        headers = {'User-Agent': 'Mozilla/5.0'}
        chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{y_code}?interval=1d&range=1d"
        chart_res = requests.get(chart_url, headers=headers, timeout=5)
        if chart_res.status_code == 200:
            meta = chart_res.json()['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice', 0)
            prev = meta.get('chartPreviousClose', price)
            change_percent = ((price - prev) / prev) * 100 if prev else 0
            return {
                "status": "success", "price": round(price, 2), "change_percent": round(change_percent, 2),
                "market_cap": "--", "pe": "--", "pb": "--", 
                "volume": meta.get('regularMarketVolume', '--'),
                "open": "--", "high": "--", "low": "--", "prev": prev,
                "turnover": "--", "amplitude": "--", "vol_ratio": "--"
            }
    except: pass
    return {"status": "error"}

def internal_get_quick_quote(ticker: str):
    res = get_quick_quote(ticker)
    if res.get('status') == 'success': return res.get('price', -1)
    return -1

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def internal_get_stock_tech_basis(ticker: str):
    try:
        y_code = ticker
        t_code = format_ticker(ticker)
        if t_code.startswith("sh"): y_code = t_code[2:] + ".SS"
        elif t_code.startswith("sz"): y_code = t_code[2:] + ".SZ"
        elif t_code.startswith("hk"): y_code = t_code[2:] + ".HK"
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{y_code}?interval=1d&range=3mo", headers=headers, timeout=5)
        if res.status_code == 200:
            inds = res.json()['chart']['result'][0]['indicators']['quote'][0]
            closes = [c for c in inds.get('close', []) if c is not None]
            highs = [h for h in inds.get('high', []) if h is not None]
            lows = [l for l in inds.get('low', []) if l is not None]
            volumes = [v for v in inds.get('volume', []) if v is not None]
            
            if len(closes) >= 20:
                recent_high = max(highs[-20:])
                recent_low = min(lows[-20:])
                ma5 = sum(closes[-5:])/5
                ma20 = sum(closes[-20:])/20
                ma5_prev = sum(closes[-6:-1])/5
                ma20_prev = sum(closes[-21:-1])/20
                
                ma5_trend = "向上" if ma5 > ma5_prev else "向下"
                ma20_trend = "向上" if ma20 > ma20_prev else "向下"
                rsi_14 = calc_rsi(closes)
                
                vwap = sum(c * v for c, v in zip(closes[-60:], volumes[-60:])) / sum(volumes[-60:]) if sum(volumes[-60:]) > 0 else closes[-1]
                t_data = get_quick_quote(ticker)
                turnover = t_data.get('turnover', '--')
                vol_ratio = t_data.get('vol_ratio', '--')
                
                return f"[量化技术探针] 当前换手率:{turnover}%, 量比:{vol_ratio}, RSI(14):{rsi_14:.1f}。均线系统:MA5{ma5_trend}({ma5:.2f}), MA20{ma20_trend}({ma20:.2f})。近3月核心筹码密集区(VWAP估算):{vwap:.2f}元。近20日区间:{recent_low:.2f}-{recent_high:.2f}元。"
        return "[技术面缺失]：暂无法获取均线数据。"
    except:
        return "[技术面缺失]：网络波动。"

def extract_json_from_text(text: str) -> str:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match: return match.group(0)
    return text

@app.post("/api/quant_infer")
def run_analysis_api(): 
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    settings = {}
    for row in c.execute("SELECT key, value FROM settings").fetchall(): settings[row[0]] = row[1]
        
    news_row = c.execute("SELECT content FROM news_cache ORDER BY id DESC LIMIT 1").fetchone()
    if not news_row:
        conn.close()
        return {"status": "error", "message": "没有找到新闻数据，请先执行初始化抓取操作。"}
    
    news_content = news_row[0]
    provider = settings.get("llm_provider", "deepseek")
    market = settings.get("target_market", "A股-主板(沪深)")
    
    preferred_sectors = settings.get("preferred_sectors", "").strip()
    min_price = float(settings.get("min_price", "1.0"))
    max_price = float(settings.get("max_price", "200.0"))
    
    cap_pref = settings.get("cap_preference", "全部")
    min_vol = float(settings.get("min_volume", "0"))
    trading_style = settings.get("trading_style", "中长线")
    
    cap_rule = ""
    if cap_pref == "大盘权重股": cap_rule = "【市值红线】：必须选择千亿市值以上的大盘权重股、行业绝对龙头！"
    elif cap_pref == "中小盘股": cap_rule = "【市值红线】：必须选择 100亿-500亿市值 左右的中小盘股！"
    elif cap_pref == "微盘股": cap_rule = "【市值红线】：必须选择 100亿市值以下 的微盘高弹性概念股！"
    
    vol_rule = f"【资金活跃度红线】：日均成交额需显著活跃，具备容纳 {min_vol} 亿以上资金进出的深度。" if min_vol > 0 else ""
    
    # 跨市场物理隔离防串台
    market_prompt = ""
    if market == "A股-主板(沪深)":
        market_prompt = "【跨市场红线】：用户当前选择的市场是【A股-主板(沪深)】。你推荐的股票代码必须且只能以 60 或 00 开头！绝对禁止出现 3 开头的创业板股票或 688 开头的科创板股票！"
    elif market == "A股-创业板/科创板":
        market_prompt = "【跨市场红线】：用户当前选择的市场是【A股-创业板/科创板】。你推荐的股票代码必须且只能以 30 或 688 开头！绝对禁止出现 60 或 00 开头的主板股票！"
    elif market == "港股":
        market_prompt = "【跨市场红线】：必须且只能推荐香港股市的股票（如00700）。"
    elif market == "美股全局":
        market_prompt = "【跨市场红线】：必须且只能推荐美股市场的股票（如AAPL）。"
        
    if preferred_sectors and "AI自动捕捉" in preferred_sectors:
        sector_constraint = "【核心题材指令】：不要局限于静态设定的老板块！请通过分析今天抓取到的全息情报流，自动识别出当下市场资金最集中、炒作最热的【绝对主线热门题材】，并从该热点主线中挖掘个股！"
    elif preferred_sectors:
        sector_constraint = f"优先考虑以下板块：【{preferred_sectors}】。"
    else:
        sector_constraint = "在全市场范围内寻找最受情报利好的板块。"
    
    if trading_style == "超短线":
        style_prompt = """【交易风格：超短线突击 (1-3天持仓)】
        你现在是一个专门做连板接力和情绪炒作的顶级游资大脑！
        1. 核心逻辑：极端聚焦市场情绪、昨日资金认可度、突发消息的持续性与题材的“想象空间（画大饼）”。彻底无视市盈率等长期基本面。
        2. 选股标准：寻找处于风口浪尖、连板潜力大、游资高度关注的情绪龙头或补涨龙。
        3. 盈亏比要求（激进）：追涨或极浅回踩买入（buy_discount_percent 设为 0% 到 2%），严格止损（stop_loss_percent 设为 3% 到 5%），吃完溢价即走（take_profit_percent 设为 10% 到 20%）。"""
    else:
        style_prompt = """【交易风格：中长线潜伏波段】
        你现在是一个顶级的华尔街价值投资与趋势跟踪专家！
        1. 核心逻辑：聚焦基本面与技术面共振，注重PE/PB估值修复、行业景气度拐点及真实机构研报背书。
        2. 选股标准：寻找底部扎实、业绩有支撑、机构潜伏的中大盘或高成长优质中小盘。
        3. 盈亏比要求（格局）：从容回踩买入（buy_discount_percent 设为 3% 到 8%），波段止损防守（stop_loss_percent 设为 5% 到 10%），大格局止盈（take_profit_percent 设为 15% 到 40% 以上）。"""

    system_prompt = f"""你是一个顶级的量化交易分析师。
【极其重要的警告】：绝对禁止你在输出中猜测具体的买入价格！由后台Python实时算价。

{style_prompt}

【用户的硬性风控限制】：
1. {market_prompt}
2. 目标板块：{sector_constraint}
3. 价格区间：要求真实现价严格在 {min_price} 元 至 {max_price} 元之间！
4. {cap_rule}
5. {vol_rule}
6. 【机构调研数据要求】：务必从情报中提取出真实的【研报覆盖】数据，包含真实的机构名称、评级等真实依据，绝不凭空捏造。

你【必须】挖掘 6 到 8 只符合上述所有约束条件的核心个股！

请严格按照以下JSON结构输出结果，绝无废话：
{{
  "trading_style": "{trading_style}",
  "sector": "最看好的极简板块名",
  "probability": "板块整体爆发概率，如 92%",
  "stocks": [
      {{
         "name": "符合市值红线的核心股名称", 
         "code": "股票代码(极度注意防串台)",
         "probability": "该股独立的综合上涨胜率，如 95%",
         "buy_discount_percent": 5.0,
         "stop_loss_percent": 8.0,
         "take_profit_percent": 25.0
      }}
  ],
  "reasoning": "详细推演逻辑：你是如何结合【真实研报预期】、【突发公告】和【舆情情绪】产生共振的？为何符合当前交易风格？",
  "source_news": [
      {{"title": "决定性情报标题", "url": "情报链接", "time": "情报时间"}}
  ]
}}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/8.1.0"}
        api_key = settings.get(f"{provider}_api_key", "").strip()
        if not api_key: raise Exception("您还没有配置 API Key。")
        headers = {**base_headers, "Authorization": f"Bearer {api_key}"}

        if provider in ["openai", "deepseek", "kimi", "qwen", "groq"]:
            if provider == "openai": url, model = "https://api.openai.com/v1/chat/completions", "gpt-4-turbo-preview"
            elif provider == "deepseek": url, model = "https://api.deepseek.com/chat/completions", "deepseek-chat"
            elif provider == "kimi": url, model = "https://api.moonshot.cn/v1/chat/completions", "moonshot-v1-8k"
            elif provider == "qwen": url, model = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-turbo"
            elif provider == "groq": url, model = "https://api.groq.com/openai/v1/chat/completions", "llama3-70b-8192"

            payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"最新全息情报 JSON：\n{news_content}"}]}
            response = requests.post(url, json=payload, headers=headers)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"大模型报错: {res_json}")
            llm_result_text = res_json['choices'][0]['message']['content']
            
        elif provider == "claude":
            headers = {**base_headers, "x-api-key": api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": "claude-3-opus-20240229", "max_tokens": 1500, "system": system_prompt, "messages": [{"role": "user", "content": f"最新新闻流：\n{news_content}"}]}
            response = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            res_json = response.json()
            if response.status_code != 200: raise Exception(f"Claude 报错: {res_json}")
            llm_result_text = res_json['content'][0]['text']

        elif provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n最新新闻流：\n{news_content}"}]}]}
            response = requests.post(url, json=payload, headers=base_headers)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"Gemini 报错: {res_json}")
            llm_result_text = res_json['candidates'][0]['content']['parts'][0]['text']
            
        else: raise Exception(f"未知的提供商: {provider}")

        clean_json_str = extract_json_from_text(llm_result_text)
        
        try:
            parsed_res = json.loads(clean_json_str)
            valid_stocks = []
            global_prob = parsed_res.get('probability', 'N/A')
            if 'trading_style' not in parsed_res: parsed_res['trading_style'] = trading_style
            
            for stock in parsed_res.get('stocks', []):
                code = str(stock.get('code', '')).strip()
                buy_discount = float(stock.get('buy_discount_percent', 4.0))
                stop_loss = float(stock.get('stop_loss_percent', 8.0))
                take_profit_pct = float(stock.get('take_profit_percent', 20.0))
                
                # Python 物理级防串台拦截逻辑
                is_valid_market = True
                num_match = re.search(r'\d+', code)
                eng_match = re.search(r'[A-Za-z]+', code)
                
                if market == "A股-主板(沪深)":
                    if not num_match or len(num_match.group()) != 6 or not (num_match.group().startswith('60') or num_match.group().startswith('00')):
                        is_valid_market = False
                elif market == "A股-创业板/科创板":
                    if not num_match or len(num_match.group()) != 6 or not (num_match.group().startswith('30') or num_match.group().startswith('688')):
                        is_valid_market = False
                elif market == "港股":
                    if not num_match or len(num_match.group()) > 5: is_valid_market = False
                elif market == "美股全局":
                    if not eng_match or num_match: is_valid_market = False
                        
                if not is_valid_market:
                    print(f"[MARKET FILTER] 剔除串台股票: {code} 不属于 {market}")
                    continue
                
                stock['probability'] = stock.get('probability', global_prob)
                current_price = internal_get_quick_quote(code)
                
                if current_price == -1:
                    stock['current_price'] = "获取失败"
                    stock['buy_range'] = f"预估下探 {buy_discount}%"
                    stock['sell_target'] = f"破位 {stop_loss}% 止损"
                    stock['take_profit_target'] = f"上攻 {take_profit_pct}% 止盈"
                    valid_stocks.append(stock)
                elif current_price > 0 and (min_price <= current_price <= max_price):
                    buy_price = round(current_price * (1 - buy_discount / 100), 2)
                    sell_price = round(current_price * (1 - stop_loss / 100), 2)
                    target_price = round(current_price * (1 + take_profit_pct / 100), 2)
                    
                    stock['current_price'] = f"{current_price} 元"
                    stock['buy_range'] = f"{buy_price} - {current_price} 元"
                    stock['sell_target'] = f"{sell_price} 元"
                    stock['take_profit_target'] = f"{target_price} 元"
                    valid_stocks.append(stock)
                
            if not valid_stocks:
                conn.close()
                return {"status": "error", "message": f"大模型推演的标的不符合价格/市场红线，已全部废弃过滤。"}
                
            parsed_res['stocks'] = valid_stocks
            final_json_str = json.dumps(parsed_res, ensure_ascii=False)
            
            c.execute("DELETE FROM analysis_results WHERE id NOT IN (SELECT id FROM analysis_results ORDER BY id DESC LIMIT 20)")
            conn.commit()
            
        except Exception as filter_e:
            print(f"[PRICE CALCULUS ERROR]: {filter_e}")
            final_json_str = clean_json_str
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO analysis_results (timestamp, content) VALUES (?, ?)", (timestamp, final_json_str))
        conn.commit()
        conn.close()

        send_push(final_json_str)
        return {"status": "success", "message": f"推演完成！策略池已无缝刷新。"}
        
    except Exception as e:
        conn.close()
        return {"status": "error", "message": f"{str(e)}"}

class DeepDiveReq(BaseModel):
    code: str
    name: str

@app.post("/api/quant_deep_dive")
def run_deep_dive_api(req: DeepDiveReq):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    settings = {row[0]: row[1] for row in c.execute("SELECT key, value FROM settings").fetchall()}
    
    provider = settings.get("llm_provider", "deepseek")
    trading_style = settings.get("trading_style", "中长线")
    api_key = settings.get(f"{provider}_api_key", "").strip()
    if not api_key:
        conn.close()
        return {"status": "error", "message": "大模型 API Key 未配置，无法执行 12D 透视。"}
        
    quote_res = get_quick_quote(req.code)
    if quote_res.get('status') == 'error':
        conn.close()
        return {"status": "error", "message": f"无法获取股票 {req.code} 的实时盘面价格，透视引擎拒绝启动。"}
    
    current_price = quote_res.get('price', 0)
    market_cap = quote_res.get('market_cap', '--')
    pe = quote_res.get('pe', '--')
    pb = quote_res.get('pb', '--')

    tech_basis = internal_get_stock_tech_basis(req.code)

    ticker_news_str = ""
    try:
        clean_ticker = format_ticker(req.code)
        res_news = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={clean_ticker}&newsCount=10", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if res_news.status_code == 200:
            news_items = res_news.json().get('news', [])
            extracted = [f"标题:{n.get('title', '')} 出处:{n.get('publisher', '')}" for n in news_items]
            ticker_news_str = " | ".join(extracted)
    except: pass
    
    if not ticker_news_str:
        ticker_news_str = "近期无该股专属舆情新闻。"

    system_prompt = f"""你现在是一位顶级的华尔街量化策略师与风控专家。当前系统设定的【全局交易风格】为：{trading_style}。对【{req.name}({req.code})】进行【12维全息透视】。
    【实时量化基本面特征】：现价 {current_price}元, 总市值 {market_cap}, 动态市盈率(PE) {pe}, 市净率(PB) {pb}。
    【实时量价技术面探针】：{tech_basis}
    【该股近期专属舆情】：{ticker_news_str}

    【多维立体定价与风控指令 (Multi-Factor Pricing Matrix)】：
    你必须彻底摒弃空洞的套话和单一的均线分析！你必须像通达信、同花顺的高级 F10 研报一样，直接引用我提供的【换手率】、【量比】、【筹码密集区VWAP】、【RSI指标】等真实数据作为你的论据支持。
    如果你在进行中长线透视，请侧重于估值修复(PE/PB)、筹码分布和行业宏观环境。如果你在进行超短线透视，请极端偏向资金面（换手/量比）、题材爆发力与游资情绪！

    【输出定价约束】：
    - entry_strategy.basis：必须引用上述真实数据中的至少2个维度写出建仓逻辑（如：今日量比放大配合高换手率，股价成功站稳 VWAP 筹码密集区，RSI脱离超卖区，可依托MA5向上发散建仓）。
    - take_profit.basis：展现出基于 {trading_style} 的专属止盈格局依据（超短线看前高阻力，中长线看估值修复空间）。
    - stop_loss.basis：必须结合筹码 VWAP 破位或换手率情绪退潮来定制定量止损线。

    严格输出JSON：
    {{
      "probability": "综合胜率如 88%",
      "entry_strategy": {{
          "price": "建议买入价，如 {current_price}",
          "basis": "引用真实量价数据的多维共振建仓推演依据(不少于30字)"
      }},
      "stop_loss": {{
          "price": "具体止损价",
          "basis": "引用真实量价数据的破位止损推演依据"
      }},
      "take_profit": {{
          "price": "具体强势止盈价",
          "basis": "基于估值修复或波段阻力的推演依据"
      }},
      "analysis_12d": {{
         "1_宏观经济": "一句话专业推演(限50字)",
         "2_行业环境": "一句话专业推演(限50字)",
         "3_基本面价值": "一句话专业推演(结合PE/PB, 限50字)",
         "4_财务与营收": "一句话专业推演(限50字)",
         "5_真实机构动向": "一句话专业推演(提取真实评级, 限50字)",
         "6_资金与筹码": "一句话专业推演(引用换手率/量比/VWAP, 限50字)",
         "7_高阶技术面": "一句话专业推演(引用RSI与均线斜率, 限50字)",
         "8_市场情绪面": "一句话专业推演(限50字)",
         "9_政策红利": "一句话专业推演(限50字)",
         "10_题材催化": "一句话专业推演(限50字)",
         "11_风险与黑天鹅": "一句话专业推演(限50字)",
         "12_交易风格契合度": "一句话说明是否符合[{trading_style}]要求(限50字)"
      }},
      "summary": "最终一句话量化决策与仓位建议总结"
    }}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/8.1.0", "Authorization": f"Bearer {api_key}"}

        if provider in ["openai", "deepseek", "kimi", "qwen", "groq"]:
            if provider == "openai": url, model = "https://api.openai.com/v1/chat/completions", "gpt-4-turbo-preview"
            elif provider == "deepseek": url, model = "https://api.deepseek.com/chat/completions", "deepseek-chat"
            elif provider == "kimi": url, model = "https://api.moonshot.cn/v1/chat/completions", "moonshot-v1-8k"
            elif provider == "qwen": url, model = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-turbo"
            elif provider == "groq": url, model = "https://api.groq.com/openai/v1/chat/completions", "llama3-70b-8192"

            payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": "请基于上述硬核量价指标与全息基本面数据，立即执行 12D 机构级多维发散透视分析。"}]}
            response = requests.post(url, json=payload, headers=base_headers)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"大模型报错: {res_json}")
            llm_result_text = res_json['choices'][0]['message']['content']
            
        elif provider == "claude":
            headers_claude = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": "claude-3-opus-20240229", "max_tokens": 1500, "system": system_prompt, "messages": [{"role": "user", "content": "请立即执行深度透视。"}]}
            response = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers_claude)
            res_json = response.json()
            if response.status_code != 200: raise Exception(f"Claude 报错: {res_json}")
            llm_result_text = res_json['content'][0]['text']

        elif provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n请立即执行深度透视。"}]}]}
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"Gemini 报错: {res_json}")
            llm_result_text = res_json['candidates'][0]['content']['parts'][0]['text']

        clean_json_str = extract_json_from_text(llm_result_text)
        json.loads(clean_json_str)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO deep_analysis_history (timestamp, code, name, content) VALUES (?, ?, ?, ?)", (timestamp, req.code, req.name, clean_json_str))
        conn.commit()
        conn.close()

        return {"status": "success", "data": json.loads(clean_json_str), "current_price": current_price}
        
    except Exception as e:
        conn.close()
        return {"status": "error", "message": f"{str(e)}"}

def scheduled_auto_quant():
    res_fetch = internal_fetch_news()
    if res_fetch.get("status") == "success": internal_run_analysis()

def reload_scheduler():
    scheduler.remove_all_jobs()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    enabled_row = c.execute("SELECT value FROM settings WHERE key = 'cron_enabled'").fetchone()
    time_row = c.execute("SELECT value FROM settings WHERE key = 'cron_time'").fetchone()
    conn.close()

    if enabled_row and enabled_row[0] == 'true' and time_row and time_row[0]:
        try:
            hour, minute = time_row[0].split(':')
            scheduler.add_job(scheduled_auto_quant, 'cron', hour=int(hour), minute=int(minute), id='auto_quant_job')
        except: pass

@app.on_event("startup")
def startup_event():
    init_db()
    scheduler.start()
    reload_scheduler()

class SettingItem(BaseModel):
    key: str
    value: str

@app.post("/api/settings")
def save_setting(setting: SettingItem):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (setting.key, setting.value))
    conn.commit()
    conn.close()
    if setting.key in ["cron_enabled", "cron_time"]: reload_scheduler()
    return {"status": "success"}

@app.get("/api/settings/{key}")
def get_setting(key: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row: return {"value": row[0]}
    return {"value": ""}

@app.get("/api/news/fetch")
def fetch_news_api(): return internal_fetch_news()

@app.get("/api/news/list")
def get_news_list():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT content FROM news_cache ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        try: return json.loads(row[0])
        except: return []
    return []

@app.get("/api/results")
def get_results():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT timestamp, content FROM analysis_results ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    parsed_results = []
    for r in rows:
        try: parsed_results.append({"timestamp": r[0], "content": json.loads(r[1])})
        except: pass
    return parsed_results

class WatchlistItem(BaseModel):
    code: str
    name: str

@app.get("/api/watchlist")
def get_watchlist():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()
    conn.close()
    if row:
        try: return json.loads(row[0])
        except: return []
    return []

@app.post("/api/watchlist/add")
def add_to_watchlist(item: WatchlistItem):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()
    wl = json.loads(row[0]) if row else []
    if not any(x.get('code') == item.code for x in wl):
        wl.append({"code": item.code, "name": item.name})
        c.execute("REPLACE INTO settings (key, value) VALUES ('watchlist', ?)", (json.dumps(wl),))
        conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/watchlist/remove")
def remove_from_watchlist(item: WatchlistItem):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT value FROM settings WHERE key='watchlist'").fetchone()
    if row:
        wl = json.loads(row[0])
        wl = [x for x in wl if x.get('code') != item.code]
        c.execute("REPLACE INTO settings (key, value) VALUES ('watchlist', ?)", (json.dumps(wl),))
        conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/stock/{ticker}")
def get_stock_data(ticker: str, chart_type: str = 'daily'):
    y_code = ticker
    t_code = format_ticker(ticker)
    if t_code.startswith("sh"): y_code = t_code[2:] + ".SS"
    elif t_code.startswith("sz"): y_code = t_code[2:] + ".SZ"
    elif t_code.startswith("hk"): y_code = t_code[2:] + ".HK"

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36', 'Accept': '*/*'}
        if chart_type == 'intraday': interval, range_val = '1m', '1d'
        elif chart_type == '5day': interval, range_val = '15m', '5d'
        else: interval, range_val = '1d', '10y'

        chart_res = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{y_code}?interval={interval}&range={range_val}", headers=headers, timeout=10)
        if chart_res.status_code == 404: raise Exception(f"未找到代码 ({y_code})。")
        elif chart_res.status_code != 200: raise Exception(f"节点拒绝 (HTTP {chart_res.status_code})。")
            
        result = chart_res.json()['chart']['result'][0]
        meta, timestamps, indicators = result['meta'], result.get('timestamp', []), result.get('indicators', {}).get('quote', [{}])[0]
        volumes = indicators.get('volume', [])
        
        klines_dict = {}
        for i in range(len(timestamps)):
            if i < len(indicators.get('open', [])) and indicators['open'][i] is not None:
                time_key = int(timestamps[i]) if chart_type in ['intraday', '5day'] else datetime.fromtimestamp(timestamps[i]).strftime('%Y-%m-%d')
                klines_dict[time_key] = {
                    'time': time_key, 'open': round(indicators['open'][i], 2), 'high': round(indicators['high'][i], 2), 
                    'low': round(indicators['low'][i], 2), 'close': round(indicators['close'][i], 2),
                    'volume': volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                }
        klines = list(klines_dict.values())
        klines.sort(key=lambda x: x['time'])
        if not klines: raise Exception("数据为空。")

        return {
            "status": "success", "symbol": y_code, "price": round(meta.get('regularMarketPrice', 0), 2),
            "change": round(meta.get('regularMarketPrice', 0) - meta.get('chartPreviousClose', 0), 2), 
            "change_percent": round(((meta.get('regularMarketPrice', 0) - meta.get('chartPreviousClose', 0)) / meta.get('chartPreviousClose', 1)) * 100, 2) if meta.get('chartPreviousClose') else 0, 
            "klines": klines, "chart_type": chart_type
        }
    except Exception as e: return {"status": "error", "message": str(e)}

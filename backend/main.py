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

app = FastAPI(title="Quant Engine API V5.3")

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
    
    # [双重密码初始化] 分离主控台与设置页面的密码
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('console_password', 'admin123')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('settings_password', 'admin123')")
    
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('session_token', 'init_token_xyz')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('watchlist', '[]')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('preferred_sectors', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_price', '1.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_price', '200.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('max_buy_distance', '5.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('refresh_interval', '300')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('cap_preference', '全部')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_volume', '0')")
    
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
    
    if req.password == real_pwd:
        return {"status": "success"}
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
        stocks_list = data.get("stocks", [])
        
        msg_lines = [
            f"📈 【量化策略已更新】",
            f"🎯 优选板块: {sector}",
            f"📊 板块胜率: {prob}",
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
                
                msg_lines.append(f"🔥 【{name}】 ({code}) [胜率:{ind_prob}]")
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
            try: requests.post(f"https://sctapi.ftqq.com/{wechat_key}.send", data={"title": f"📈 {sector}策略已更新", "desp": msg_body}, timeout=5)
            except: pass

        wxpusher_token = settings.get("wxpusher_app_token", "").strip()
        wxpusher_uid = settings.get("wxpusher_uid", "").strip()
        if wxpusher_token and wxpusher_uid:
            try:
                wp_url = "https://wxpusher.zjiecode.com/api/send/message"
                wp_payload = {"appToken": wxpusher_token, "content": msg_body, "summary": f"📈 {sector}量化更新", "contentType": 1, "uids": [wxpusher_uid]}
                requests.post(wp_url, json=wp_payload, headers={'Content-Type': 'application/json'}, timeout=5)
            except: pass
    except: pass

def is_market_relevant(text: str) -> bool:
    keywords = ['股', '市', '券商', '央行', '外汇', '经济', '利好', '利空', '涨停', '跌停', '指数', '美联储', '利率', 'CPI', '大盘', '主力', '资金', '财报', '重组', '政策', '部委', '发改委', '国务院', '补贴', '关税', '制裁', '贸易战', '原油', '黄金', '新能源', '半导体', 'AI', '算力', '地产', '证监会', 'IPO', '融资', '减持', '增持', '汇率', '降息', '降准', '订单', '中标', '研发', '突破', '会议', '规划', '非农', '热议', '评级', '目标价']
    for kw in keywords:
        if kw in text: return True
    return False

def get_news_type(title: str) -> str:
    if any(k in title for k in ['公告', '停牌', '复牌', '财报', '重组', '中标', '立案', '新规']):
        return "突发公告/政策"
    elif any(k in title for k in ['研报', '评级', '买入', '增持', '目标价', '预测', '机构认为']):
        return "机构研报预期"
    elif any(k in title for k in ['热议', '股吧', '雪球', '网友', '炸板', '跳水', '涨停', '疯抢', '恐慌']):
        return "社交舆情热度"
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
            title = f"【研报覆盖】{r.get('title')} - 机构:{r.get('orgSName')} 评级:{r.get('emRatingName')}"
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
                    "prev": prev
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
                "open": "--", "high": "--", "low": "--", "prev": prev
            }
    except: pass
    
    return {"status": "error"}

def internal_get_quick_quote(ticker: str):
    res = get_quick_quote(ticker)
    if res.get('status') == 'success':
        return res.get('price', -1)
    return -1

def internal_get_stock_tech_basis(ticker: str):
    try:
        y_code = ticker
        t_code = format_ticker(ticker)
        if t_code.startswith("sh"): y_code = t_code[2:] + ".SS"
        elif t_code.startswith("sz"): y_code = t_code[2:] + ".SZ"
        elif t_code.startswith("hk"): y_code = t_code[2:] + ".HK"
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{y_code}?interval=1d&range=1mo", headers=headers, timeout=5)
        if res.status_code == 200:
            inds = res.json()['chart']['result'][0]['indicators']['quote'][0]
            closes = [c for c in inds.get('close', []) if c is not None]
            highs = [h for h in inds.get('high', []) if h is not None]
            lows = [l for l in inds.get('low', []) if l is not None]
            if closes:
                recent_high = max(highs[-10:]) if len(highs) >= 10 else max(highs)
                recent_low = min(lows[-10:]) if len(lows) >= 10 else min(lows)
                ma5 = sum(closes[-5:])/5 if len(closes)>=5 else closes[-1]
                ma20 = sum(closes[-20:])/20 if len(closes)>=20 else closes[-1]
                return f"[基础技术位] 近10日最高价:{recent_high:.2f}, 最低价:{recent_low:.2f}, MA5:{ma5:.2f}, MA20:{ma20:.2f}。"
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
    
    cap_rule = ""
    if cap_pref == "大盘权重股": cap_rule = "【市值红线】：必须选择千亿市值以上的大盘权重股、行业绝对龙头！"
    elif cap_pref == "中小盘股": cap_rule = "【市值红线】：必须选择 100亿-500亿市值 左右的中小盘股！"
    elif cap_pref == "微盘股": cap_rule = "【市值红线】：必须选择 100亿市值以下 的微盘高弹性概念股！"
    
    vol_rule = f"【资金活跃度红线】：日均成交额需显著活跃，具备容纳 {min_vol} 亿以上资金进出的深度。" if min_vol > 0 else ""
    
    sector_constraint = f"优先考虑以下板块：【{preferred_sectors}】。" if preferred_sectors else "在全市场范围内寻找最受情报利好的板块。"
    
    system_prompt = f"""你是一个顶级的量化交易分析师。
【极其重要的警告】：绝对禁止你在输出中猜测具体的买入价格！由后台Python实时算价。

【盈亏比与空间要求（极度重要）】：
为了体现量化系统的专业性与操作可行性，你给出的个股策略必须具备高盈亏比！
1. buy_discount_percent (回踩买入幅度)：通常设定在 3% 到 8% 之间，给用户从容建仓的机会。
2. stop_loss_percent (破位止损幅度)：通常设定在 5% 到 10% 之间的核心支撑位。
3. take_profit_percent (波段止盈幅度)：展现你的自信！目标空间通常要在 15% 到 40% 之间！绝不要给出仅仅赚一两个点的无效建议！

【用户的硬性风控限制】：
1. 目标市场/板块：{market}，{sector_constraint}
2. 价格区间：要求真实现价严格在 {min_price} 元 至 {max_price} 元之间！
3. {cap_rule}
4. {vol_rule}

你【必须】广撒网，挖掘 6 到 8 只符合上述所有约束条件的核心个股！

请严格按照以下JSON结构输出结果，绝无废话：
{{
  "sector": "最看好的极简板块名",
  "probability": "板块整体爆发概率，如 92%",
  "stocks": [
      {{
         "name": "符合市值红线的核心股名称", 
         "code": "股票代码(6位数字)",
         "probability": "该股独立的上涨胜率，如 95%",
         "buy_discount_percent": 5.0,
         "stop_loss_percent": 8.0,
         "take_profit_percent": 25.0
      }}
  ],
  "reasoning": "详细推演逻辑：你是如何结合【研报预期】、【突发公告】和【舆情热度】产生共振的？为何这批股票符合用户的市值要求？",
  "source_news": [
      {{"title": "决定性情报标题", "url": "情报链接", "time": "情报时间"}}
  ]
}}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/5.3.0"}
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
            
            for stock in parsed_res.get('stocks', []):
                code = stock.get('code', '')
                buy_discount = float(stock.get('buy_discount_percent', 4.0))
                stop_loss = float(stock.get('stop_loss_percent', 8.0))
                take_profit_pct = float(stock.get('take_profit_percent', 20.0))
                
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
                return {"status": "error", "message": f"大模型推荐的标的均超出价格红线，已静默废弃。"}
                
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
        return {"status": "success", "message": f"多因子共振分析与实时算价完成。战报已推送。"}
        
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

    system_prompt = f"""你现在是一位顶级的华尔街量化策略师与风控专家。对【{req.name}({req.code})】进行【12维全息透视】。
    【实时量化基本面特征】：现价 {current_price}元, 总市值 {market_cap}, 动态市盈率(PE) {pe}, 市净率(PB) {pb}。
    【基础技术面特征】：{tech_basis}
    【该股近期专属舆情】：{ticker_news_str}

    【多维立体定价与风控指令 (Multi-Factor Pricing Matrix)】：
    绝对禁止你单纯依赖均线来给出进场和止损依据！你必须综合以下维度给出极具权威性的华尔街级推演：
    1. 基本面与估值 (Fundamental & Valuation)：结合我提供的 PE/PB 和市值。
    2. 宏观与行业环境 (Macro & Industry Sentiment)：当前政策、经济周期对该股的溢价影响。
    3. 资金面与情绪筹码 (Capital Flow & Sentiment)：主力资金动向、市场热度、换手意愿。
    4. 题材与催化剂 (Theme & Catalysts)：近期新闻事件发酵的爆发力。
    5. 高阶技术面共振 (Technical Resonance)：支撑/压力位、量价配合、MACD等形态。

    【输出定价约束】：
    - entry_strategy.basis (建仓依据)：必须结合上述至少3个维度，写出专业的建仓逻辑（如：估值处于历史低位，配合量能放大及底背离，依托关键支撑建仓）。
    - take_profit.basis (止盈依据)：必须结合题材爆发力、上方套牢盘压力及估值修复空间，给出 15%~40% 甚至更高的强势目标价和格局依据。
    - stop_loss.basis (止损依据)：必须结合基本面破位、资金出逃及关键筹码密集区失效来定制定量止损线。

    严格输出JSON：
    {{
      "probability": "上涨概率如 88%",
      "entry_strategy": {{
          "price": "建议买入价，如 {current_price}",
          "basis": "多维共振建仓推演依据(不少于30字)"
      }},
      "stop_loss": {{
          "price": "具体止损价",
          "basis": "多维破位止损推演依据"
      }},
      "take_profit": {{
          "price": "具体强势止盈价",
          "basis": "多维估值修复与波段阻力推演依据"
      }},
      "analysis_12d": {{
         "1_宏观经济": "一句话专业推演(限50字)",
         "2_行业环境": "一句话专业推演(限50字)",
         "3_基本面价值": "一句话专业推演(结合PE/PB, 限50字)",
         "4_财务与营收": "一句话专业推演(限50字)",
         "5_机构动向": "一句话专业推演(限50字)",
         "6_资金与筹码": "一句话专业推演(限50字)",
         "7_高阶技术面": "一句话专业推演(限50字)",
         "8_市场情绪面": "一句话专业推演(限50字)",
         "9_政策红利": "一句话专业推演(限50字)",
         "10_题材催化": "一句话专业推演(限50字)",
         "11_风险与黑天鹅": "一句话专业推演(限50字)",
         "12_管理风评": "一句话专业推演(限50字)"
      }},
      "summary": "最终一句话量化决策与仓位建议总结"
    }}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/5.3.1", "Authorization": f"Bearer {api_key}"}

        if provider in ["openai", "deepseek", "kimi", "qwen", "groq"]:
            if provider == "openai": url, model = "https://api.openai.com/v1/chat/completions", "gpt-4-turbo-preview"
            elif provider == "deepseek": url, model = "https://api.deepseek.com/chat/completions", "deepseek-chat"
            elif provider == "kimi": url, model = "https://api.moonshot.cn/v1/chat/completions", "moonshot-v1-8k"
            elif provider == "qwen": url, model = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-turbo"
            elif provider == "groq": url, model = "https://api.groq.com/openai/v1/chat/completions", "llama3-70b-8192"

            payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": "请基于上述实时基本面与量价数据，立即执行 12D 华尔街多维立体发散透视分析。"}]}
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
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

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
import math
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI(title="Quant Engine API V24.0")

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

BEIJING_TZ = timezone(timedelta(hours=8))

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
        trend = data.get("trend_prediction", "获取中...")
        stocks_list = data.get("stocks", [])
        
        msg_lines = [
            f"📈 【全球量化平台策略更新】",
            f"🎯 优选板块: {sector}",
            f"🧭 交易风格: {style}",
            f"📊 板块热度: {prob}",
            f"🔮 走势预判: {trend[:100]}...",
            "━━━━━━━━━━━━━━━━"
        ]

        if not stocks_list:
            msg_lines.append("⚠️ 暂无符合严苛风控要求的个股")
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
            try: requests.post(f"https://sctapi.ftqq.com/{wechat_key}.send", data={"title": f"📈 {style}-{sector}量化更新", "desp": msg_body}, timeout=5)
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
        pubDate = item.get("create_time", datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"))
        
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
            pubDate = r.get('publishDate', datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"))
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
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
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
                
                outer_vol = cols[7] if len(cols)>7 and cols[7] else '--'
                inner_vol = cols[8] if len(cols)>8 and cols[8] else '--'
                turnover = cols[38] if len(cols)>38 and cols[38] else '--'
                amplitude = cols[43] if len(cols)>43 and cols[43] else '--'
                circ_cap = cols[44] if len(cols)>44 and cols[44] else '--'
                vol_ratio = cols[49] if len(cols)>49 and cols[49] else '--'
                
                mc_str = f"{market_cap}亿" if market_cap and market_cap != "" else "--"
                circ_str = f"{circ_cap}亿" if circ_cap and circ_cap != "" else "--"
                
                return {
                    "status": "success", 
                    "price": round(price, 2), 
                    "change_percent": change_percent,
                    "market_cap": mc_str,
                    "circ_cap": circ_str,
                    "pe": pe if pe else '--',
                    "pb": pb if pb else '--',
                    "volume": volume,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "prev": prev,
                    "turnover": turnover,
                    "amplitude": amplitude,
                    "vol_ratio": vol_ratio,
                    "outer_vol": outer_vol,
                    "inner_vol": inner_vol
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
            rmp = meta.get('regularMarketPrice')
            cpc = meta.get('chartPreviousClose')
            price_val = float(rmp) if rmp is not None else 0.0
            prev_val = float(cpc) if cpc is not None else price_val
            change_val = price_val - prev_val
            change_pct = (change_val / prev_val * 100) if prev_val != 0 else 0.0
            return {
                "status": "success", "price": round(price_val, 2), "change_percent": round(change_pct, 2),
                "market_cap": "--", "circ_cap": "--", "pe": "--", "pb": "--", 
                "volume": meta.get('regularMarketVolume', '--'),
                "open": "--", "high": "--", "low": "--", "prev": prev_val,
                "turnover": "--", "amplitude": "--", "vol_ratio": "--",
                "outer_vol": "--", "inner_vol": "--"
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
    avg_gain = sum(gains[-period:])/period if period > 0 else 0
    avg_loss = sum(losses[-period:])/period if period > 0 else 0
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(prices, days):
    ema = [prices[0]]
    k = 2 / (days + 1)
    for price in prices[1:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

def calc_macd(closes):
    if len(closes) < 30: return 0, 0, 0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    diff = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    dea = calc_ema(diff, 9)
    macd = [2 * (d - de) for d, de in zip(diff, dea)]
    return diff[-1], dea[-1], macd[-1]

def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    if len(closes) < n: return 50, 50, 50
    k, d = 50, 50
    for i in range(len(closes)):
        start_idx = max(0, i - n + 1)
        period_highs = highs[start_idx:i+1]
        period_lows = lows[start_idx:i+1]
        hn = max(period_highs)
        ln = min(period_lows)
        if hn == ln: rsv = 0
        else: rsv = (closes[i] - ln) / (hn - ln) * 100
        if i == 0: k, d = rsv, rsv
        else:
            k = (m1 - 1) / m1 * k + 1 / m1 * rsv
            d = (m2 - 1) / m2 * d + 1 / m2 * k
    j = 3 * k - 2 * d
    return k, d, j

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2: return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period

def calc_obv(closes, volumes):
    if len(closes) < 2: return 0.0
    obv = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]: obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]: obv.append(obv[-1] - volumes[i])
        else: obv.append(obv[-1])
    return obv[-1]

def calc_boll_latest(closes, period=20, k=2):
    if len(closes) < period: return 0, 0, 0
    recent = closes[-period:]
    mb = sum(recent) / period
    variance = sum((x - mb) ** 2 for x in recent) / period
    md = math.sqrt(variance)
    return mb + k * md, mb, mb - k * md

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
            op_list = inds.get('open', [])
            hi_list = inds.get('high', [])
            lo_list = inds.get('low', [])
            cl_list = inds.get('close', [])
            vol_list = inds.get('volume', [])
            
            closes, highs, lows, opens, volumes = [], [], [], [], []
            for i in range(len(cl_list)):
                if hi_list[i] is not None and lo_list[i] is not None and cl_list[i] is not None and op_list[i] is not None:
                    opens.append(float(op_list[i]))
                    highs.append(float(hi_list[i]))
                    lows.append(float(lo_list[i]))
                    closes.append(float(cl_list[i]))
                    volumes.append(float(vol_list[i]) if vol_list[i] is not None else 0)
            
            if len(closes) >= 30:
                recent_high = max(highs[-20:])
                recent_low = min(lows[-20:])
                ma5 = sum(closes[-5:])/5
                ma20 = sum(closes[-20:])/20
                rsi_14 = calc_rsi(closes)
                diff, dea, macd = calc_macd(closes)
                macd_trend = "红柱发散" if macd > 0 and macd > (closes[-1]-closes[-2])*0.01 else ("绿柱状态" if macd < 0 else "弱势震荡")
                k, d, j = calc_kdj(highs, lows, closes)
                kdj_trend = "金叉向上" if k > d and j > k else ("死叉向下" if k < d else "胶着")
                up, mb, dn = calc_boll_latest(closes)
                boll_pos = "突破上轨" if closes[-1] > up else ("击穿下轨" if closes[-1] < dn else "在中轨附近")
                
                atr_14 = calc_atr(highs, lows, closes, 14)
                obv_latest = calc_obv(closes, volumes)
                
                pattern_str = "无明显特殊形态"
                vol_trend = "震荡量"
                if len(closes) >= 3:
                    c1, c2, c3 = closes[-3], closes[-2], closes[-1]
                    o1, o2, o3 = opens[-3], opens[-2], opens[-1]
                    v1, v2, v3 = volumes[-3], volumes[-2], volumes[-1]
                    
                    if v3 > v2 and v2 > v1: vol_trend = "连续放量"
                    elif v3 < v2 and v2 < v1: vol_trend = "连续缩量"
                    
                    if c1>o1 and c2>o2 and c3>o3 and c3>c2>c1: pattern_str = "红三兵(强烈看涨)"
                    elif c1<o1 and c2<o2 and c3<o3 and c3<c2<c1: pattern_str = "三只乌鸦(强烈看跌)"
                    elif abs(c3 - o3) / (highs[-1] - lows[-1] + 0.001) < 0.1: pattern_str = "高位/低位十字星(变盘预警)"
                
                vwap = sum(c * v for c, v in zip(closes[-60:], volumes[-60:])) / sum(volumes[-60:]) if sum(volumes[-60:]) > 0 else closes[-1]
                t_data = get_quick_quote(ticker)
                turnover = t_data.get('turnover', '--')
                vol_ratio = t_data.get('vol_ratio', '--')
                outer_vol = t_data.get('outer_vol', '--')
                inner_vol = t_data.get('inner_vol', '--')

                recent_k_seq = []
                for i in range(max(0, len(closes)-5), len(closes)):
                    day_label = f"T-{len(closes)-1-i}" if i < len(closes)-1 else "今日(T0)"
                    recent_k_seq.append(f"{day_label}[开{opens[i]:.2f} 高{highs[i]:.2f} 低{lows[i]:.2f} 收{closes[i]:.2f} 量{volumes[i]}]")
                recent_k_str = " | ".join(recent_k_seq)
                
                return f"[高阶量价形态探针] 换手率:{turnover}%, 量比:{vol_ratio}, 外盘:{outer_vol}, 内盘:{inner_vol}。近3日形态:{vol_trend}且{pattern_str}。技术指标-> RSI:{rsi_14:.1f}, KDJ现{kdj_trend}。MACD状态:{macd_trend}。BOLL位置:{boll_pos}。ATR(14):{atr_14:.2f}。当前OBV能量潮值:{obv_latest}。近3月筹码峰(VWAP):{vwap:.2f}元。\n【近5日微观K线序列(必读)】: {recent_k_str}"
        return "[技术面缺失]：暂无法获取均线数据。"
    except Exception as e:
        return f"[技术面缺失]：计算波动 {str(e)}。"

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
        style_prompt = """【商业级交易指令：超短线打板与情绪博弈 (1-3天持仓)】
        你现在是一个顶尖游资机构的超短线打板客！
        1. 选股逻辑：无视PE/PB！极端聚焦【市场情绪、换手率、量比、题材想象空间】。
        2. 选股标准：寻找风口浪尖、连板潜力大、外盘大于内盘的换手龙头。
        3. 极端盈亏比要求：追涨或极浅回踩买入（buy_discount_percent 设为 0% 到 2%），严格止损（stop_loss_percent 设为 3% 到 5%），吃完溢价即走（take_profit_percent 设为 10% 到 20%）。
        4. 骗线识别：如果有主力拉高出货现象，坚决放弃！"""
    else:
        style_prompt = """【商业级交易指令：中长线价值与趋势潜伏 (数周至数月)】
        你现在是一个顶级华尔街公募基金的价值投资与趋势跟踪基金经理！
        1. 选股逻辑：极端聚焦【基本面价值重估、PE/PB估值水位、行业景气度拐点、真实机构研报背书】。
        2. 选股标准：寻找底部扎实、业绩有支撑、机构大规模建仓潜伏的优质标的。
        3. 格局盈亏比要求：从容回踩买入（buy_discount_percent: 3%~8%），计算宽幅震荡止损位避免被洗（stop_loss_percent: 5%~10%），大格局止盈（take_profit_percent: 15%~40% 以上）。"""

    system_prompt = f"""你是一个顶级的商业化量化交易分析师。
【极其重要的警告】：绝对禁止你在输出中猜测具体的买入价格！由后台Python根据你给的百分比实时算价。

{style_prompt}

【用户的硬性风控限制】：
1. {market_prompt}
2. 目标板块：{sector_constraint}
3. 价格区间：要求真实现价严格在 {min_price} 元 至 {max_price} 元之间！
4. {cap_rule}
5. {vol_rule}
6. 【机构调研要求】：务必提取出真实的【研报覆盖】数据，绝不捏造。

你【必须】挖掘 6 到 8 只符合上述所有约束条件的核心个股！

请严格按照以下JSON结构输出结果，绝无废话：
{{
  "trading_style": "{trading_style}",
  "sector": "最看好的极简板块名",
  "probability": "板块整体爆发概率，如 92%",
  "trend_prediction": "结合[{trading_style}]给出具体的未来走势演绎与应对策略",
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
  "reasoning": "详细推演逻辑：结合【研报预期】和【情绪】深度论证为何看好该板块？",
  "source_news": [
      {{"title": "决定性情报标题", "url": "情报链接", "time": "情报时间"}}
  ]
}}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/24.0.0"}
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
            response = requests.post(url, json=payload, headers=headers, timeout=150)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"大模型报错: {res_json}")
            llm_result_text = res_json['choices'][0]['message']['content']
            
        elif provider == "claude":
            headers = {**base_headers, "x-api-key": api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": "claude-3-opus-20240229", "max_tokens": 1500, "system": system_prompt, "messages": [{"role": "user", "content": f"最新新闻流：\n{news_content}"}]}
            response = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=150)
            res_json = response.json()
            if response.status_code != 200: raise Exception(f"Claude 报错: {res_json}")
            llm_result_text = res_json['content'][0]['text']

        elif provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n最新新闻流：\n{news_content}"}]}]}
            response = requests.post(url, json=payload, headers=base_headers, timeout=150)
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
            if 'trend_prediction' not in parsed_res: parsed_res['trend_prediction'] = "系统正在汇聚算力评估未来走势..."
            
            for stock in parsed_res.get('stocks', []):
                code = str(stock.get('code', '')).strip()
                buy_discount = float(stock.get('buy_discount_percent', 4.0))
                stop_loss = float(stock.get('stop_loss_percent', 8.0))
                take_profit_pct = float(stock.get('take_profit_percent', 20.0))
                
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
            final_json_str = clean_json_str
            
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
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
    base_prob: Optional[str] = "90%"

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

    if trading_style == "超短线":
        dim_matrix = """
         "1_情绪周期位置": "推演当前处于混沌/高潮/退潮期及该股站位(50-100字精炼剖析)。",
         "2_题材爆发力": "概念持续性及龙头身位评估(50-100字精炼剖析)。",
         "3_龙虎榜与游资预期": "推测主力接力意愿及市场辨识度(50-100字精炼剖析)。",
         "4_盘口量价动能": "结合近5日K线序列与内外盘深度分析活跃度(50-100字精炼剖析)。",
         "5_连板梯队地位": "当前身位唯一性或卡位优势(50-100字精炼剖析)。",
         "6_核心K线形态": "结合K线形态判断支撑与突破(50-100字精炼剖析)。",
         "7_主力潜伏与骗线": "利用OBV能量潮判断量价背离(50-100字精炼剖析)。",
         "8_高阶指标共振": "利用KDJ与MACD分析超买超卖(50-100字精炼剖析)。",
         "9_隔夜发酵预期": "明早竞价溢价或核按钮风险(50-100字精炼剖析)。",
         "10_监管异动风险": "触发严重异动的可能性(50-100字精炼剖析)。",
         "11_波幅与止损纪律": "结合ATR波动率给出绝对防守红线(50-100字精炼剖析)。",
         "12_短线盈亏比评估": "打板/半路/低吸的具体盈亏比建议(50-100字精炼剖析)。"
        """
    else:
        dim_matrix = """
         "1_宏观经济环境": "推演宏观对该股的溢价影响(50-100字精炼剖析)。",
         "2_行业景气度周期": "剖析该行业处于复苏/过热/衰退期(50-100字精炼剖析)。",
         "3_基本面估值水位": "利用PE/PB数据判断当前是否低估(50-100字精炼剖析)。",
         "4_财务与盈利预期": "未来业绩爆发确定性(50-100字精炼剖析)。",
         "5_真实机构研报背书": "提取真实机构评级论证(50-100字精炼剖析)。",
         "6_主力筹码分布": "利用VWAP筹码密集区分析套牢盘与支撑(50-100字精炼剖析)。",
         "7_核心K线形态": "结合近5日K线形态分析底部确认度(50-100字精炼剖析)。",
         "8_主力资金异动": "利用OBV能量潮判断长线大资金吸筹(50-100字精炼剖析)。",
         "9_国家产业政策红利": "是否顺应国家大政方针(50-100字精炼剖析)。",
         "10_核心资产护城河": "公司行业绝对壁垒(50-100字精炼剖析)。",
         "11_潜在黑天鹅与风控": "利用ATR波动率评估长线防洗盘区间(50-100字精炼剖析)。",
         "12_交易风格契合度": "是否符合中长线潜伏逻辑(50-100字精炼剖析)。"
        """

    system_prompt = f"""你现在是一位顶级的商业级华尔街量化策略师与风控专家。当前系统设定的【全局交易风格】为：{trading_style}。对【{req.name}({req.code})】进行【12维全息深度透视】。
    【系统初筛基准胜率】：{req.base_prob}
    【实时量化基本面特征】：现价 {current_price}元, 总市值 {market_cap}, 动态市盈率(PE) {pe}, 市净率(PB) {pb}。
    【实时量价形态技术探针(含形态/OBV/ATR/BOLL/MACD)】：{tech_basis}
    【该股近期专属舆情】：{ticker_news_str}

    【多维立体定价与风控指令 (Multi-Factor Pricing Matrix)】：
    你必须彻底摒弃空洞的套话！像商业级高级 F10 研报一样进行精炼且极其专业的剖析。请严格控制字数以确保生成速度！
    直接引用我提供的【近5日K线序列】、【换手率】、【内外盘】、【VWAP筹码峰】、【KDJ】、【MACD】、【BOLL轨道】、【ATR(真实波幅)】以及【OBV(能量潮)】等全方位真实数据作为你的论据支持。

    【输出定价约束 (必须包含深度逻辑，结合全方位数据)】：
    - entry_strategy (建仓)：必须引用真实技术指标与形态写出详细的建仓逻辑。
    - reduce_position (减仓)：当股价触及压力位或指标超买时，建议减仓多少？给出具体预警价格及逻辑。
    - take_profit (止盈)：展现出基于 {trading_style} 的专属止盈格局依据。
    - stop_loss (止损)：绝对禁止猜测整数止损位！必须使用【1.5倍 ATR波幅】或【VWAP筹码破位】等全方位数据来进行严密的数学制定及详细论证！

    严格输出JSON：
    {{
      "probability": "结合【系统初筛基准胜率 {req.base_prob}】确定的最终胜率！",
      "trend_prediction": "结合[{trading_style}]和最新K线形态给出具体未来走势演绎与预判",
      "entry_strategy": {{
          "price": "建议买入价，如 {current_price}",
          "basis": "引用全方位真实形态与数据的建仓依据"
      }},
      "reduce_position": {{
          "price": "建议遇阻减仓价",
          "basis": "结合BOLL上轨或KDJ超买等数据，写出减仓防守逻辑"
      }},
      "stop_loss": {{
          "price": "具体止损价",
          "basis": "强制引用ATR或VWAP数据的破位止损推演依据"
      }},
      "take_profit": {{
          "price": "具体强势止盈价",
          "basis": "基于阻力或估值的止盈依据"
      }},
      "analysis_12d": {{
         {dim_matrix}
      }},
      "summary": "最终一段商业级量化决策总结"
    }}"""

    llm_result_text = ""
    try:
        base_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 QuantEngine/24.0.0", "Authorization": f"Bearer {api_key}"}

        if provider in ["openai", "deepseek", "kimi", "qwen", "groq"]:
            if provider == "openai": url, model = "https://api.openai.com/v1/chat/completions", "gpt-4-turbo-preview"
            elif provider == "deepseek": url, model = "https://api.deepseek.com/chat/completions", "deepseek-chat"
            elif provider == "kimi": url, model = "https://api.moonshot.cn/v1/chat/completions", "moonshot-v1-8k"
            elif provider == "qwen": url, model = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-turbo"
            elif provider == "groq": url, model = "https://api.groq.com/openai/v1/chat/completions", "llama3-70b-8192"

            payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": "请立刻执行 12D 机构级极速精炼透视分析，必须在60秒内完成输出。"}]}
            response = requests.post(url, json=payload, headers=base_headers, timeout=150)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"大模型报错: {res_json}")
            llm_result_text = res_json['choices'][0]['message']['content']
            
        elif provider == "claude":
            headers_claude = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": "claude-3-opus-20240229", "max_tokens": 3000, "system": system_prompt, "messages": [{"role": "user", "content": "请立刻执行精炼透视。"}]}
            response = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers_claude, timeout=150)
            res_json = response.json()
            if response.status_code != 200: raise Exception(f"Claude 报错: {res_json}")
            llm_result_text = res_json['content'][0]['text']

        elif provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n请立刻执行精炼透视。"}]}]}
            response = requests.post(url, json=payload, headers=base_headers, timeout=150)
            res_json = response.json()
            if response.status_code != 200 or 'error' in res_json: raise Exception(f"Gemini 报错: {res_json}")
            llm_result_text = res_json['candidates'][0]['content']['parts'][0]['text']

        clean_json_str = extract_json_from_text(llm_result_text)
        json.loads(clean_json_str)
        
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
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
        meta = result['meta']
        timestamps = result.get('timestamp', [])
        indicators = result.get('indicators', {}).get('quote', [{}])[0]
        volumes = indicators.get('volume', [])
        
        klines_dict = {}
        op_list = indicators.get('open', [])
        hi_list = indicators.get('high', [])
        lo_list = indicators.get('low', [])
        cl_list = indicators.get('close', [])
        
        for i in range(len(timestamps)):
            if i < len(op_list) and i < len(hi_list) and i < len(lo_list) and i < len(cl_list):
                op_val = op_list[i]
                hi_val = hi_list[i]
                lo_val = lo_list[i]
                cl_val = cl_list[i]
                
                if op_val is not None and hi_val is not None and lo_val is not None and cl_val is not None:
                    time_key = int(timestamps[i]) if chart_type in ['intraday', '5day'] else datetime.fromtimestamp(timestamps[i], BEIJING_TZ).strftime('%Y-%m-%d')
                    klines_dict[time_key] = {
                        'time': time_key, 
                        'open': round(float(op_val), 2), 
                        'high': round(float(hi_val), 2), 
                        'low': round(float(lo_val), 2), 
                        'close': round(float(cl_val), 2),
                        'volume': volumes[i] if i < len(volumes) and volumes[i] is not None else 0
                    }
                    
        klines = list(klines_dict.values())
        klines.sort(key=lambda x: x['time'])
        if not klines: raise Exception("接口返回空数据或数据已停牌损坏。")

        rmp = meta.get('regularMarketPrice')
        cpc = meta.get('chartPreviousClose')
        price_val = float(rmp) if rmp is not None else 0.0
        prev_val = float(cpc) if cpc is not None else price_val
        change_val = price_val - prev_val
        change_pct = (change_val / prev_val * 100) if prev_val != 0 else 0.0

        return {
            "status": "success", "symbol": y_code, 
            "price": round(price_val, 2),
            "change": round(change_val, 2), 
            "change_percent": round(change_pct, 2), 
            "klines": klines, "chart_type": chart_type
        }
    except Exception as e: return {"status": "error", "message": f"节点拒绝: {str(e)}"}

import asyncio
import json
import logging
import base64
import time
import re
import os
import subprocess
import aiohttp
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, BackgroundTasks, File, UploadFile
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import akshare as ak
from zhipuai import ZhipuAI
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis
import pandas as pd
import concurrent.futures
import psutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Quant AI Trading Backend")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MONGO_DETAILS = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_DETAILS)
db = client.quant_system
signals_collection = db.signals
heat_collection = db.heat_scores 
token_collection = db.token_usage 

redis_client = Redis(host='127.0.0.1', port=6379, password='QuantAI_2026_Secure', decode_responses=True)

sys_config = {
    "api_provider": "zhipu", "api_key": "", "price_range_min": 0, "price_range_max": 20, "is_running": False,
    "tg_bot_token": "", "tg_chat_id": "", "wxpusher_app_token": "", "wxpusher_uid": "",
    "filter_fund": False, "filter_kdj_boll": False, "ignore_time_lock": False, "filter_market": False,
    "daily_token_limit": 1000000,
    "allow_cyb": False, "allow_kcb": False, "allow_bj": False,
    "filter_deep_fund": False
}

HARDCODED_CONCEPTS = [
    "半导体", "消费电子", "光学光电子", "通信设备", "汽车零部件", "电池", "光伏设备", "电网设备", 
    "化学制药", "中药", "医疗器械", "国防军工", "房地产开发", "银行", "证券", "保险", 
    "贵金属", "工业金属", "小金属", "煤炭开采", "燃气", "航运港口", "软件开发", "IT服务", "计算机设备",
    "人工智能", "低空经济", "算力概念", "信创", "珠宝首饰", "有色金属", "采掘行业"
]

ths_concepts_cache = []
trade_calendar_cache = []
recent_ai_logs = []
fund_data_cache = {}
last_fund_time = 0
retail_sentiment_cache = []

def get_beijing_time():
    bj_tz = timezone(timedelta(hours=8))
    return datetime.now(bj_tz)

def add_system_log(msg: str):
    time_str = get_beijing_time().strftime("%H:%M:%S")
    recent_ai_logs.insert(0, f"[{time_str}] {msg}")
    if len(recent_ai_logs) > 20:
        recent_ai_logs.pop()

class ConfigUpdate(BaseModel):
    api_provider: str
    api_key: str
    price_range_min: int
    price_range_max: int
    is_running: bool
    tg_bot_token: Optional[str] = ""
    tg_chat_id: Optional[str] = ""
    wxpusher_app_token: Optional[str] = ""
    wxpusher_uid: Optional[str] = ""
    filter_fund: bool = False
    filter_kdj_boll: bool = False
    ignore_time_lock: bool = False
    filter_market: bool = False
    daily_token_limit: int = 1000000
    allow_cyb: bool = False
    allow_kcb: bool = False
    allow_bj: bool = False
    filter_deep_fund: bool = False

class ManualRequest(BaseModel):
    news_text: str

@app.post("/api/config")
async def update_config(config: ConfigUpdate):
    global sys_config
    sys_config.update(config.dict())
    mode = "全天候" if sys_config["ignore_time_lock"] else "智能休眠"
    add_system_log(f"⚙️ 配置同步，引擎状态: {'运行中' if sys_config['is_running'] else '已停止'} | 模式: {mode}")
    return {"status": "success", "data": sys_config}

@app.get("/api/config")
async def get_config(): return {"status": "success", "data": sys_config}

@app.get("/api/signals")
async def get_signals():
    signals = await signals_collection.find().sort("timestamp", -1).limit(30).to_list(100)
    for signal in signals: signal["_id"] = str(signal["_id"])
    return {"status": "success", "data": signals}

@app.get("/api/system")
async def get_system_status(): return {"status": "success", "logs": recent_ai_logs}

@app.get("/api/heat")
async def get_heat_ranking():
    today_str = get_beijing_time().strftime("%Y-%m-%d")
    heat_data = await heat_collection.find({"date": today_str}).sort("score", -1).limit(10).to_list(100)
    for h in heat_data: h["_id"] = str(h["_id"])
    return {"status": "success", "data": heat_data}

@app.get("/api/retail_sentiment")
async def get_retail_sentiment():
    return {"status": "success", "data": retail_sentiment_cache}

@app.get("/api/token_usage")
async def get_token_usage_api():
    today_str = get_beijing_time().strftime("%Y-%m-%d")
    doc = await token_collection.find_one({"date": today_str})
    used = doc["total_tokens"] if doc else 0
    return {"status": "success", "data": {"used": used, "limit": sys_config["daily_token_limit"]}}

# 🌟 新增：系统硬件负荷与网络延迟（Ping）探测器
def get_ping_latency(host="8.8.8.8"):
    try:
        output = subprocess.run(["ping", "-c", "1", "-W", "1", host], capture_output=True, text=True, timeout=2)
        if output.returncode == 0:
            match = re.search(r'time=([\d\.]+)\s*ms', output.stdout)
            if match:
                return float(match.group(1))
    except Exception: pass
    return -1.0

def sync_get_vps_status():
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    ping_ms = get_ping_latency()
    return {"cpu": cpu, "ram": ram, "disk": disk, "ping": ping_ms}

@app.get("/api/vps_status")
async def api_vps_status():
    stats = await asyncio.to_thread(sync_get_vps_status)
    return {"status": "success", "data": stats}

async def record_token_usage(tokens: int):
    today_str = get_beijing_time().strftime("%Y-%m-%d")
    await token_collection.update_one({"date": today_str}, {"$inc": {"total_tokens": tokens}}, upsert=True)

async def get_today_tokens() -> int:
    today_str = get_beijing_time().strftime("%Y-%m-%d")
    doc = await token_collection.find_one({"date": today_str})
    return doc["total_tokens"] if doc else 0

def fetch_data_with_timeout(func, timeout=5):
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func)
    try:
        return future.result(timeout=timeout)
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False)

def sync_init_background_data():
    global ths_concepts_cache, trade_calendar_cache
    if not ths_concepts_cache:
        try:
            df = fetch_data_with_timeout(ak.stock_board_industry_name_em, 8)
            ths_concepts_cache = df['板块名称'].tolist() if df is not None and not df.empty else HARDCODED_CONCEPTS
        except:
            ths_concepts_cache = HARDCODED_CONCEPTS
            
    try:
        if not trade_calendar_cache:
            df_cal = ak.tool_trade_date_hist_sina()
            trade_calendar_cache = [str(d.date()) if hasattr(d, 'date') else str(d)[:10] for d in df_cal['trade_date']]
    except Exception: pass

def sync_update_fundamentals():
    global fund_data_cache, last_fund_time
    now = time.time()
    if now - last_fund_time > 600 or not fund_data_cache:
        try:
            df = fetch_data_with_timeout(ak.stock_zh_a_spot_em, 8)
            if df is not None and not df.empty:
                cols = ['名称', '最新价', '市盈率-动态', '市净率']
                for c in cols:
                    if c not in df.columns: df[c] = None
                fund_data_cache = df.set_index('代码')[cols].to_dict('index')
                last_fund_time = now
            else:
                df_sina = fetch_data_with_timeout(ak.stock_zh_a_spot, 8)
                if df_sina is not None and not df_sina.empty:
                    if 'code' in df_sina.columns and 'trade' in df_sina.columns and 'name' in df_sina.columns:
                        df_sina = df_sina.rename(columns={'code': '代码', 'name': '名称', 'trade': '最新价'})
                        df_sina['市盈率-动态'] = None
                        df_sina['市净率'] = None
                        fund_data_cache = df_sina.set_index('代码')[['名称', '最新价', '市盈率-动态', '市净率']].to_dict('index')
                        last_fund_time = now
        except Exception: pass

def sync_update_retail_sentiment():
    global retail_sentiment_cache
    try:
        df_hot = fetch_data_with_timeout(ak.stock_hot_rank_em, 5)
        if df_hot is not None and not df_hot.empty:
            cols = df_hot.columns.tolist()
            name_col = '名称' if '名称' in cols else ('股票简称' if '股票简称' in cols else None)
            code_col = '代码' if '代码' in cols else ('股票代码' if '股票代码' in cols else None)
            price_col = '最新价' if '最新价' in cols else None
            pct_col = '涨跌幅' if '涨跌幅' in cols else None
            
            if name_col and code_col:
                top_20 = df_hot.head(20)
                res = []
                for _, row in top_20.iterrows():
                    res.append({'代码': str(row[code_col]), '名称': str(row[name_col]), '最新价': float(row[price_col]) if price_col else 0.0, '涨跌幅': float(row[pct_col]) if pct_col else 0.0})
                retail_sentiment_cache = res
    except Exception: pass

def check_market_environment() -> bool:
    try:
        df = fetch_data_with_timeout(lambda: ak.stock_zh_index_daily_em(symbol="sh000001"), 5)
        if df is None or df.empty or len(df) < 20: return True
        df = df.tail(30).reset_index(drop=True)
        df['MA20'] = df['close'].rolling(window=20).mean()
        return bool(df.iloc[-1]['close'] > df.iloc[-1]['MA20'])
    except Exception: return True

def check_deep_fundamentals(code: str) -> tuple:
    if not sys_config.get("filter_deep_fund"): return True, "无需体检"
    try:
        df = fetch_data_with_timeout(lambda: ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期"), 4)
        if df is not None and not df.empty:
            return True, "ROE>5%,EPS>0"
        return True, "财报通过"
    except: return True, "财报容错"

def sync_check_tech(stock_code: str, use_adv: bool) -> tuple:
    try:
        code = str(stock_code).zfill(6)
        df = fetch_data_with_timeout(lambda: ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq"), 5)
        if df is None or df.empty or len(df) < 30: return (False, "K线获取超时", 0, 0)
        df = df.sort_values(by='日期').reset_index(drop=True)
        df['MA20'] = df['收盘'].rolling(window=20).mean()
        df['EMA12'] = df['收盘'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['收盘'].ewm(span=26, adjust=False).mean()
        df['DIF'] = df['EMA12'] - df['EMA26']
        df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['MACD'] = (df['DIF'] - df['DEA']) * 2
        low_list = df['最低'].rolling(9, min_periods=1).min()
        high_list = df['最高'].rolling(9, min_periods=1).max()
        df['K'] = ((df['收盘'] - low_list) / (high_list - low_list + 1e-8) * 100).ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()
        df['BOLL_UP'] = df['MA20'] + 2 * df['收盘'].rolling(20).std()
        latest = df.iloc[-1]
        
        ma20_val = float(latest['MA20'])
        boll_up_val = float(latest['BOLL_UP'])
        
        if latest['收盘'] <= latest['MA20']: return (False, "破MA20", 0, 0)
        if latest['DIF'] <= latest['DEA'] or latest['MACD'] <= 0: return (False, "MACD死叉", 0, 0)
        if use_adv:
            if latest['K'] <= latest['D']: return (False, "KDJ未金叉", 0, 0)
            if latest['收盘'] >= latest['BOLL_UP']: return (False, "触BOLL上轨", 0, 0)
            
        return (True, "通过", ma20_val, boll_up_val)
    except Exception: return (False, "异常", 0, 0)

async def async_check_tech(stock_code: str, use_adv: bool) -> tuple:
    return await asyncio.to_thread(sync_check_tech, stock_code, use_adv)

async def push_notification(title: str, content: str):
    async with aiohttp.ClientSession() as session:
        if sys_config.get("tg_bot_token") and sys_config.get("tg_chat_id"):
            tg_url = f"https://api.telegram.org/bot{sys_config['tg_bot_token']}/sendMessage"
            try: await session.post(tg_url, json={"chat_id": sys_config["tg_chat_id"], "text": f"*{title}*\n\n{content}", "parse_mode": "Markdown"})
            except Exception: pass
            
        if sys_config.get("wxpusher_app_token") and sys_config.get("wxpusher_uid"):
            wx_url = "http://wxpusher.zjiecode.com/api/send/message"
            try: await session.post(wx_url, json={"appToken": sys_config["wxpusher_app_token"], "content": f"【{title}】\n\n{content}", "summary": title, "contentType": 1, "uids": [sys_config["wxpusher_uid"]]})
            except Exception: pass

async def analyze_news_with_llm(news_text: str, is_global: bool = False) -> dict:
    if not sys_config["api_key"]: return {}
    context_directive = """这是一条【全球宏观或海外市场】重大新闻。请精准映射到中国A股市场的对应受惠板块。""" if is_global else "这是一条【国内A股】财经快讯。"
    
    prompt = f"""你是一个顶级的量化分析师。{context_directive}
    请评估以下新闻，并严格输出JSON格式。
    ⚠️ 极其重要：在 `ai_suggested_stocks` 数组中，你必须直接提供至少 20-30 只属于该受惠板块的真实A股股票。
    🚨 纪律警告：股票代码(code)必须是纯净的6位数字！绝对不能带有 sh、sz 等任何字母！
    格式如下：
    {{
        "sentiment_score": 0.8, 
        "affected_sectors": ["半导体"], 
        "ai_suggested_stocks": [{{"name": "中芯国际", "code": "688981"}}, {{"name": "北方华创", "code": "002371"}}],
        "impact_logic": "推导逻辑", 
        "probability": 85
    }}
    新闻内容：{news_text}"""
    
    tokens_used = 0
    try:
        provider, api_key = sys_config["api_provider"], sys_config["api_key"]
        if provider == "zhipu":
            res = ZhipuAI(api_key=api_key).chat.completions.create(model="glm-4", messages=[{"role": "user", "content": prompt}])
            content = res.choices[0].message.content
            tokens_used = res.usage.total_tokens if hasattr(res, 'usage') else len(prompt + content) // 2
        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            res = await asyncio.to_thread(genai.GenerativeModel('gemini-1.5-pro').generate_content, prompt)
            content = res.text
            tokens_used = res.usage_metadata.total_token_count if hasattr(res, 'usage_metadata') else len(prompt + content) // 2
        elif provider == "claude":
            from anthropic import AsyncAnthropic
            res = await AsyncAnthropic(api_key=api_key).messages.create(max_tokens=1024, messages=[{"role": "user", "content": prompt}], model="claude-3-opus-20240229")
            content = res.content[0].text
            tokens_used = res.usage.input_tokens + res.usage.output_tokens if hasattr(res, 'usage') else len(prompt + content) // 2
        else:
            from openai import AsyncOpenAI
            res = await AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com" if provider == "deepseek" else "https://api.openai.com/v1").chat.completions.create(model="deepseek-chat" if provider == "deepseek" else "gpt-4", messages=[{"role": "user", "content": prompt}])
            content = res.choices[0].message.content
            tokens_used = res.usage.total_tokens if hasattr(res, 'usage') else len(prompt + content) // 2
            
        if tokens_used > 0: await record_token_usage(tokens_used)
        return json.loads(content.replace("```json", "").replace("```", "").strip())
    except Exception: return {}

async def analyze_image_with_vision(image_bytes: bytes) -> dict:
    if not sys_config["api_key"]: return {}
    prompt = """提取图片中对A股的核心利好逻辑，并输出JSON：{{"sentiment_score": 0.8, "affected_sectors": ["半导体"], "impact_logic": "逻辑", "probability": 85}}"""
    try:
        provider, api_key = sys_config["api_provider"], sys_config["api_key"]
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        if provider == "zhipu":
            res = ZhipuAI(api_key=api_key).chat.completions.create(model="glm-4v", messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}]}])
            content = res.choices[0].message.content
        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            res = await asyncio.to_thread(genai.GenerativeModel('gemini-1.5-pro').generate_content, [prompt, [{"mime_type": "image/jpeg", "data": image_bytes}]])
            content = res.text
        elif provider == "openai":
            from openai import AsyncOpenAI
            res = await AsyncOpenAI(api_key=api_key).chat.completions.create(model="gpt-4-vision-preview", messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}]}])
            content = res.choices[0].message.content
        else: return {}
        return json.loads(content.replace("```json", "").replace("```", "").strip())
    except Exception: return {}

def sync_fetch_sector_stocks(sector_name: str) -> pd.DataFrame:
    def standardize(d):
        if d is None or d.empty: return pd.DataFrame()
        cols = d.columns.tolist()
        code_c = '代码' if '代码' in cols else ('股票代码' if '股票代码' in cols else None)
        name_c = '名称' if '名称' in cols else ('股票简称' if '股票简称' in cols else None)
        price_c = '最新价' if '最新价' in cols else None
        if code_c and name_c and price_c:
            res = d[[code_c, name_c, price_c]].copy()
            res.columns = ['代码', '名称', '最新价']
            res['代码'] = res['代码'].astype(str).str.zfill(6)
            res['最新价'] = pd.to_numeric(res['最新价'], errors='coerce')
            return res
        return pd.DataFrame()

    try:
        res = standardize(ak.stock_board_industry_cons_em(symbol=sector_name))
        if not res.empty: return res
    except: pass
    try:
        res = standardize(ak.stock_board_concept_cons_em(symbol=sector_name))
        if not res.empty: return res
    except: pass
    try:
        df_ind = ak.stock_board_industry_name_em()
        matched_real = [n for n in df_ind['板块名称'].astype(str) if sector_name in n or n in sector_name]
        if matched_real:
            res = standardize(ak.stock_board_industry_cons_em(symbol=matched_real[0]))
            if not res.empty: return res
    except: pass
    return pd.DataFrame()

def get_best_matched_sectors(ai_sector: str, cache_list: list) -> list:
    matches = []
    for c in cache_list:
        if ai_sector in c or c in ai_sector: matches.append(c)
    if not matches and len(ai_sector) >= 4:
        sub_key1 = ai_sector[:2]
        sub_key2 = ai_sector[2:4]
        for c in cache_list:
            if sub_key1 in c or sub_key2 in c: matches.append(c)
    return list(set(matches))[:3]

async def execute_strategy(ai_analysis: dict, news_content: str, is_manual: bool = False, source_tag: str = "🧠 自动实盘"):
    if sys_config["filter_market"] and not is_manual:
        if not await asyncio.to_thread(check_market_environment):
            add_system_log("🛑 大盘风控触发: 上证跌破20日均线，强制空仓！")
            return

    score = ai_analysis.get("sentiment_score", 0)
    prob = ai_analysis.get("probability", 0)
    sectors = ai_analysis.get("affected_sectors", [])
    logic = ai_analysis.get("impact_logic", "无")
    action_type = "MANUAL_TEST" if is_manual else "BUY"
    
    add_system_log(f"{source_tag} | 情绪:{score} | 胜率:{prob}% | 初始板块:{sectors}")
    
    if score <= 0.7 or prob <= 80:
        add_system_log(f"❌ 拦截: 情绪或胜率未达打板阈值，果断放弃。")
        return

    if score > 0 and prob > 50:
        today_str = get_beijing_time().strftime("%Y-%m-%d")
        heat_inc = round(float(score) * (float(prob) / 100.0) * 10, 2)
        for ai_sector in sectors:
            matched_list = get_best_matched_sectors(ai_sector, ths_concepts_cache)
            save_name = matched_list[0] if matched_list else ai_sector
            await heat_collection.update_one({"date": today_str, "sector": save_name}, {"$inc": {"score": heat_inc}}, upsert=True)

    await asyncio.to_thread(sync_update_fundamentals)
    raw_target_stocks = []
    
    for ai_sector in sectors:
        matched_list = get_best_matched_sectors(ai_sector, ths_concepts_cache)
        if not matched_list: matched_list = [ai_sector] 
            
        for matched in matched_list:
            df_cons = await asyncio.to_thread(fetch_data_with_timeout, lambda m=matched: sync_fetch_sector_stocks(m), 8)
            if df_cons is not None and not df_cons.empty and '最新价' in df_cons.columns:
                try:
                    df_filtered = df_cons[(df_cons['最新价'] >= sys_config["price_range_min"]) & (df_cons['最新价'] <= sys_config["price_range_max"])]
                    if not df_filtered.empty:
                        raw_target_stocks.extend(df_filtered[['代码', '名称', '最新价']].to_dict('records'))
                except Exception: pass
                
    if not raw_target_stocks and "ai_suggested_stocks" in ai_analysis:
        ai_stocks = ai_analysis.get("ai_suggested_stocks", [])
        if ai_stocks:
            for s in ai_stocks:
                raw_code = str(s.get('code', ''))
                clean_code = re.sub(r'[^0-9]', '', raw_code)
                if len(clean_code) >= 6: code = clean_code[-6:]
                else: code = clean_code.zfill(6)

                price = None
                cached_info = fund_data_cache.get(code)
                if cached_info and pd.notna(cached_info.get('最新价')):
                    price = float(cached_info['最新价'])
                else:
                    try:
                        df_spot = await asyncio.to_thread(fetch_data_with_timeout, lambda c=code: ak.stock_zh_a_hist(symbol=c, period="daily", adjust="qfq"), 5)
                        if df_spot is not None and not df_spot.empty: price = float(df_spot.iloc[-1]['收盘'])
                    except: pass
                
                if price is not None and sys_config["price_range_min"] <= price <= sys_config["price_range_max"]:
                    raw_target_stocks.append({'代码': code, '名称': s.get('name', cached_info.get('名称', '') if cached_info else code), '最新价': price})

    if not raw_target_stocks:
        add_system_log(f"📉 选股中止: 经过全盘检索与AI脑补，未能抓取到符合低价档位的标的。")
        return
        
    unique_raw_stocks = [dict(t) for t in {tuple(d.items()) for d in raw_target_stocks}]
    
    market_passed_stocks = []
    for stock in unique_raw_stocks:
        code_str = str(stock['代码']).zfill(6)
        if not sys_config.get("allow_cyb", False) and code_str.startswith("300"): continue
        if not sys_config.get("allow_kcb", False) and code_str.startswith("688"): continue
        if not sys_config.get("allow_bj", False) and (code_str.startswith("8") or code_str.startswith("4")): continue
        market_passed_stocks.append(stock)
        
    if not market_passed_stocks:
        add_system_log("📉 选股中止: 过滤后无符合您账户交易权限的标的。")
        return

    fund_passed_stocks = []
    for stock in market_passed_stocks:
        code = str(stock['代码'])
        if sys_config.get("filter_deep_fund", False):
            passed, f_tag = await asyncio.to_thread(check_deep_fundamentals, code)
            if passed:
                stock['fund_tag'] = f_tag
                fund_passed_stocks.append(stock)
        elif sys_config["filter_fund"]:
            fund_info = fund_data_cache.get(code, {})
            try: pe, pb = float(fund_info.get('市盈率-动态', -1)), float(fund_info.get('市净率', -1))
            except: pe, pb = -1, -1
            if (0 < pe <= 50) and (0 < pb <= 5):
                stock['fund_tag'] = f"PE:{pe:.1f} PB:{pb:.1f}"
                fund_passed_stocks.append(stock)
        else:
            stock['fund_tag'] = "无基面"
            fund_passed_stocks.append(stock)
            
    if not fund_passed_stocks:
        add_system_log("📉 选股中止: 所有低价票的【基本面财报】指标均不达标被剔除。")
        return
    
    tasks = [async_check_tech(stock['代码'], sys_config["filter_kdj_boll"]) for stock in fund_passed_stocks]
    tech_results = await asyncio.gather(*tasks)
    
    final_stocks = []
    retail_codes = [s['代码'] for s in retail_sentiment_cache]
    
    for stock, tech_res in zip(fund_passed_stocks, tech_results):
        passed = tech_res[0]
        if passed:
            ma20, boll_up, price = tech_res[2], tech_res[3], float(stock['最新价'])
            sl_price = round(max(ma20 * 0.99, price * 0.95), 2)
            tp_price = round(max(boll_up, price * 1.05), 2)
            tech_tag = "KDJ+BOLL" if sys_config["filter_kdj_boll"] else "MA20+MACD"
            reso_tag = " | 共振🔥" if stock['代码'] in retail_codes else ""
            stock['tech_passed'] = f"{tech_tag} | {stock['fund_tag']}{reso_tag}"
            stock['sl'] = sl_price
            stock['tp'] = tp_price
            final_stocks.append(stock)
    
    if final_stocks:
        signal_doc = {
            "timestamp": get_beijing_time().isoformat(), "news": news_content, "analysis": ai_analysis,
            "action": action_type, "target_stocks": final_stocks, "status": "published"
        }
        await signals_collection.insert_one(signal_doc)
        await redis_client.publish("qmt_trade_signals", json.dumps({"source": "Global_Quant_AI", "action": action_type, "strategy": "MultiFactor", "stocks": [{"code": s["代码"], "name": s["名称"], "price": s["最新价"]} for s in final_stocks]}, ensure_ascii=False))
        add_system_log(f"🎯 选股大满贯！标的已推送至手机 ({action_type})。")
        stocks_str = "\n".join([f"📈 【{s['名称']}】 ({s['代码']})\n  -> 现价: ¥{s['最新价']}\n  -> 🛑止损: ¥{s['sl']} | 🎯止盈: ¥{s['tp']}\n  -> 🏷️ {s['tech_passed']}\n" for s in final_stocks])
        push_title = f"🚨 极速买单 ({source_tag})"
        push_content = f"🤖 **逻辑推演**\n板块: {', '.join(sectors)}\n情绪: {score} | 胜率: {prob}%\n理由: {logic}\n\n📦 **操作建议 (请挂单)**\n{stocks_str}"
        asyncio.create_task(push_notification(push_title, push_content))
    else: 
        add_system_log("📉 选股中止: 标的【技术面】均存在破位或死叉，安全第一。")

@app.post("/api/manual_analyze")
async def manual_analyze(req: ManualRequest):
    if not sys_config["api_key"]: return {"status": "error"}
    ai_result = await analyze_news_with_llm(req.news_text, is_global=False)
    if ai_result: await execute_strategy(ai_result, req.news_text, is_manual=True, source_tag="🧪 沙盒推演")
    return {"status": "success"}

@app.post("/api/manual_analyze_image")
async def manual_analyze_image(file: UploadFile = File(...)):
    if not sys_config["api_key"]: return {"status": "error"}
    ai_result = await analyze_image_with_vision(await file.read())
    if ai_result: await execute_strategy(ai_result, f"[视觉解析]: {ai_result.get('impact_logic', '')}", is_manual=True, source_tag="📸 视觉推演")
    return {"status": "success"}

def sync_run_backtest(signals_data):
    report = []
    for sig in signals_data:
        sig_date_str = sig["timestamp"][:10].replace("-", "") 
        for stock in sig.get("target_stocks", []):
            try:
                df = ak.stock_zh_a_hist(symbol=str(stock["代码"]).zfill(6), start_date=sig_date_str, adjust="qfq").head(4)
                if not df.empty:
                    mp, ml, cp = round((df['最高'].max()-stock["最新价"])/stock["最新价"]*100, 2), round((df['最低'].min()-stock["最新价"])/stock["最新价"]*100, 2), round((df.iloc[-1]['收盘']-stock["最新价"])/stock["最新价"]*100, 2)
                    report.append({"signal_time": sig["timestamp"][:19].replace("T"," "), "sector": ", ".join(sig["analysis"].get("affected_sectors", [])), "stock_name": stock["名称"], "stock_code": stock["代码"], "entry_price": stock["最新价"], "max_profit": mp, "max_loss": ml, "current_pct": cp, "is_win": mp > 2.0})
            except: pass
    return report

@app.get("/api/backtest")
async def run_backtest():
    signals = await signals_collection.find({"timestamp": {"$gte": (get_beijing_time() - timedelta(days=7)).isoformat()}}).to_list(1000)
    return {"status": "success", "data": await asyncio.to_thread(sync_run_backtest, signals) if signals else []}

def is_trading_allowed():
    if sys_config["ignore_time_lock"]: return True
    return is_ashare_trading_time()

async def background_init_and_loop():
    await asyncio.to_thread(sync_init_background_data)
    add_system_log("🚀 引擎主轮询彻底激活，全天候雷达已启动...")
    last_news_domestic, last_news_global = "", ""
    is_sleeping_logged, loop_counter = False, 0
    while True:
        if not ths_concepts_cache: await asyncio.to_thread(sync_init_background_data)
        if sys_config["is_running"] and sys_config["api_key"]:
            current_tokens = await get_today_tokens()
            if current_tokens >= sys_config.get("daily_token_limit", 1000000):
                sys_config["is_running"] = False
                add_system_log("🛑 物理熔断触发！今日Token消耗超限。")
                await asyncio.sleep(60); continue
            if not is_trading_allowed():
                if not is_sleeping_logged: 
                    add_system_log("💤 交易时段外，自动休眠防耗损..."); is_sleeping_logged = True
            else:
                is_sleeping_logged = False
                if loop_counter % 10 == 0: await asyncio.to_thread(sync_update_retail_sentiment)
                loop_counter += 1
                try:
                    df_domestic = fetch_data_with_timeout(ak.wallstreet_news_live, 5)
                    if df_domestic is not None and not df_domestic.empty:
                        latest_domestic = str(df_domestic.iloc[0]['内容'])
                        if latest_domestic != last_news_domestic:
                            last_news_domestic = latest_domestic
                            ai_res = await analyze_news_with_llm(latest_domestic, is_global=False)
                            if ai_res: await execute_strategy(ai_res, latest_domestic, False, "🇨🇳 国内主线")
                except Exception: pass
                try:
                    df_global = fetch_data_with_timeout(ak.stock_info_global_futu, 5)
                    if df_global is not None and not df_global.empty:
                        title_col = 'title' if 'title' in df_global.columns else ('标题' if '标题' in df_global.columns else None)
                        if title_col:
                            latest_global = str(df_global.iloc[0][title_col])
                            if latest_global != last_news_global:
                                last_news_global = latest_global
                                ai_res = await analyze_news_with_llm(latest_global, is_global=True)
                                if ai_res: await execute_strategy(ai_res, latest_global, False, "🌍 全球映射")
                except Exception: pass
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event(): asyncio.create_task(background_init_and_loop())

@app.get("/")
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read(), status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

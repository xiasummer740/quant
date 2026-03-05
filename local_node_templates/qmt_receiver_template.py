import redis, json, time, sys
from xtquant import xtdata, xtconstant
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback

# 【用户请修改以下配置】
VPS_IP = "YOUR_VPS_IP_HERE"  # 替换为您的云端服务器公网 IP
REDIS_PASS = "YOUR_REDIS_PASSWORD" # 替换为云端 Redis 密码
CHANNEL = "qmt_trade_signals"
QMT_PATH = r"D:\您的券商QMT交易端\userdata" # 替换为真实的本地 QMT 路径
ACCOUNT_ID = "YOUR_ACCOUNT_ID" # 替换为资金账号
TRADE_AMOUNT = 10000 # 单笔交易金额上限

class MyXtTraderCallback(XtQuantTraderCallback):
    def on_stock_order(self, order): print(f"📈 委托: {order.stock_code} | 状态: {order.order_status}")
    def on_stock_trade(self, trade): print(f"💰 成交: {trade.stock_code} | 均价: {trade.traded_price}")

def get_qmt_code(symbol):
    symbol = str(symbol).zfill(6)
    return f"{symbol}.SH" if symbol.startswith('6') else (f"{symbol}.SZ" if symbol.startswith(('0','3')) else f"{symbol}.BJ")

if __name__ == "__main__":
    print("🚀 QMT 实盘节点启动中...")
    session_id = int(time.time())
    xt_trader = XtQuantTrader(QMT_PATH, session_id)
    acc = xtconstant.StockAccount(ACCOUNT_ID)
    xt_trader.register_callback(MyXtTraderCallback())
    xt_trader.start()
    
    if xt_trader.connect() != 0 or xt_trader.subscribe(acc) != 0:
        print("❌ QMT 启动失败，请检查路径和账号。")
        sys.exit(1)
        
    try:
        r = redis.Redis(host=VPS_IP, port=6379, password=REDIS_PASS, decode_responses=True)
        r.ping()
        print("✅ 已连接云端大脑，监听中...")
        pubsub = r.pubsub()
        pubsub.subscribe(CHANNEL)
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                if data.get('action') == "BUY":
                    for stock in data.get('stocks', []):
                        code, price = get_qmt_code(stock['code']), float(stock['price'])
                        shares = max(100, int((TRADE_AMOUNT / price) / 100) * 100)
                        print(f"🔥 执行买入: {code} | {shares}手")
                        xt_trader.order_stock(acc, code, xtconstant.STOCK_BUY, shares, xtconstant.FIX_PRICE, price, "AI", "AI指令")
    except Exception as e: print(f"❌ 运行异常: {e}")

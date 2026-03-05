import redis, json, sys, easytrader

# 【用户请修改以下配置】
VPS_IP = "YOUR_VPS_IP_HERE" 
REDIS_PASS = "YOUR_REDIS_PASSWORD"
CHANNEL = "qmt_trade_signals"
THS_XIADAN_PATH = r"C:\同花顺软件\xiadan.exe" # 替换为同花顺独立下单程序路径
TRADE_AMOUNT = 10000

if __name__ == "__main__":
    print("🤖 同花顺 RPA 节点启动中...")
    try:
        user = easytrader.use('ths')
        user.connect(THS_XIADAN_PATH)
        print("✅ 成功接管同花顺 PC 端！")
    except Exception as e:
        print(f"❌ RPA 接管失败: {e}")
        sys.exit(1)

    try:
        r = redis.Redis(host=VPS_IP, port=6379, password=REDIS_PASS, decode_responses=True)
        pubsub = r.pubsub()
        pubsub.subscribe(CHANNEL)
        print("✅ 已连接云端大脑，监听中(请勿移动鼠标)...")
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                if data.get('action') == "BUY":
                    for stock in data.get('stocks', []):
                        code, price = str(stock['code']).zfill(6), float(stock['price'])
                        shares = max(100, int((TRADE_AMOUNT / price) / 100) * 100)
                        print(f"🔥 模拟键鼠买入: {code} | {shares}手")
                        user.buy(code, price=price, amount=shares)
    except Exception as e: print(f"❌ 运行异常: {e}")

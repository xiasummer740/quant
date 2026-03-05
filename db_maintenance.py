import asyncio
import logging
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("QuantMaintenance")

def get_beijing_time():
    bj_tz = timezone(timedelta(hours=8))
    return datetime.now(bj_tz)

async def clean_old_data():
    logger.info("=== 数据库垃圾回收任务启动 ===")
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.quant_system
    
    # 计算 30 天前的北京时间基准线
    thirty_days_ago_dt = get_beijing_time() - timedelta(days=30)
    
    # 1. 清理过期交易信号 (timestamp 格式: 2026-03-05T14:30:00.123456+08:00)
    sig_cutoff = thirty_days_ago_dt.isoformat()
    sig_res = await db.signals.delete_many({"timestamp": {"$lt": sig_cutoff}})
    logger.info(f"清理过期交易信号: 成功删除 {sig_res.deleted_count} 条。")
    
    # 2. 清理过期板块热度数据 (date 格式: 2026-03-05)
    heat_cutoff = thirty_days_ago_dt.strftime("%Y-%m-%d")
    heat_res = await db.heat_scores.delete_many({"date": {"$lt": heat_cutoff}})
    logger.info(f"清理过期题材热度: 成功删除 {heat_res.deleted_count} 条。")
    
    logger.info("=== 数据库垃圾回收任务完成 ===")

if __name__ == "__main__":
    asyncio.run(clean_old_data())

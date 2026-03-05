#!/bin/bash
# 量化系统全局日常维护脚本

LOG_FILE="/var/log/quant_maintenance.log"
echo "==================================================" >> $LOG_FILE
echo "系统日常维护开始时间: $(date)" >> $LOG_FILE

# 1. 调用 Python 脚本清理 MongoDB 过期数据
source /var/www/quant_system/venv/bin/activate
python3 /var/www/quant_system/db_maintenance.py >> $LOG_FILE 2>&1

# 2. 清理 Systemd 日志 (仅保留最近 7 天，或者最大 500MB，防止打爆磁盘)
echo "[清理系统日志]..." >> $LOG_FILE
journalctl --vacuum-time=7d >> $LOG_FILE 2>&1
journalctl --vacuum-size=500M >> $LOG_FILE 2>&1

# 3. 清理 Nginx 历史压缩日志 (保留最近 14 天)
echo "[清理 Nginx 历史日志]..." >> $LOG_FILE
find /var/log/nginx -type f -name "*.gz" -mtime +14 -exec rm -f {} \; >> $LOG_FILE 2>&1

# 4. 清理 APT 缓存及系统无用依赖
echo "[清理 APT 系统缓存]..." >> $LOG_FILE
apt-get clean >> $LOG_FILE 2>&1
apt-get autoremove -y >> $LOG_FILE 2>&1

echo "系统日常维护完成时间: $(date)" >> $LOG_FILE
echo "==================================================" >> $LOG_FILE

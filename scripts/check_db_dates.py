"""查看数据库中各表的日期范围"""
import sqlite3
from pathlib import Path
import datetime

db = Path(__file__).resolve().parent.parent / "bybit_eth_data" / "data" / "processed" / "eth_perpetual.db"
conn = sqlite3.connect(str(db))
c = conn.cursor()

print(f"数据库: {db}")
print(f"大小: {db.stat().st_size / (1024*1024):.1f} MB\n")
print(f"{'表名':20s} {'最早日期':15s} {'最晚日期':15s} {'行数':>10s}")
print("-" * 60)

tables = ['kline_1m','kline_5m','kline_15m','kline_1h','kline_4h','kline_1d']
total_rows = 0
for t in tables:
    try:
        c.execute(f"SELECT MIN(open_time), MAX(open_time), COUNT(*) FROM {t}")
        r = c.fetchone()
        if r and r[0]:
            min_dt = datetime.datetime.fromtimestamp(r[0]/1000).strftime('%Y-%m-%d')
            max_dt = datetime.datetime.fromtimestamp(r[1]/1000).strftime('%Y-%m-%d')
            print(f"{t:20s} {min_dt:15s} {max_dt:15s} {r[2]:>10,}")
            total_rows += r[2]
    except Exception as e:
        print(f"{t:20s} 错误: {e}")

conn.close()
print("-" * 60)
print(f"{'总计':20s} {'':15s} {'':15s} {total_rows:>10,}")

# 估计2024年起的数据量
print(f"\n估计2024年起的数据量:")
for t in tables:
    try:
        conn = sqlite3.connect(str(db))
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM {t} WHERE open_time >= 1704067200000")  # 2024-01-01
        cnt = c.fetchone()[0]
        c.execute(f"SELECT COUNT(*) FROM {t}")
        total = c.fetchone()[0]
        print(f"  {t:15s}: {cnt:>8,} / {total:>8,} 行 ({cnt/total*100:.1f}%)")
        conn.close()
    except:
        pass

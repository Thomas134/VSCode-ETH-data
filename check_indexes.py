import sqlite3
from pathlib import Path

db = Path("bybit_eth_data/data/processed/eth_perpetual.db")
conn = sqlite3.connect(str(db))
cursor = conn.cursor()

print("=== 主数据库索引 ===")
for table in ["kline_1m", "kline_5m", "kline_15m", "kline_1h", "kline_4h", "kline_1d"]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,))
    indexes = [r[0] for r in cursor.fetchall()]
    print(f"  {table}: {indexes}")
    # 看索引的具体列
    for idx in indexes:
        cursor.execute(f"PRAGMA index_info({idx})")
        cols = [(r[1], r[2]) for r in cursor.fetchall()]
        print(f"    {idx}: {cols}")

conn.close()

struct_db = Path("bybit_eth_data/data/processed/eth_structure.db")
conn2 = sqlite3.connect(str(struct_db))
cursor2 = conn2.cursor()

print("\n=== 结构数据库索引 ===")
for table in ["kline_1m_std", "kline_5m_std", "kline_15m_std", "kline_1h_std", "kline_4h_std", "kline_1d_std"]:
    cursor2.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,))
    indexes = [r[0] for r in cursor2.fetchall()]
    print(f"  {table}: {indexes}")
    for idx in indexes:
        cursor2.execute(f"PRAGMA index_info({idx})")
        cols = [(r[1], r[2]) for r in cursor2.fetchall()]
        print(f"    {idx}: {cols}")

conn2.close()

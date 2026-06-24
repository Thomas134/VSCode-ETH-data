import sqlite3
from pathlib import Path

# 结构数据库
db = Path("bybit_eth_data/data/processed/eth_structure.db")
conn = sqlite3.connect(str(db))
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print("=== eth_structure.db 所有表 ===")
for t in tables:
    print(f"  {t[0]}")

print()
for t in tables:
    name = t[0]
    cursor.execute(f"PRAGMA table_info({name})")
    cols = cursor.fetchall()
    print(f"--- {name} ---")
    for c in cols:
        print(f"  {c[1]:30s} {c[2]:20s} nullable={c[3]} default={c[4]}")
    print()
conn.close()

# 原始K线数据库
print("\n" + "="*60)
print("=== eth_perpetual.db ===")
db2 = Path("bybit_eth_data/data/processed/eth_perpetual.db")
conn2 = sqlite3.connect(str(db2))
cursor2 = conn2.cursor()
cursor2.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables2 = cursor2.fetchall()
for t in tables2:
    print(f"  {t[0]}")

for t in tables2:
    name = t[0]
    cursor2.execute(f"PRAGMA table_info({name})")
    cols = cursor2.fetchall()
    print(f"\n--- {name} ---")
    for c in cols:
        print(f"  {c[1]:30s} {c[2]:20s} nullable={c[3]} default={c[4]}")
conn2.close()

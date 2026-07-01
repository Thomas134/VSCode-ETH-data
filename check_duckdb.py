"""检查 DuckDB 数据库中有哪些表"""
import duckdb

DB_PATH = "duckdb_migration/duckdb_data/eth_perpetual.duckdb"
print(f"连接: {DB_PATH}")
conn = duckdb.connect(DB_PATH, read_only=True)

tables = conn.execute("SHOW TABLES").fetchall()
print(f"\n找到 {len(tables)} 个表:")
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]}: {count:,} 条")
conn.close()

DB_PATH2 = "duckdb_migration/duckdb_data/eth_structure.duckdb"
print(f"\n连接: {DB_PATH2}")
conn2 = duckdb.connect(DB_PATH2, read_only=True)

tables2 = conn2.execute("SHOW TABLES").fetchall()
print(f"\n找到 {len(tables2)} 个表:")
for t in tables2:
    count = conn2.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]}: {count:,} 条")
conn2.close()
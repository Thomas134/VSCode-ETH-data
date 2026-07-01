"""检查 DuckDB 数据库中有哪些表"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "web"))

from api.config import get_duckdb_kline_connection, get_duckdb_structure_connection

print("=== DuckDB K线库表 ===")
conn = get_duckdb_kline_connection(read_only=True)
tables = conn.execute("SHOW TABLES").fetchall()
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]}: {count} 条")
conn.close()

print("\n=== DuckDB 结构库表 ===")
conn2 = get_duckdb_structure_connection(read_only=True)
tables2 = conn2.execute("SHOW TABLES").fetchall()
for t in tables2:
    count = conn2.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f"  {t[0]}: {count} 条")
conn2.close()
"""
创建部署用数据库 - 从2025年起保留数据
用于部署到 Replit / PythonAnywhere
"""
import sqlite3
from pathlib import Path
import datetime

# ── 日期配置 ──
KEEP_FROM = "2025-01-01"  # 从2025年1月1日起保留
KEEP_FROM_MS = int(datetime.datetime.strptime(KEEP_FROM, "%Y-%m-%d").timestamp() * 1000)

# ── 路径 ──
BASE = Path(__file__).resolve().parent.parent
SOURCE_DB = BASE / "bybit_eth_data" / "data" / "processed" / "eth_perpetual.db"
SOURCE_STRUCT_DB = BASE / "bybit_eth_data" / "data" / "processed" / "eth_structure.db"
OUTPUT_DIR = BASE / "deploy_db"
OUTPUT_DB = OUTPUT_DIR / "eth_perpetual.db"
OUTPUT_STRUCT_DB = OUTPUT_DIR / "eth_structure.db"

# 表名
KLINE_TABLES = ["kline_1m", "kline_5m", "kline_15m", "kline_1h", "kline_4h", "kline_1d"]
STRUCT_TABLES = ["kline_1m_std", "kline_5m_std", "kline_15m_std", "kline_1h_std", "kline_4h_std", "kline_1d_std"]


def copy_table(src_conn, dst_cursor, table, time_col, keep_from_ms):
    """从源库复制表结构+数据到目标库，只保留指定时间之后的数据"""
    src_cursor = src_conn.cursor()

    # 检查表是否存在
    src_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
    if not src_cursor.fetchone():
        print(f"  [跳过] 表 {table} 不存在")
        return 0, 0

    # 复制建表语句
    src_cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
    create_sql = src_cursor.fetchone()[0]
    dst_cursor.execute(create_sql)

    # 原总行数
    src_cursor.execute(f"SELECT COUNT(*) FROM {table}")
    total = src_cursor.fetchone()[0]

    # 提取数据
    src_cursor.execute(
        f"SELECT * FROM {table} WHERE {time_col} >= ? ORDER BY {time_col} ASC",
        (keep_from_ms,)
    )
    rows = src_cursor.fetchall()
    if not rows:
        print(f"  [x] {table}: 原 {total:,} 行 → 0 行")
        return total, 0

    # 获取列名
    columns = [desc[0] for desc in src_cursor.description]
    placeholders = ",".join(["?" for _ in columns])
    col_names = ",".join(columns)

    # 批量插入
    BATCH_SIZE = 5000
    dst_cursor.execute("BEGIN TRANSACTION")
    for i, row in enumerate(rows):
        dst_cursor.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", row)
        if (i + 1) % BATCH_SIZE == 0:
            dst_cursor.execute("COMMIT")
            dst_cursor.execute("BEGIN TRANSACTION")
    dst_cursor.execute("COMMIT")

    count = len(rows)
    pct = count / total * 100
    print(f"  [OK] {table}: 原 {total:,} 行 → {count:,} 行 ({pct:.1f}%)")
    return total, count


def main():
    print(f"{'=' * 60}")
    print(f"部署数据库生成工具")
    print(f"从 {KEEP_FROM} 起保留数据")
    print(f"{'=' * 60}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_orig = 0
    total_new = 0

    # ── 处理原始K线库 ──
    print(f"\n[处理] 原始K线库: {SOURCE_DB.name}")
    print(f"  源大小: {SOURCE_DB.stat().st_size / (1024*1024):.1f} MB")

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    src = sqlite3.connect(str(SOURCE_DB))
    dst = sqlite3.connect(str(OUTPUT_DB))
    dst.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;")
    cursor = dst.cursor()

    for table in KLINE_TABLES:
        orig, new = copy_table(src, cursor, table, "open_time", KEEP_FROM_MS)
        total_orig += orig
        total_new += new

    # 创建索引
    print(f"  创建索引...")
    for table in KLINE_TABLES:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(open_time DESC)")
        except:
            pass

    dst.commit()
    dst.close()
    src.close()

    size_mb = OUTPUT_DB.stat().st_size / (1024*1024)
    print(f"\n  原始K线库: {total_orig:,} 行 → {total_new:,} 行")
    print(f"  大小: {size_mb:.1f} MB")

    # ── 处理结构K线库 ──
    total_orig = 0
    total_new = 0

    print(f"\n[处理] 结构K线库: {SOURCE_STRUCT_DB.name}")
    print(f"  源大小: {SOURCE_STRUCT_DB.stat().st_size / (1024*1024):.1f} MB")

    if OUTPUT_STRUCT_DB.exists():
        OUTPUT_STRUCT_DB.unlink()

    src = sqlite3.connect(str(SOURCE_STRUCT_DB))
    dst = sqlite3.connect(str(OUTPUT_STRUCT_DB))
    dst.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;")
    cursor = dst.cursor()

    for table in STRUCT_TABLES:
        orig, new = copy_table(src, cursor, table, "start_time", KEEP_FROM_MS)
        total_orig += orig
        total_new += new

    print(f"  创建索引...")
    for table in STRUCT_TABLES:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(start_time DESC)")
        except:
            pass

    dst.commit()
    dst.close()
    src.close()

    size_mb2 = OUTPUT_STRUCT_DB.stat().st_size / (1024*1024)
    print(f"\n  结构K线库: {total_orig:,} 行 → {total_new:,} 行")
    print(f"  大小: {size_mb2:.1f} MB")

    # ── 汇总 ──
    total_size = (OUTPUT_DB.stat().st_size + OUTPUT_STRUCT_DB.stat().st_size) / (1024*1024)
    print(f"\n{'=' * 60}")
    print(f"[OK] 完成！生成到 {OUTPUT_DIR}/")
    print(f"  {OUTPUT_DB.name}:     {OUTPUT_DB.stat().st_size / (1024*1024):.1f} MB")
    print(f"  {OUTPUT_STRUCT_DB.name}: {OUTPUT_STRUCT_DB.stat().st_size / (1024*1024):.1f} MB")
    print(f"  合计: {total_size:.1f} MB")
    print(f"{'=' * 60}")

    if total_size > 450:
        print(f"\n[注意] 合计 {total_size:.1f} MB 可能偏大，如需缩小可改为更晚的日期。")
    else:
        print(f"\n[OK] 大小适合 Replit 免费部署！")


if __name__ == "__main__":
    main()

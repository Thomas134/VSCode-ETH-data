"""
阶段 1：SQLite → DuckDB 迁移脚本
================================
功能：
1. 将现有的 SQLite 数据库（eth_perpetual.db、eth_structure.db）迁移到 DuckDB
2. 提供 DuckDB 连接工厂（供后续阶段替换 config.py 使用）
3. 验证迁移后数据一致性

用法：
    cd duckdb_migration
    python migrate.py

输出：
    duckdb_data/eth_perpetual.duckdb
    duckdb_data/eth_structure.duckdb
"""

import sqlite3
import sys
from pathlib import Path

# ── 路径配置 ──
MIGRATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MIGRATION_DIR.parent

SOURCE_DB_DIR = PROJECT_ROOT / "bybit_eth_data" / "data" / "processed"
SOURCE_KLINE_DB = SOURCE_DB_DIR / "eth_perpetual.db"
SOURCE_STRUCT_DB = SOURCE_DB_DIR / "eth_structure.db"

OUTPUT_DIR = MIGRATION_DIR / "duckdb_data"
OUTPUT_KLINE_DB = OUTPUT_DIR / "eth_perpetual.duckdb"
OUTPUT_STRUCT_DB = OUTPUT_DIR / "eth_structure.duckdb"

# 表名定义（和原项目保持一致）
KLINE_TABLES = [
    "kline_1m", "kline_5m", "kline_15m",
    "kline_1h", "kline_4h", "kline_1d",
]
STRUCT_TABLES = [
    "kline_1m_std", "kline_5m_std", "kline_15m_std",
    "kline_1h_std", "kline_4h_std", "kline_1d_std",
]


def ensure_duckdb():
    """检查 duckdb 是否已安装"""
    try:
        import duckdb
        return duckdb
    except ImportError:
        print("[错误] 未安装 duckdb，请先执行：pip install duckdb")
        sys.exit(1)


def get_sqlite_tables(conn: sqlite3.Connection) -> list:
    """获取 SQLite 数据库中所有用户表"""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [row[0] for row in cursor.fetchall()]


def get_table_schema(conn: sqlite3.Connection, table_name: str) -> str:
    """获取建表 SQL"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    result = cursor.fetchone()
    return result[0] if result else None


def get_table_count(conn, table_name: str) -> int:
    """获取表行数"""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def migrate_table_fast(source_path: Path, duckdb_conn, table_name: str):
    """
    快速迁移单张表：使用 DuckDB 内置的 sqlite_scan 扩展
    直接让 DuckDB 读取 SQLite 文件，绕过 Python 层逐行搬运
    """
    print(f"  迁移表: {table_name} ...", end=" ")

    # 1. 在 DuckDB 中安装/加载 sqlite 扩展
    duckdb_conn.execute("INSTALL sqlite;")
    duckdb_conn.execute("LOAD sqlite;")

    # 2. 读取 SQLite 建表语句（用于获取列名和主键信息）
    sqlite_conn = sqlite3.connect(str(source_path))
    create_sql = get_table_schema(sqlite_conn, table_name)
    sqlite_conn.close()

    if not create_sql:
        print("[跳过] 表不存在")
        return 0

    # 3. 适配建表语句（和之前一样的替换规则）
    adapted_sql = create_sql \
        .replace("AUTOINCREMENT", "") \
        .replace("DATETIME", "TIMESTAMP") \
        .replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT CURRENT_TIMESTAMP") \
        .replace("INTEGER", "BIGINT")

    # 4. 先创建空表（获取正确的列类型）
    duckdb_conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    duckdb_conn.execute(adapted_sql)

    # 5. 用 sqlite_scan 直接从 SQLite 读取数据并插入
    # 这是核心优化：DuckDB 内部直接解析 SQLite 文件格式，不走 Python 层
    duckdb_conn.execute(f"""
        INSERT INTO {table_name}
        SELECT * FROM sqlite_scan('{source_path}', '{table_name}')
    """)

    # 6. 获取插入行数
    count = duckdb_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    print(f"[OK] {count:,} 行")
    return count


def migrate_database(source_path: Path, output_path: Path, expected_tables: list, db_label: str):
    """迁移单个数据库文件"""
    print(f"\n{'='*60}")
    print(f"迁移数据库: {db_label}")
    print(f"  源: {source_path}")
    print(f"  目标: {output_path}")
    print(f"{'='*60}")

    if not source_path.exists():
        print(f"[错误] 源数据库不存在: {source_path}")
        return False

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 如果目标文件已存在，先删除
    if output_path.exists():
        output_path.unlink()
        print(f"  已删除旧的 DuckDB 文件")

    duckdb = ensure_duckdb()

    # 获取 SQLite 中实际存在的表（快速检查）
    sqlite_conn = sqlite3.connect(str(source_path))
    actual_tables = get_sqlite_tables(sqlite_conn)
    sqlite_conn.close()
    print(f"  源库共有 {len(actual_tables)} 个表: {actual_tables}")

    # 迁移每张表（使用 DuckDB 内置 sqlite_scan，不走 Python 层）
    duckdb_conn = duckdb.connect(str(output_path))

    total_rows = 0
    for table in expected_tables:
        if table in actual_tables:
            rows = migrate_table_fast(source_path, duckdb_conn, table)
            total_rows += rows
        else:
            print(f"  [跳过] {table} 在源库中不存在")

    duckdb_conn.close()

    print(f"\n  迁移完成: {total_rows:,} 行数据")
    print(f"  输出大小: {output_path.stat().st_size / (1024*1024):.1f} MB")
    return True


def verify_migration():
    """验证迁移结果：对比 SQLite 和 DuckDB 的表行数"""
    print(f"\n{'='*60}")
    print("数据一致性验证")
    print(f"{'='*60}")

    duckdb = ensure_duckdb()
    all_pass = True

    # 验证 K 线库
    sqlite_conn = sqlite3.connect(str(SOURCE_KLINE_DB))
    duckdb_conn = duckdb.connect(str(OUTPUT_KLINE_DB))

    for table in KLINE_TABLES:
        sqlite_count = get_table_count(sqlite_conn, table)
        duckdb_count = duckdb_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        status = "OK" if sqlite_count == duckdb_count else "NG"
        if sqlite_count != duckdb_count:
            all_pass = False

        print(f"  [{status}] {table:12}  SQLite: {sqlite_count:>12,}  DuckDB: {duckdb_count:>12,}")

    sqlite_conn.close()
    duckdb_conn.close()

    # 验证结构库
    sqlite_conn = sqlite3.connect(str(SOURCE_STRUCT_DB))
    duckdb_conn = duckdb.connect(str(OUTPUT_STRUCT_DB))

    for table in STRUCT_TABLES:
        sqlite_count = get_table_count(sqlite_conn, table)
        result = duckdb_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        duckdb_count = result[0] if result else 0

        status = "OK" if sqlite_count == duckdb_count else "NG"
        if sqlite_count != duckdb_count:
            all_pass = False

        print(f"  [{status}] {table:12}  SQLite: {sqlite_count:>12,}  DuckDB: {duckdb_count:>12,}")

    sqlite_conn.close()
    duckdb_conn.close()

    print()
    if all_pass:
        print("[OK] 验证通过：所有表行数一致")
    else:
        print("[NG] 验证失败：存在数据不一致")

    return all_pass


def test_duckdb_query():
    """测试 DuckDB 查询性能（和 SQLite 对比）"""
    print(f"\n{'='*60}")
    print("查询性能对比测试")
    print(f"{'='*60}")

    import time
    duckdb = ensure_duckdb()

    test_query = """
        SELECT open_time, open, high, low, close, volume
        FROM kline_1m
        ORDER BY open_time DESC
        LIMIT 300000
    """

    # SQLite 查询
    sqlite_conn = sqlite3.connect(f"file:{SOURCE_KLINE_DB}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row

    t0 = time.perf_counter()
    sqlite_rows = sqlite_conn.execute(test_query).fetchall()
    sqlite_time = time.perf_counter() - t0
    sqlite_conn.close()

    # DuckDB 查询
    duckdb_conn = duckdb.connect(str(OUTPUT_KLINE_DB))

    t0 = time.perf_counter()
    duckdb_rows = duckdb_conn.execute(test_query).fetchall()
    duckdb_time = time.perf_counter() - t0
    duckdb_conn.close()

    print(f"  查询: kline_1m ORDER BY open_time DESC LIMIT 300000")
    print(f"  SQLite: {sqlite_time*1000:>8.2f} ms  ({len(sqlite_rows)} 行)")
    print(f"  DuckDB: {duckdb_time*1000:>8.2f} ms  ({len(duckdb_rows)} 行)")

    if duckdb_time < sqlite_time:
        speedup = sqlite_time / duckdb_time
        print(f"  DuckDB 快 {speedup:.1f}x")
    else:
        slowdown = duckdb_time / sqlite_time
        print(f"  SQLite 快 {slowdown:.1f}x")


def main():
    print("=" * 60)
    print("SQLite → DuckDB 迁移工具（阶段 1）")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"输出目录: {OUTPUT_DIR}")

    # 1. 迁移 K 线数据库
    migrate_database(
        SOURCE_KLINE_DB, OUTPUT_KLINE_DB,
        KLINE_TABLES, "原始K线库 (eth_perpetual)"
    )

    # 2. 迁移结构数据库
    migrate_database(
        SOURCE_STRUCT_DB, OUTPUT_STRUCT_DB,
        STRUCT_TABLES, "结构K线库 (eth_structure)"
    )

    # 3. 验证数据一致性
    verify_migration()

    # 4. 性能对比
    test_duckdb_query()

    print(f"\n{'='*60}")
    print("阶段 1 完成！")
    print(f"DuckDB 文件位置:")
    print(f"  {OUTPUT_KLINE_DB}")
    print(f"  {OUTPUT_STRUCT_DB}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
"""
DuckDB 查询兼容性测试
====================
测试原项目中常用的 SQL 查询在 DuckDB 中是否能正常执行。

用法：
    cd duckdb_migration
    python test_query.py
"""

import sys
from pathlib import Path

# 添加项目根目录到路径，以便导入 db_factory
MIGRATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MIGRATION_DIR.parent))

from duckdb_migration.db_factory import get_duckdb_kline_connection, get_duckdb_structure_connection


def test_kline_query():
    """测试 K 线查询（模拟 kline_api.py 中的查询）"""
    print("\n[测试 1] K线数据查询（带分页）")
    conn = get_duckdb_kline_connection()

    # 查询 1：带 LIMIT 的基本查询
    query1 = """
        SELECT open_time, open, high, low, close, volume
        FROM kline_1m
        WHERE open_time IS NOT NULL
        ORDER BY open_time DESC
        LIMIT 500
    """
    result = conn.execute(query1).fetchall()
    print(f"  ✓ 基本查询: {len(result)} 行")

    # 查询 2：带 before 分页
    query2 = """
        SELECT open_time, open, high, low, close, volume
        FROM kline_1m
        WHERE open_time IS NOT NULL AND open_time < ?
        ORDER BY open_time DESC
        LIMIT ?
    """
    result = conn.execute(query2, (1700000000000, 500)).fetchall()
    print(f"  ✓ 分页查询: {len(result)} 行")

    # 查询 3：时间范围统计
    query3 = """
        SELECT
            COUNT(*) as count,
            MIN(open_time) as first_time,
            MAX(open_time) as last_time
        FROM kline_1m
    """
    row = conn.execute(query3).fetchone()
    print(f"  ✓ 统计查询: count={row[0]:,}, first={row[1]}, last={row[2]}")

    conn.close()


def test_structure_query():
    """测试结构 K 线查询（模拟 structure_api.py 中的查询）"""
    print("\n[测试 2] 结构K线查询")
    conn = get_duckdb_structure_connection()

    # 查询 1：基本结构 K 线
    query1 = """
        SELECT start_time, end_time, open, high, low, close, volume,
               source_count, direction, fractal_label
        FROM kline_5m_std
        WHERE start_time IS NOT NULL
        ORDER BY start_time DESC
        LIMIT 500
    """
    result = conn.execute(query1).fetchall()
    print(f"  ✓ 结构K线查询: {len(result)} 行")

    # 查询 2：只查分型
    query2 = """
        SELECT start_time, end_time, high, low, fractal_label
        FROM kline_5m_std
        WHERE fractal_label != 0
        ORDER BY start_time DESC
        LIMIT 100
    """
    result = conn.execute(query2).fetchall()
    print(f"  ✓ 分型查询: {len(result)} 行")

    # 查询 3：UNION ALL 统计（structure_api.py 中的用法）
    query3 = """
        SELECT '1m' as interval, COUNT(*), MIN(start_time), MAX(start_time) FROM kline_1m_std
        UNION ALL
        SELECT '5m' as interval, COUNT(*), MIN(start_time), MAX(start_time) FROM kline_5m_std
        UNION ALL
        SELECT '1h' as interval, COUNT(*), MIN(start_time), MAX(start_time) FROM kline_1h_std
    """
    result = conn.execute(query3).fetchall()
    print(f"  ✓ UNION ALL 统计: {len(result)} 条记录")
    for row in result:
        print(f"      {row[0]}: {row[1]:,} 行")

    conn.close()


def test_backtest_query():
    """测试回测数据加载查询（模拟 backtest_api.py）"""
    print("\n[测试 3] 回测数据加载查询")
    conn = get_duckdb_kline_connection()

    # 模拟回测加载大量数据
    query = """
        SELECT open_time, open, high, low, close, volume
        FROM kline_1m
        WHERE open_time >= ? AND open_time < ?
        ORDER BY open_time ASC
    """
    # 加载 2024-01-01 到 2024-02-01 的数据
    start_ms = 1704067200000
    end_ms = 1706745600000

    result = conn.execute(query, (start_ms, end_ms)).fetchall()
    print(f"  ✓ 回测数据加载: {len(result):,} 行 (2024-01)")

    conn.close()


def test_fetchdf():
    """测试 DuckDB 的 DataFrame 输出（后续阶段可能用到）"""
    print("\n[测试 4] DataFrame 输出")
    conn = get_duckdb_kline_connection()

    query = """
        SELECT open_time, open, high, low, close, volume
        FROM kline_1m
        LIMIT 100
    """
    df = conn.execute(query).fetchdf()
    print(f"  ✓ fetchdf: {len(df)} 行, 列: {list(df.columns)}")

    conn.close()


def main():
    print("=" * 60)
    print("DuckDB 查询兼容性测试")
    print("=" * 60)

    try:
        test_kline_query()
        test_structure_query()
        test_backtest_query()
        test_fetchdf()

        print("\n" + "=" * 60)
        print("[✓] 所有测试通过！DuckDB 可以兼容现有查询。")
        print("=" * 60)

    except Exception as e:
        print(f"\n[✗] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
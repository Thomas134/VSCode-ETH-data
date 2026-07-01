# create_indexes.py
# 为K线数据表创建索引，优化查询性能
# 运行一次即可，索引会持久保存在数据库中

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 数据库路径 ──
BASE_DIR = Path(__file__).resolve().parents[1]  # 项目根目录
DB_PATH = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_perpetual.db"
STRUCTURE_DB = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_structure.db"

# 原始K线表
KLINE_TABLES = ["kline_1m", "kline_5m", "kline_15m", "kline_1h", "kline_4h", "kline_1d"]
# 结构K线表
STD_TABLES = ["kline_1m_std", "kline_5m_std", "kline_15m_std", "kline_1h_std", "kline_4h_std", "kline_1d_std"]


def create_indexes_for_db(conn, tables, time_column, is_structure=False):
    cursor = conn.cursor()
    for table in tables:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cursor.fetchone():
            logger.info("  [SKIP] 表 %s 不存在，跳过", table)
            continue
        try:
            if is_structure:
                cursor.execute(f"DROP INDEX IF EXISTS idx_{table}_start_time")
                cursor.execute(f"DROP INDEX IF EXISTS idx_{table}_start_label")
                new_index = f"idx_{table}_start_label"
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {new_index} ON {table}(start_time DESC, fractal_label)")
                logger.info("  [OK] %s: 新索引 %s (start_time DESC, fractal_label)", table, new_index)
            else:
                cursor.execute(f"DROP INDEX IF EXISTS idx_{table}_symbol_time")
                cursor.execute(f"DROP INDEX IF EXISTS idx_{table}_symbol_interval")
                new_index = f"idx_{table}_{time_column}"
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {new_index} ON {table}({time_column} DESC)")
                logger.info("  [OK] %s: 新索引 %s (%s DESC)", table, new_index, time_column)
        except Exception as e:
            logger.error("  [FAIL] %s 处理失败: %s", table, e)
    conn.commit()


def main():
    logger.info("=== 重建SQLite索引（优化查询性能） ===\n")
    
    # ── 处理原始K线数据库 ──
    logger.info("【原始K线库】%s", DB_PATH)
    conn1 = sqlite3.connect(str(DB_PATH))
    create_indexes_for_db(conn1, KLINE_TABLES, "open_time", is_structure=False)
    conn1.close()
    
    # ── 处理结构数据库 ──
    logger.info("【结构K线库】%s", STRUCTURE_DB)
    conn2 = sqlite3.connect(str(STRUCTURE_DB))
    create_indexes_for_db(conn2, STD_TABLES, "start_time", is_structure=True)
    conn2.close()
    
    logger.info("所有索引创建完成!")


if __name__ == "__main__":
    main()
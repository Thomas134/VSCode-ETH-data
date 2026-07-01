# check_db_status.py - 查看数据库数据状态（时间范围 + 记录数）
import sqlite3
from pathlib import Path
import sys

current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from bybit_config import DB_PATH, TIME_INTERVALS, PROCESSED_DIR

STRUCTURE_DB = PROCESSED_DIR / "eth_structure.db"

INTERVAL_NAMES = {
    "1m": "1分钟K线",
    "5m": "5分钟K线",
    "15m": "15分钟K线",
    "1h": "1小时K线",
    "4h": "4小时K线",
    "1d": "日线K线",
}


def fmt_ts(ms):
    if ms is None:
        return "无数据"
    from datetime import datetime
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def check_db(db_path, label, table_suffix="", time_col="open_time"):
    if not Path(db_path).exists():
        print(f"  ✗ 数据库不存在: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  路径: {db_path}")
    print(f"{'='*60}")

    # 先列出所有表
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    table_names = [t['name'] for t in tables]
    print(f"  现有表: {table_names if table_names else '（空数据库，无任何表）'}")
    print()

    if not table_names:
        conn.close()
        return

    print(f"  {'时间级别':<12} {'最早时间':<22} {'最晚时间':<22} {'记录数':>10}")
    print(f"  {'-'*12} {'-'*22} {'-'*22} {'-'*10}")

    for key, cfg in TIME_INTERVALS.items():
        table_name = cfg["table_name"] + table_suffix
        if table_name not in table_names:
            print(f"  {INTERVAL_NAMES.get(key, key):<12} {'表不存在':<22} {'':<22} {'':>10}")
            continue
        try:
            row = conn.execute(
                f"SELECT MIN({time_col}) as earliest, MAX({time_col}) as latest, COUNT(*) as cnt FROM {table_name}"
            ).fetchone()
            print(f"  {INTERVAL_NAMES.get(key, key):<12} {fmt_ts(row['earliest']):<22} {fmt_ts(row['latest']):<22} {row['cnt']:>10,}")
        except Exception as e:
            print(f"  {INTERVAL_NAMES.get(key, key):<12} 查询失败: {e}")

    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  数据库状态检查")
    print("=" * 60)

    check_db(DB_PATH, "原始K线数据库 (eth_perpetual.db)")
    check_db(STRUCTURE_DB, "结构K线数据库 (eth_structure.db)", table_suffix="_std", time_col="start_time")

    print(f"\n{'='*60}")
    print("  检查完毕")
    print(f"{'='*60}")
# fetch_range.py - 一键并发拉取全部时间级别数据，速度最大化
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
import pandas as pd

current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from bybit_client import BybitClient
from database_manager import init_database, insert_or_update_kline_data
from bybit_config import SYMBOL, TIME_INTERVALS
from structure_engine import update_all_structures

# ========== 改这里 ==========
START_DATE = "2024-01-01"
END_DATE = "2026-07-01"
# ============================

# Bybit 公开接口限速: 50 req/s/IP
# 激进用 48 req/s，留 2 req/s 余量
TARGET_RPS = 48
MIN_INTERVAL = 1.0 / TARGET_RPS  # 约 0.021s
BATCH_INSERT_EVERY = 5  # 每5批(1000条)写入一次DB，减少连接开销

_rate_lock = threading.Lock()
_last_request = 0.0
_total_requests = 0
_start_time = None


def rate_limit():
    """全局速率限制：确保所有线程合计不超过 TARGET_RPS"""
    global _last_request, _total_requests, _start_time
    with _rate_lock:
        now = time.time()
        elapsed = now - _last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_request = time.time()
        _total_requests += 1
        if _start_time is None:
            _start_time = _last_request


def convert_to_dataframe(kline_data, interval_key):
    """将K线数据转换为DataFrame"""
    if not kline_data:
        return pd.DataFrame()
    columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'turnover']
    df = pd.DataFrame(kline_data, columns=columns)
    numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'turnover']
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['open_time'] = pd.to_numeric(df['open_time'], errors='coerce')
    df['symbol'] = SYMBOL
    df['interval'] = TIME_INTERVALS[interval_key]["interval"]
    df['trade_count'] = 0
    df['taker_buy_volume'] = 0
    return df


def fetch_one_interval(interval_key, start_ts, end_ts, results):
    """单个时间级别的数据拉取（线程安全，批量累积写入）"""
    client = BybitClient()
    interval_config = TIME_INTERVALS[interval_key]
    interval_ms = {
        "1m": 60000, "5m": 300000, "15m": 900000,
        "1h": 3600000, "4h": 14400000, "1d": 86400000
    }[interval_key]

    current_ts = start_ts
    batch_count = 0
    total_inserted = 0
    accumulated_dfs = []  # 累积多个批次再写入

    while current_ts < end_ts:
        batch_count += 1
        try:
            rate_limit()  # 全局速率限制

            kline_data = client.get_klines(
                symbol=SYMBOL,
                interval=interval_config["interval"],
                start_time=current_ts,
                limit=200
            )

            if not kline_data:
                break

            df = convert_to_dataframe(kline_data, interval_key)
            if df.empty:
                break

            accumulated_dfs.append(df)
            last_timestamp = df['open_time'].max()
            current_ts = last_timestamp + interval_ms

            # 每 N 批累积写入一次，减少 DB 连接开销
            if batch_count % BATCH_INSERT_EVERY == 0:
                merged = pd.concat(accumulated_dfs, ignore_index=True)
                inserted_count, _ = insert_or_update_kline_data(merged, interval_key)
                total_inserted += inserted_count
                accumulated_dfs = []

            if batch_count % 50 == 0:
                latest_time = pd.Timestamp(last_timestamp, unit='ms')
                print(f"  [{interval_key}] 批次 {batch_count}: "
                      f"已新增 {total_inserted} 条, 最新: {latest_time}")

        except Exception as e:
            print(f"  [{interval_key}] 批次 {batch_count} 出错: {e}")
            time.sleep(0.5)
            continue

    # 写入剩余累积数据
    if accumulated_dfs:
        merged = pd.concat(accumulated_dfs, ignore_index=True)
        inserted_count, _ = insert_or_update_kline_data(merged, interval_key)
        total_inserted += inserted_count

    results[interval_key] = total_inserted
    print(f"  [{interval_key}] 完成! 共 {batch_count} 批, 新增 {total_inserted} 条")


def main():
    global _start_time
    print("=" * 60)
    print("  ETH 永续合约多时间级别并发数据拉取")
    print(f"  日期范围: {START_DATE} → {END_DATE}")
    print(f"  速率限制: {TARGET_RPS} req/s (Bybit 公开接口上限 50 req/s)")
    print("=" * 60)

    init_database()

    start_ts = int(pd.Timestamp(START_DATE).timestamp() * 1000)
    end_ts = int(pd.Timestamp(END_DATE).timestamp() * 1000)

    intervals = list(TIME_INTERVALS.keys())
    print(f"\n启动 {len(intervals)} 个并发线程: {intervals}")

    results = {}
    threads = []
    t0 = time.time()

    for ik in intervals:
        t = threading.Thread(target=fetch_one_interval, args=(ik, start_ts, end_ts, results))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - t0
    actual_rps = _total_requests / elapsed if elapsed > 0 else 0

    print("\n" + "=" * 60)
    print("  数据拉取完成!")
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  总请求数: {_total_requests}")
    print(f"  实际速率: {actual_rps:.1f} req/s")
    print("-" * 60)
    for ik, count in results.items():
        print(f"  {TIME_INTERVALS[ik]['description']}: {count} 条")
    print("=" * 60)

    # 更新结构K线
    print("\n更新结构K线...")
    struct_results = update_all_structures()
    if struct_results:
        for interval, count in struct_results.items():
            print(f"  {interval}: 处理 {count} 条新K线")
    else:
        print("  结构K线已是最新")
    print("\n全部完成!")


if __name__ == "__main__":
    main()
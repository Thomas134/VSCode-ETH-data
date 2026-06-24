# fetch_historical.py
import pandas as pd
import time
from datetime import datetime, timedelta
import sys
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from bybit_client import get_bybit_client
from database_manager import insert_or_update_kline_data, init_database, get_db_connection, get_table_stats
from config import SYMBOL, TIME_INTERVALS, init_directories, print_config_info
from structure_engine import update_all_structures, get_structure_stats

def convert_to_dataframe(kline_data, interval_key):
    """将K线数据转换为DataFrame"""
    if not kline_data:
        return pd.DataFrame()
    
    # Bybit V5 API返回的数据格式（列表格式）
    # [时间戳, 开盘价, 最高价, 最低价, 收盘价, 成交量, 成交额]
    columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'turnover']
    
    # 创建DataFrame
    df = pd.DataFrame(kline_data, columns=columns)
    
    # 转换数据类型
    numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'turnover']
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['open_time'] = pd.to_numeric(df['open_time'], errors='coerce')
    
    # 添加元数据
    df['symbol'] = SYMBOL
    df['interval'] = TIME_INTERVALS[interval_key]["interval"]
    
    # 计算交易笔数（如果API不提供，可以设为0或估算）
    df['trade_count'] = 0
    df['taker_buy_volume'] = 0
    
    return df

def fetch_historical_data(start_date, end_date=None, interval_key="1m"):
    """
    获取指定时间范围和历史数据
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        interval_key: 时间级别key
    """
    if interval_key not in TIME_INTERVALS:
        print(f"✗ 不支持的时间级别: {interval_key}")
        return 0
    
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    client = get_bybit_client()
    interval_config = TIME_INTERVALS[interval_key]
    
    # 转换为时间戳（毫秒）
    start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
    
    print(f"开始获取{interval_config['description']}数据: {start_date} 到 {end_date}")
    
    current_ts = start_ts
    total_inserted = 0
    batch_count = 0
    
    while current_ts < end_ts:
        batch_count += 1
        try:
            current_time = pd.Timestamp(current_ts, unit='ms')
            print(f"  批次 {batch_count}: 获取从 {current_time} 开始的数据...")
            
            # 获取K线数据
            kline_data = client.get_klines(
                symbol=SYMBOL,
                interval=interval_config["interval"],
                start_time=current_ts,
                limit=200
            )
            
            if not kline_data:
                print("    没有获取到数据，可能已到达数据末尾")
                break
            
            # 转换为DataFrame
            df = convert_to_dataframe(kline_data, interval_key)
            
            if df.empty:
                print("    转换后的数据为空，结束循环")
                break
            
            # 保存到数据库
            inserted_count, updated_count = insert_or_update_kline_data(df, interval_key)
            total_inserted += inserted_count
            
            # 显示进度
            if not df.empty:
                latest_time = pd.Timestamp(df['open_time'].max(), unit='ms')
                print(f"    ✓ 批次 {batch_count}: 新增 {inserted_count} 条, 最新时间: {latest_time}, 总计新增: {total_inserted}")
            
            # 更新当前时间戳
            if not df.empty:
                last_timestamp = df['open_time'].max()
                # 根据时间间隔确定增量
                if interval_key == "1m":
                    current_ts = last_timestamp + 60000  # 1分钟
                elif interval_key == "5m":
                    current_ts = last_timestamp + 300000  # 5分钟
                elif interval_key == "15m":
                    current_ts = last_timestamp + 900000  # 15分钟
                elif interval_key == "1h":
                    current_ts = last_timestamp + 3600000  # 1小时
                elif interval_key == "4h":
                    current_ts = last_timestamp + 14400000  # 4小时
                elif interval_key == "1d":
                    current_ts = last_timestamp + 86400000  # 1天
                else:
                    current_ts = last_timestamp + 60000  # 默认1分钟
            else:
                print("    数据为空，结束循环")
                break
            
            # 避免频繁请求，遵守API限制
            time.sleep(0.3)
            
        except Exception as e:
            print(f"    获取数据时出错: {e}")
            time.sleep(1)
            continue
    
    print(f"🎉 {interval_config['description']}数据获取完成！总共新增 {total_inserted} 条记录")
    return total_inserted

def fetch_incremental_data(interval_key="1m", days=1):
    """
    获取增量数据（从数据库中最新时间开始）
    """
    # 初始化数据库
    init_database()
    
    if interval_key not in TIME_INTERVALS:
        print(f"✗ 不支持的时间级别: {interval_key}")
        return 0
    
    table_name = TIME_INTERVALS[interval_key]["table_name"]
    
    # 获取数据库中最新数据的时间
    conn = get_db_connection()
    try:
        latest_time_query = f"""
        SELECT MAX(open_time) as latest_time 
        FROM {table_name} 
        WHERE symbol = ?
        """
        result = pd.read_sql(latest_time_query, conn, params=[SYMBOL])
        latest_ts = result.iloc[0]['latest_time']
        
        if latest_ts:
            start_date = pd.Timestamp(latest_ts, unit='ms').strftime("%Y-%m-%d")
            print(f"数据库中最新的{interval_key}数据时间: {pd.Timestamp(latest_ts, unit='ms')}")
        else:
            # 如果没有数据，从几天前开始
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            print(f"数据库为空，从 {start_date} 开始获取{interval_key}数据")
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        return fetch_historical_data(start_date, end_date, interval_key)
        
    finally:
        conn.close()

def fetch_all_intervals(days=7):
    """获取所有时间级别的数据"""
    print("=== 开始获取所有时间级别数据 ===")
    
    client = get_bybit_client()
    if not client.test_connection():
        print("✗ API连接失败")
        return
    
    # 初始化数据库
    init_database()
    
    total_results = {}
    
    for interval_key in TIME_INTERVALS.keys():
        print(f"\n{'='*50}")
        print(f"处理 {TIME_INTERVALS[interval_key]['description']} 数据...")
        print(f"{'='*50}")
        
        try:
            result = fetch_incremental_data(interval_key, days)
            total_results[interval_key] = result
            # 不同时间级别之间等待一下，避免API限制
            time.sleep(1)
        except Exception as e:
            print(f"获取{interval_key}数据时出错: {e}")
            total_results[interval_key] = 0
    
    print(f"\n{'='*50}")
    print("所有时间级别数据获取完成！")
    print(f"{'='*50}")
    
    for interval_key, count in total_results.items():
        status = "✓ 成功" if count > 0 else "✗ 失败"
        print(f"{TIME_INTERVALS[interval_key]['description']}: {status} ({count} 条)")

if __name__ == "__main__":
    print("=== ETH永续合约多时间级别数据获取程序 ===")
    
    # 显示当前数据状态
    print("\n=== 当前数据状态 ===")
    stats = get_table_stats()
    for interval_key, stat in stats.items():
        if stat["exists"]:
            status = f"{stat['count']} 条记录"
            if stat['count'] > 0:
                status += f" ({stat['time_range']})"
            print(f"{stat['description']}: {status}")
    
    client = get_bybit_client()
    if client.test_connection():
        # 自动执行：获取所有时间级别数据（增量更新）
        print("\n开始自动更新所有时间级别数据...")
        fetch_all_intervals(days=7)
        
        # 更新结构K线（增量）
        print("\n=== 更新结构K线 ===")
        struct_results = update_all_structures()
        if struct_results:
            for interval, count in struct_results.items():
                print(f"  {interval}: 处理 {count} 条新K线")
        else:
            print("  结构K线已是最新")
        
        # 显示更新后的数据状态
        print("\n=== 更新后数据状态 ===")
        stats = get_table_stats()
        for interval_key, stat in stats.items():
            if stat["exists"]:
                status = f"{stat['count']} 条记录"
                if stat['count'] > 0:
                    status += f" ({stat['time_range']})"
                print(f"{stat['description']}: {status}")
        
        # 显示结构数据库状态
        print("\n=== 结构K线状态 ===")
        struct_stats = get_structure_stats()
        for interval, data in struct_stats.items():
            if data['count'] > 0:
                print(f"  {interval}: {data['count']} 条标准K线")
    else:
        print("请检查API配置和网络连接")
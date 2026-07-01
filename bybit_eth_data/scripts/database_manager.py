# database_manager.py
import sqlite3
import threading
import pandas as pd
from bybit_config import DB_PATH, TIME_INTERVALS, SYMBOL, init_directories

# 线程级持久连接：避免每批数据都开关连接
_tl = threading.local()

def ensure_db_directory():
    """确保数据库文件所在的目录存在"""
    db_parent = DB_PATH.parent
    if not db_parent.exists():
        print(f"创建数据库目录: {db_parent}")
        db_parent.mkdir(parents=True, exist_ok=True)

def get_db_connection():
    """创建并返回一个数据库连接（写入优化）"""
    ensure_db_directory()
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-20000")  # 80MB 缓存
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except Exception as e:
        print(f"连接数据库失败: {e}")
        raise

def get_thread_connection():
    """获取当前线程的持久数据库连接（复用，避免重复开关）"""
    if not hasattr(_tl, 'conn') or _tl.conn is None:
        _tl.conn = get_db_connection()
    return _tl.conn

def init_database():
    """初始化数据库，创建所有时间级别的K线数据表"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 为每个时间级别创建表
        for interval_key, interval_config in TIME_INTERVALS.items():
            table_name = interval_config["table_name"]
            description = interval_config["description"]
            
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                trade_count INTEGER DEFAULT 0,
                taker_buy_volume REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                -- 唯一约束，防止重复数据
                UNIQUE(symbol, interval, open_time)
            );
            
            -- 创建索引以提高查询性能
            CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol_interval ON {table_name} (symbol, interval);
            CREATE INDEX IF NOT EXISTS idx_{table_name}_open_time ON {table_name} (open_time);
            """
            
            cursor.executescript(create_table_sql)
            print(f"✓ {description}表初始化成功: {table_name}")
        
        conn.commit()
        print("✓ 所有数据表初始化完成！")
        
        # 验证所有表是否创建成功
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kline_%';")
        tables = cursor.fetchall()
        print(f"✓ 数据库中存在 {len(tables)} 个K线数据表")
        for table in tables:
            print(f"  - {table[0]}")
            
    except Exception as e:
        print(f"✗ 初始化数据库时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

def insert_or_update_kline_data(df, interval_key):
    """
    插入或更新指定时间级别的K线数据（批量优化版）
    
    Args:
        df: 包含K线数据的DataFrame
        interval_key: 时间级别key，如 "1m", "5m" 等
    Returns:
        inserted_count: 新插入的记录数
        updated_count: 更新的记录数
    """
    if interval_key not in TIME_INTERVALS:
        print(f"✗ 未知的时间级别: {interval_key}")
        return 0, 0
    
    if df.empty:
        return 0, 0
    
    table_name = TIME_INTERVALS[interval_key]["table_name"]
    conn = get_thread_connection()
    
    try:
        cursor = conn.cursor()
        
        # 构建批量数据列表
        rows = [
            (
                str(row['symbol']), str(row['interval']), int(row['open_time']),
                float(row['open']), float(row['high']), float(row['low']),
                float(row['close']), float(row['volume']),
                int(row.get('trade_count', 0)), float(row.get('taker_buy_volume', 0))
            )
            for _, row in df.iterrows()
        ]
        
        insert_sql = f"""
        INSERT OR IGNORE INTO {table_name} 
        (symbol, interval, open_time, open, high, low, close, volume, trade_count, taker_buy_volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.executemany(insert_sql, rows)
        inserted_count = cursor.rowcount
        
        conn.commit()
        
        skipped = len(rows) - inserted_count
        if skipped > 0:
            print(f"  [{interval_key}] 批量写入: 新增 {inserted_count} 条, 跳过 {skipped} 条重复")
        
    except Exception as e:
        print(f"批量插入数据时出错: {e}")
        conn.rollback()
        inserted_count = 0
        skipped = 0
    
    return inserted_count, 0

def get_table_stats():
    """获取所有数据表的统计信息"""
    conn = get_db_connection()
    try:
        stats = {}
        cursor = conn.cursor()
        
        for interval_key, interval_config in TIME_INTERVALS.items():
            table_name = interval_config["table_name"]
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                stats[interval_key] = {"exists": False, "count": 0}
                continue
            
            # 获取记录数
            count_query = f"SELECT COUNT(*) FROM {table_name} WHERE symbol = ?"
            cursor.execute(count_query, (SYMBOL,))
            count = cursor.fetchone()[0]
            
            # 获取时间范围
            time_query = f"""
            SELECT 
                MIN(open_time) as first_time,
                MAX(open_time) as last_time
            FROM {table_name} 
            WHERE symbol = ?
            """
            cursor.execute(time_query, (SYMBOL,))
            result = cursor.fetchone()
            
            if result and result[0]:
                first_dt = pd.to_datetime(result[0], unit='ms')
                last_dt = pd.to_datetime(result[1], unit='ms')
                time_range = f"{first_dt} 到 {last_dt}"
            else:
                time_range = "无数据"
            
            stats[interval_key] = {
                "exists": True,
                "count": count,
                "time_range": time_range,
                "description": interval_config["description"]
            }
        
        return stats
        
    except Exception as e:
        print(f"获取表统计时出错: {e}")
        return {}
    finally:
        conn.close()

def migrate_old_data():
    """将旧数据从kline_data表迁移到新的分表"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 检查旧表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kline_data'")
        if not cursor.fetchone():
            print("✓ 没有发现旧数据表，无需迁移")
            return
        
        # 获取旧表数据
        cursor.execute("SELECT COUNT(*) FROM kline_data")
        old_count = cursor.fetchone()[0]
        
        if old_count == 0:
            print("✓ 旧表为空，无需迁移")
            return
        
        print(f"发现旧表数据 {old_count} 条，开始迁移...")
        
        # 假设旧表都是1分钟数据
        if "1m" in TIME_INTERVALS:
            table_name = TIME_INTERVALS["1m"]["table_name"]
            
            # 迁移数据
            migrate_sql = f"""
            INSERT OR IGNORE INTO {table_name} 
            (symbol, interval, open_time, open, high, low, close, volume, trade_count, taker_buy_volume)
            SELECT symbol, interval, open_time, open, high, low, close, volume, trade_count, taker_buy_volume
            FROM kline_data
            """
            cursor.execute(migrate_sql)
            migrated_count = cursor.rowcount
            
            conn.commit()
            print(f"✓ 成功迁移 {migrated_count} 条数据到 {table_name} 表")
            
            # 可选：删除旧表
            # cursor.execute("DROP TABLE kline_data")
            # print("✓ 旧表已删除")
        else:
            print("✗ 无法迁移：1m时间级别未配置")
            
    except Exception as e:
        print(f"迁移数据时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    init_directories()
    print("开始初始化数据库...")
    init_database()
    
    print("\n开始迁移旧数据...")
    migrate_old_data()
    
    print("\n=== 数据库统计 ===")
    stats = get_table_stats()
    for interval_key, stat in stats.items():
        if stat["exists"]:
            print(f"{stat['description']}: {stat['count']} 条记录")
            if stat['count'] > 0:
                print(f"  时间范围: {stat['time_range']}")
        else:
            print(f"{TIME_INTERVALS[interval_key]['description']}: 表不存在")
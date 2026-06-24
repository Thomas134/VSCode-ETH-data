# structure_engine.py
# 标准化K线处理引擎 - DB读写 + 编排调度
#
# 核心算法（包含关系处理、顶底分型识别）已抽离到 structure_analyzer.py
# 本模块只负责: DB连接、数据读取/写入、全量/增量编排、统计查询

import sqlite3
from pathlib import Path
from datetime import datetime
from config import DATA_DIR, TIME_INTERVALS
from structure_analyzer import (
    is_containing,
    merge_klines,
    get_direction,
    process_containing_relationship,
    identify_fractals,
)

# 数据库路径
SOURCE_DB = DATA_DIR / "processed" / "eth_perpetual.db"
STRUCTURE_DB = DATA_DIR / "processed" / "eth_structure.db"

# 时间级别与表名映射
INTERVAL_TABLE_MAP = {
    "1m": ("kline_1m", "kline_1m_std"),
    "5m": ("kline_5m", "kline_5m_std"),
    "15m": ("kline_15m", "kline_15m_std"),
    "1h": ("kline_1h", "kline_1h_std"),
    "4h": ("kline_4h", "kline_4h_std"),
    "1d": ("kline_1d", "kline_1d_std"),
}

# 时间级别对应的毫秒数
INTERVAL_MS = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def init_structure_db():
    """初始化结构数据库"""
    conn = sqlite3.connect(STRUCTURE_DB)
    cursor = conn.cursor()
    
    # 为每个时间级别创建标准化K线表
    for interval, (_, std_table) in INTERVAL_TABLE_MAP.items():
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {std_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            source_count INTEGER DEFAULT 1,
            direction INTEGER DEFAULT 0,
            fractal_label INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, start_time)
        )
        """)
        
        # 兼容旧表：若 fractal_label 列不存在则添加
        try:
            cursor.execute(f"ALTER TABLE {std_table} ADD COLUMN fractal_label INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略错误
        
        # 创建索引
        cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{std_table}_symbol_time 
        ON {std_table}(symbol, start_time)
        """)
    
    conn.commit()
    conn.close()
    print(f"✓ 结构数据库初始化完成: {STRUCTURE_DB}")


def get_source_connection():
    """获取源数据库连接 (只读)"""
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_structure_connection():
    """获取结构数据库连接"""
    conn = sqlite3.connect(STRUCTURE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _save_5m_kline_log(std_klines, fractal_labels, top_count, bottom_count, mode='全量'):
    """保存5m结构化K线日志到文件（全量/增量均调用）"""
    log_path = Path(__file__).resolve().parent / "structure_kline_log.txt"
    fractal_char = {1: ' ▲顶', -1: ' ▼底', 0: ''}
    
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"=== 5m 结构化K线 [{mode}] {datetime.now().strftime('%m-%d %H:%M:%S')} ===\n")
        for idx, k in enumerate(std_klines):
            dt_start = datetime.fromtimestamp(k['start_time'] / 1000).strftime('%Y-%m-%d %H:%M')
            dt_end = datetime.fromtimestamp(k['end_time'] / 1000).strftime('%H:%M')
            label = fractal_labels[idx]
            fractal_str = fractal_char.get(label, '')
            line = f"[{idx}] {dt_start}~{dt_end}  H:{k['high']:.2f}  L:{k['low']:.2f}  src:{k['source_count']}{fractal_str}"
            f.write(line + "\n")

        # 分型汇总
        f.write(f"\n--- 分型汇总 ---\n")
        f.write(f"顶分型: {top_count}个\n")
        f.write(f"底分型: {bottom_count}个\n")
        for idx, label in enumerate(fractal_labels):
            if label != 0:
                k = std_klines[idx]
                dt = datetime.fromtimestamp(k['start_time'] / 1000).strftime('%Y-%m-%d %H:%M')
                label_name = "顶分型" if label == 1 else "底分型"
                f.write(f"  [{idx}] {dt}  {label_name}  H:{k['high']:.2f}  L:{k['low']:.2f}\n")

    print(f"  已保存 {len(std_klines)} 条5m结构化K线到 structure_kline_log.txt")


def process_interval(interval, symbol='ETHUSDT'):
    """
    处理指定时间级别的K线数据
    """
    if interval not in INTERVAL_TABLE_MAP:
        print(f"✗ 不支持的时间级别: {interval}")
        return 0
    
    source_table, std_table = INTERVAL_TABLE_MAP[interval]
    
    print(f"\n处理 {interval} K线数据...")
    
    # 读取源数据
    source_conn = get_source_connection()
    cursor = source_conn.cursor()
    
    # 获取时间级别对应的毫秒数
    interval_ms = INTERVAL_MS[interval]
    
    cursor.execute(f"""
    SELECT open_time, open, high, low, close, volume
    FROM {source_table}
    WHERE open_time IS NOT NULL
    ORDER BY open_time ASC
    """)
    
    rows = cursor.fetchall()
    source_conn.close()
    
    if not rows:
        print(f"  暂无数据")
        return 0
    
    print(f"  原始K线: {len(rows)} 条")
    
    # 转换为字典列表，计算正确的 end_time
    klines = []
    for row in rows:
        start_time = row['open_time']
        klines.append({
            'start_time': start_time,
            'end_time': start_time + interval_ms,  # end_time = start_time + 周期时长
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'volume': row['volume'],
        })
    
    # 处理包含关系
    std_klines = process_containing_relationship(klines)
    print(f"  标准化K线: {len(std_klines)} 条 (合并 {len(klines) - len(std_klines)} 条)")

    # 识别顶底分型
    fractal_labels = identify_fractals(std_klines)
    top_count = sum(1 for x in fractal_labels if x == 1)
    bottom_count = sum(1 for x in fractal_labels if x == -1)
    print(f"  顶底分型: 顶{top_count}个 / 底{bottom_count}个 / 共{top_count + bottom_count}个")

    # 写入结构数据库
    struct_conn = get_structure_connection()
    cursor = struct_conn.cursor()
    
    # 清空旧数据
    cursor.execute(f"DELETE FROM {std_table}")
    
    # 保存5m结构化K线日志
    if interval == '5m':
        _save_5m_kline_log(std_klines, fractal_labels, top_count, bottom_count, mode='全量')
    
    # 插入新数据（含分型标记）
    rows_batch = []
    for i, k in enumerate(std_klines):
        rows_batch.append((
            symbol,
            k['start_time'],
            k['end_time'],
            k['open'],
            k['high'],
            k['low'],
            k['close'],
            k['volume'],
            k['source_count'],
            k['direction'],
            fractal_labels[i],
        ))

    cursor.executemany(f"""
        INSERT INTO {std_table} 
    (symbol, start_time, end_time, open, high, low, close, volume, source_count, direction, fractal_label)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_batch)
    
    struct_conn.commit()
    struct_conn.close()
    
    print(f"  ✓ 已写入 {len(std_klines)} 条标准化K线")
    return len(std_klines)


def process_all_intervals(symbol='ETHUSDT'):
    """处理所有时间级别"""
    print("=== 开始处理所有时间级别K线包含关系 ===")
    
    # 初始化数据库
    init_structure_db()
    
    results = {}
    for interval in INTERVAL_TABLE_MAP.keys():
        count = process_interval(interval, symbol)
        results[interval] = count
    
    print("\n=== 处理完成 ===")
    for interval, count in results.items():
        print(f"  {interval}: {count} 条标准化K线")
    
    return results


def update_structure_incremental(interval, symbol='ETHUSDT'):
    """
    增量更新结构K线
    只处理新增的原始K线数据
    """
    if interval not in INTERVAL_TABLE_MAP:
        return 0
    
    source_table, std_table = INTERVAL_TABLE_MAP[interval]
    
    # 初始化数据库(如果不存在)
    init_structure_db()
    
    # 获取结构数据库最后一根K线的结束时间
    struct_conn = get_structure_connection()
    cursor = struct_conn.cursor()
    
    cursor.execute(f"""
    SELECT end_time, direction FROM {std_table}
    ORDER BY end_time DESC
    LIMIT 1
    """)
    last_row = cursor.fetchone()
    
    if last_row:
        last_end_time = last_row['end_time']
        last_direction = last_row['direction']
    else:
        last_end_time = 0
        last_direction = 0
    
    struct_conn.close()
    
    # 查询新增的原始K线
    source_conn = get_source_connection()
    cursor = source_conn.cursor()
    
    cursor.execute(f"""
    SELECT open_time as start_time, open_time as end_time,
           open, high, low, close, volume
    FROM {source_table}
    WHERE open_time IS NOT NULL AND open_time > ?
    ORDER BY open_time ASC
    """, (last_end_time,))
    
    new_rows = cursor.fetchall()
    source_conn.close()
    
    if not new_rows:
        return 0
    
    # 获取最后两根已确认的标准K线(用于确定方向)
    struct_conn = get_structure_connection()
    cursor = struct_conn.cursor()
    
    cursor.execute(f"""
    SELECT start_time, end_time, open, high, low, close, volume, source_count, direction
    FROM {std_table}
    ORDER BY end_time DESC
    LIMIT 2
    """)
    last_std_rows = cursor.fetchall()
    struct_conn.close()
    
    # 准备处理: 从最后一根标准K线开始(可能需要重新合并)
    klines_to_process = []
    
    if last_std_rows:
        # 删除最后一根标准K线(可能需要与新数据合并)
        struct_conn = get_structure_connection()
        cursor = struct_conn.cursor()
        last_std = last_std_rows[0]
        cursor.execute(f"""
        DELETE FROM {std_table} 
        WHERE start_time = ?
        """, (last_std['start_time'],))
        struct_conn.commit()
        struct_conn.close()
        
        # 将最后一根标准K线加入处理队列
        klines_to_process.append({
            'start_time': last_std['start_time'],
            'end_time': last_std['end_time'],
            'open': last_std['open'],
            'high': last_std['high'],
            'low': last_std['low'],
            'close': last_std['close'],
            'volume': last_std['volume'],
            'source_count': last_std['source_count'],
        })
        
        # 确定初始方向
        if len(last_std_rows) >= 2:
            prev_std = last_std_rows[1]
            last_direction = get_direction(
                {'high': prev_std['high'], 'low': prev_std['low']},
                {'high': last_std['high'], 'low': last_std['low']}
            )
    
    # 添加新的原始K线
    for row in new_rows:
        klines_to_process.append({
            'start_time': row['start_time'],
            'end_time': row['end_time'],
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'volume': row['volume'],
            'source_count': 1,
        })
    
    # 处理包含关系
    if len(klines_to_process) < 2:
        std_klines = klines_to_process
        for k in std_klines:
            k['direction'] = last_direction
    else:
        std_klines = process_containing_relationship(klines_to_process)
    
    # 写入新的标准K线
    struct_conn = get_structure_connection()
    cursor = struct_conn.cursor()
    
    # 识别顶底分型
    fractal_labels = identify_fractals(std_klines)

    for i, k in enumerate(std_klines):
        cursor.execute(f"""
        INSERT OR REPLACE INTO {std_table}
        (symbol, start_time, end_time, open, high, low, close, volume, source_count, direction, fractal_label)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            k['start_time'],
            k['end_time'],
            k['open'],
            k['high'],
            k['low'],
            k['close'],
            k['volume'],
            k['source_count'],
            k.get('direction', 0),
            fractal_labels[i],
        ))
    
    struct_conn.commit()
    struct_conn.close()

    top_count = sum(1 for x in fractal_labels if x == 1)
    bottom_count = sum(1 for x in fractal_labels if x == -1)
    if top_count + bottom_count > 0:
        print(f"  {interval} 增量更新分型: 顶{top_count}个 / 底{bottom_count}个")
    
    # 增量更新也保存5m日志
    if interval == '5m' and len(std_klines) > 0:
        _save_5m_kline_log(std_klines, fractal_labels, top_count, bottom_count, mode='增量')
    
    return len(new_rows)


def update_all_structures(symbol='ETHUSDT'):
    """增量更新所有时间级别的结构K线"""
    results = {}
    for interval in INTERVAL_TABLE_MAP.keys():
        count = update_structure_incremental(interval, symbol)
        if count > 0:
            results[interval] = count
    return results


def get_structure_stats():
    """获取结构数据库统计信息"""
    if not STRUCTURE_DB.exists():
        return {}
    
    conn = get_structure_connection()
    cursor = conn.cursor()
    
    stats = {}
    for interval, (_, std_table) in INTERVAL_TABLE_MAP.items():
        try:
            cursor.execute(f"SELECT COUNT(*) as count FROM {std_table}")
            count = cursor.fetchone()['count']
            
            cursor.execute(f"""
            SELECT MIN(start_time) as min_time, MAX(start_time) as max_time 
            FROM {std_table}
            """)
            row = cursor.fetchone()
            
            stats[interval] = {
                'count': count,
                'min_time': row['min_time'],
                'max_time': row['max_time'],
            }
        except:
            stats[interval] = {'count': 0, 'min_time': None, 'max_time': None}
    
    conn.close()
    return stats


if __name__ == "__main__":
    print("=== 标准化K线处理引擎 ===")
    print(f"源数据库: {SOURCE_DB}")
    print(f"结构数据库: {STRUCTURE_DB}")
    
    # 处理所有时间级别
    process_all_intervals()
    
    # 显示统计信息
    print("\n=== 结构数据库统计 ===")
    stats = get_structure_stats()
    for interval, data in stats.items():
        if data['count'] > 0:
            min_dt = datetime.fromtimestamp(data['min_time'] / 1000).strftime('%Y-%m-%d %H:%M')
            max_dt = datetime.fromtimestamp(data['max_time'] / 1000).strftime('%Y-%m-%d %H:%M')
            print(f"  {interval}: {data['count']} 条 ({min_dt} ~ {max_dt})")

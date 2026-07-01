# structure_api.py - 结构K线API
from flask import Blueprint, jsonify, request
import sqlite3
from .config import (
    STRUCTURE_DB, SOURCE_DB, STRUCTURE_TABLE_MAP,
    DEFAULT_LIMIT,
    get_structure_connection,
)

structure_bp = Blueprint('structure', __name__)


def get_source_connection():
    """获取原始数据库连接"""
    conn = sqlite3.connect(str(SOURCE_DB))
    conn.row_factory = sqlite3.Row
    return conn


@structure_bp.route('/api/structure_kline', methods=['GET'])
def get_structure_kline():
    """获取结构K线数据"""
    interval = request.args.get('interval', '1m')
    limit = request.args.get('limit', DEFAULT_LIMIT, type=int)
    before = request.args.get('before', None, type=int)
    after = request.args.get('after', None, type=int)
    
    if interval not in STRUCTURE_TABLE_MAP:
        return jsonify({"error": f"不支持的时间级别: {interval}"}), 400
    
    _, std_table = STRUCTURE_TABLE_MAP[interval]
    
    # 限制最大返回数量
    if limit <= 0 or limit > DEFAULT_LIMIT:
        limit = DEFAULT_LIMIT
    
    try:
        conn = get_structure_connection()
        cursor = conn.cursor()
        
        # 构建WHERE条件：优先按时间范围查询，避免全表排序
        conditions = ["start_time IS NOT NULL"]
        params = []
        
        if before:
            conditions.append("start_time < ?")
            params.append(before)
        if after:
            conditions.append("start_time > ?")
            params.append(after)
        
        where_clause = " AND ".join(conditions)
        
        cursor.execute(f"""
        SELECT start_time, end_time, open, high, low, close, volume, source_count, direction, fractal_label
        FROM {std_table}
        WHERE {where_clause}
        ORDER BY start_time DESC
        LIMIT ?
        """, params + [limit])
        
        rows = cursor.fetchall()
        conn.close()
        
        # 转换为JSON格式，按时间升序返回
        data = []
        for row in reversed(rows):
            if row['start_time'] is not None:
                data.append({
                    "time": row['start_time'] // 1000,  # 转换为秒
                    "start_time": row['start_time'],
                    "end_time": row['end_time'],
                    "open": row['open'],
                    "high": row['high'],
                    "low": row['low'],
                    "close": row['close'],
                    "volume": row['volume'],
                    "source_count": row['source_count'],
                    "direction": row['direction'],
                    "fractal_label": row['fractal_label'],
                })
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@structure_bp.route('/api/source_kline', methods=['GET'])
def get_source_kline():
    """获取原始K线数据（用于叠加显示）"""
    interval = request.args.get('interval', '1m')
    start_time = request.args.get('start', None, type=int)
    end_time = request.args.get('end', None, type=int)
    
    if interval not in STRUCTURE_TABLE_MAP:
        return jsonify({"error": f"不支持的时间级别: {interval}"}), 400
    
    source_table, _ = STRUCTURE_TABLE_MAP[interval]
    
    if not start_time or not end_time:
        return jsonify({"error": "需要指定 start 和 end 时间戳"}), 400
    
    try:
        conn = get_source_connection()
        cursor = conn.cursor()
        
        cursor.execute(f"""
        SELECT open_time, open, high, low, close, volume
        FROM {source_table}
        WHERE open_time IS NOT NULL 
          AND open_time >= ? AND open_time <= ?
        ORDER BY open_time ASC
        """, (start_time, end_time))
        
        rows = cursor.fetchall()
        conn.close()
        
        data = []
        for row in rows:
            if row['open_time'] is not None:
                data.append({
                    "time": row['open_time'] // 1000,
                    "open": row['open'],
                    "high": row['high'],
                    "low": row['low'],
                    "close": row['close'],
                    "volume": row['volume'],
                })
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@structure_bp.route('/api/structure_stats', methods=['GET'])
def get_structure_stats():
    """获取结构数据库统计"""
    try:
        conn = get_structure_connection()
        cursor = conn.cursor()
        
        # 一次 UNION ALL 查询所有表，替代逐个查询
        parts = []
        for interval, (_, std_table) in STRUCTURE_TABLE_MAP.items():
            parts.append(
                f"SELECT '{interval}' as interval, COUNT(*), "
                f"MIN(start_time), MAX(start_time) FROM {std_table}"
            )
        sql = " UNION ALL ".join(parts)
        cursor.execute(sql)
        
        stats = {}
        for row in cursor.fetchall():
            interval, count, min_time, max_time = row
            stats[interval] = {
                "count": count,
                "min_time": min_time,
                "max_time": max_time,
            }
        
        conn.close()
        return jsonify(stats)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
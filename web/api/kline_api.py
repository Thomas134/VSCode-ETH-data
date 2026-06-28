# kline_api.py
# K线数据 API - 只读访问数据库
import bisect
import datetime
import sqlite3
from flask import Blueprint, jsonify, request
from .config import (
    BASE_DIR, DB_PATH, STRUCTURE_DB,
    KLINE_TABLE_MAP, FRACTAL_TABLE_MAP, INTERVAL_MS,
    DEFAULT_LIMIT
)
from .cache_manager import kline_cache

kline_bp = Blueprint('kline', __name__)

def get_db_connection():
    """获取只读数据库连接（启用WAL模式优化并发）"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.row_factory = sqlite3.Row
    return conn

def get_structure_connection():
    """获取结构数据库连接（启用WAL模式优化并发）"""
    conn = sqlite3.connect(f"file:{STRUCTURE_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.row_factory = sqlite3.Row
    return conn

def _match_fractals_scanline(rows, fractal_ranges):
    """
    单指针扫描线算法 - O(N + M) 匹配K线和分型区间

    rows: K线数据，按 open_time 升序排列（open_time 为毫秒）
    fractal_ranges: 分型区间，按 start/start_time 升序排列。
        元素需含 (start 或 start_time), (end 或 end_time), label, high, low
        时间戳统一为秒（与前端格式一致）

    返回: 匹配后的K线数据列表（含分型标记）
    """
    if not fractal_ranges:
        return [{
            "time": int(row["open_time"]) // 1000,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        } for row in rows]

    # 统一分型字段名：兼容 {start,end}（毫秒）和 {start_time,end_time}（秒）两种格式
    first = fractal_ranges[0]
    fr_start_key = 'start' if 'start' in first else 'start_time'
    fr_end_key = 'end' if 'end' in first else 'end_time'

    data = []
    f_ptr = 0
    m = len(fractal_ranges)

    for row in rows:
        ot_sec = int(row["open_time"]) // 1000  # K线时间统一转秒

        # 推进分型指针：跳过所有已结束的分型（end <= 当前K线时间）
        while f_ptr < m and ot_sec >= fractal_ranges[f_ptr][fr_end_key]:
            f_ptr += 1

        # 检查当前分型是否覆盖这根K线（左闭右开 [start, end)）
        if f_ptr < m and ot_sec >= fractal_ranges[f_ptr][fr_start_key] and ot_sec < fractal_ranges[f_ptr][fr_end_key]:
            fr = fractal_ranges[f_ptr]
            item = {
                "time": ot_sec,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        else:
            item = {
                "time": ot_sec,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        data.append(item)

    return data


@kline_bp.route('/api/kline', methods=['GET'])
def get_kline():
    """
    获取K线数据 (支持分页，并附带分型标记)
    参数:
        interval: 时间级别 (1m, 5m, 15m, 1h, 4h, 1d)
        limit: 返回数量 (默认 2000, 最大 2000)
        before: 获取此时间戳之前的数据 (毫秒级, 可选)
    """
    interval = request.args.get('interval', '1m')
    limit = int(request.args.get('limit', DEFAULT_LIMIT))
    before = request.args.get('before', None)
    
    if interval not in KLINE_TABLE_MAP:
        return jsonify({"error": f"不支持的时间级别: {interval}"}), 400
    
    table_name = KLINE_TABLE_MAP[interval]
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建查询 - 支持分页
        if before:
            before_ts = int(before)
            query = f"""
            SELECT open_time, open, high, low, close, volume
            FROM {table_name}
            WHERE open_time IS NOT NULL AND open_time < ?
            ORDER BY open_time DESC
            LIMIT ?
            """
            cursor.execute(query, (before_ts, limit))
        else:
            query = f"""
            SELECT open_time, open, high, low, close, volume
            FROM {table_name}
            WHERE open_time IS NOT NULL
            ORDER BY open_time DESC
            LIMIT ?
            """
            cursor.execute(query, (limit,))
        
        # 使用 fetchmany 分批读取
        rows = []
        batch_size = 1000
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            rows.extend(batch)
        
        # ── 从结构表读取分型区间 ──
        fractal_ranges = []
        if rows and interval in FRACTAL_TABLE_MAP:
            min_time = rows[-1]['open_time']
            max_time = rows[0]['open_time']
            std_table = FRACTAL_TABLE_MAP[interval]
            
            try:
                struct_conn = get_structure_connection()
                struct_cursor = struct_conn.cursor()
                # 查所有标准K线（含非分型），用于定位每个分型的下一根K线
                struct_cursor.execute(f"""
                SELECT start_time, end_time, high, low, fractal_label
                FROM {std_table}
                WHERE start_time >= ? AND start_time < ?
                ORDER BY start_time ASC
                """, (min_time, max_time))
                
                # 使用 fetchmany 分批读取
                all_std_rows = []
                batch_size = 1000
                while True:
                    batch = struct_cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    all_std_rows.extend(batch)
                
                # 从所有标准K线中筛选出分型行，同时记录每个分型的下一行索引
                for idx, sr in enumerate(all_std_rows):
                    label = sr['fractal_label']
                    if label == 0:
                        continue
                    fractal_ranges.append({
                        'start': sr['start_time'],
                        'end': sr['end_time'],
                        'high': float(sr['high']),
                        'low': float(sr['low']),
                        'label': label,
                        # 下一根标准K线（即K3）的行
                        'next_row': all_std_rows[idx + 1] if idx + 1 < len(all_std_rows) else None,
                    })
                
                struct_conn.close()
            except:
                pass
        
        conn.close()
        
        # 用扫描线算法匹配K线和分型
        data = _match_fractals_scanline(reversed(rows), fractal_ranges)
        
        # 构建分型区间（给前端画矩形框用）
        interval_ms = INTERVAL_MS.get(interval, 60000)
        
        regions = []
        for fr in fractal_ranges:
            right_time = (fr['end'] - interval_ms) // 1000  # 最后一根原始K线的秒时间
            
            # 计算 confirm_time = K3覆盖的最后一根原始K线的 open_time
            if fr['next_row']:
                confirm_time_ms = fr['next_row']['end_time'] - interval_ms
                confirm_time = confirm_time_ms // 1000  # 转秒
            else:
                confirm_time = right_time  # 没有K3时，用自身的最后一根原始K线时间兜底
            
            regions.append({
                "start_time": fr['start'] // 1000,  # 转秒
                "end_time": right_time,               # 左闭右开：取最后一根的时间
                "high": fr['high'],
                "low": fr['low'],
                "label": fr['label'],
                "confirm_time": confirm_time,
            })
        
        # ── 无 before 参数时（初始加载），才缓存分型结果 ──
        if before is None:
            kline_cache.set_fractals(interval, regions)
        
        return jsonify({
            "data": data,
            "fractal_regions": regions,
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ──────────────────────────────────────────────
# 分型区间过滤函数
# ──────────────────────────────────────────────


def print_fractals_to_file(fractal_ranges, source_rows, output_path="fractal_debug.txt"):
    """将当前分型信息打印到txt文件（调试用），时间戳转为可读日期"""
    all_times = sorted([int(r['open_time']) for r in source_rows])
    
    def ts_to_dt(ts_ms):
        """毫秒时间戳转可读日期字符串"""
        return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"分型总数: {len(fractal_ranges)}\n")
        f.write(f"K线总数: {len(all_times)}\n")
        f.write(f"时间范围: {ts_to_dt(all_times[0])} ~ {ts_to_dt(all_times[-1])}\n")
        f.write("=" * 80 + "\n\n")
        
        for i, fr in enumerate(fractal_ranges):
            label_str = "顶分型 ▲" if fr['label'] == 1 else "底分型 ▼"
            f.write(f"分型[{i}]: {label_str}\n")
            f.write(f"  start: {ts_to_dt(fr['start'])}\n")
            f.write(f"  end:   {ts_to_dt(fr['end'])}\n")
            f.write(f"  high:  {fr['high']}\n")
            f.write(f"  low:   {fr['low']}\n")
            
            # 统计该分型覆盖的K线数量
            kline_count = sum(1 for t in all_times if fr['start'] <= t < fr['end'])
            f.write(f"  覆盖K线数: {kline_count}\n")
            f.write("\n")
        
        f.write("=" * 80 + "\n")
        f.write("分型序列摘要: ")
        for fr in fractal_ranges:
            label_str = "▲" if fr['label'] == 1 else "▼"
            f.write(f"[{label_str}] ")
        f.write("\n")


def check_fractal_alternation(fractal_ranges):
    """
    检测分型是否严格交替出现（顶 → 底 → 顶 → 底 ...）
    返回 (is_alternating: bool, first_violation: int)
    """
    if len(fractal_ranges) < 2:
        return True, -1
    
    for i in range(len(fractal_ranges) - 1):
        current = fractal_ranges[i]['label']
        next_label = fractal_ranges[i + 1]['label']
        if current == next_label:
            return False, i
    
    return True, -1


def filter_fractal_regions(fractal_ranges, source_rows):
    """
    过滤分型区间。
    
    规则：
    遍历到分型 b（当前）时：
      1. 往前看：a（前一个）和 b 如果是同类型 → 竞争
         - 顶分型：保留更高价的，淘汰另一个
         - 底分型：保留更低价的，淘汰另一个
         - b 胜出 → 删除 a，检查 b 和 c（后一个）的自由K线
         - a 胜出 → 删除 b，检查 a 和 c 的自由K线
         - 自由K线检查不通过 → 删除后一个分型
      2. 如果 a 和 b 不同类型 → 跳过竞争，直接往后走原有的自由K线检查
    
    参数:
        fractal_ranges: [{start, end, high, low, label}, ...] 已按 start 升序
        source_rows: 原始K线 rows（含 open_time）
    
    返回:
        过滤后的 fractal_ranges
    """
    if len(fractal_ranges) < 2:
        return fractal_ranges
    
    all_times = sorted([int(r['open_time']) for r in source_rows])
    
    # 预计算每个分型在 all_times 中的覆盖区间 [left, right)
    # 用二分查找，O(N log M)
    intervals = []
    for fr in fractal_ranges:
        left = bisect.bisect_left(all_times, fr['start'])
        right = bisect.bisect_left(all_times, fr['end'])
        intervals.append((left, right))
    
    # 用标记数组代替频繁 pop，避免 O(N) 的列表移位开销
    valid = [True] * len(fractal_ranges)
    
    # 构建每根K线所属的分型索引映射（只构建一次）
    # kline_fractal[t_idx] = 该K线所属的最后一个分型索引，-1 表示不属于任何分型
    kline_fractal = [-1] * len(all_times)
    for idx in range(len(fractal_ranges)):
        left, right = intervals[idx]
        for t_idx in range(left, right):
            kline_fractal[t_idx] = idx
    
    while True:
        removed = False
        
        # 找到第一个有效分型的索引
        i = 0
        while i < len(fractal_ranges) and not valid[i]:
            i += 1
        if i >= len(fractal_ranges):
            break
        
        # 遍历有效分型
        while True:
            # 找下一个有效分型 b
            j = i + 1
            while j < len(fractal_ranges) and not valid[j]:
                j += 1
            if j >= len(fractal_ranges):
                break
            
            a = fractal_ranges[i]
            b = fractal_ranges[j]
            
            # ── 第一步：往前看 — 同类型竞争 ──
            if a['label'] == b['label']:
                if a['label'] == 1:  # 顶分型：保留更高价
                    a_wins = a['high'] >= b['high']
                else:  # 底分型：保留更低价
                    a_wins = a['low'] <= b['low']
                
                if a_wins:
                    # a 胜出 → 标记 b 为无效
                    valid[j] = False
                    # 检查 a 和 下一个有效分型 c 的自由K线
                    k = j + 1
                    while k < len(fractal_ranges) and not valid[k]:
                        k += 1
                    if k < len(fractal_ranges):
                        c = fractal_ranges[k]
                        if not _has_free_kline_between_fast(
                            a, c, intervals, i, k, valid, kline_fractal, all_times
                        ):
                            valid[k] = False
                else:
                    # b 胜出 → 标记 a 为无效
                    valid[i] = False
                    # 检查 b（现在的第一个有效）和 下一个有效分型 c 的自由K线
                    k = j + 1
                    while k < len(fractal_ranges) and not valid[k]:
                        k += 1
                    if k < len(fractal_ranges):
                        c = fractal_ranges[k]
                        if not _has_free_kline_between_fast(
                            b, c, intervals, j, k, valid, kline_fractal, all_times
                        ):
                            valid[k] = False
                
                removed = True
                break  # 重新扫描
            
            # ── 第二步：不同类型 → 自由K线检查 ──
            else:
                if not _has_free_kline_between_fast(
                    a, b, intervals, i, j, valid, kline_fractal, all_times
                ):
                    valid[j] = False
                    removed = True
                    break
                i = j
        
        if not removed:
            break
    
    result = [fr for idx, fr in enumerate(fractal_ranges) if valid[idx]]
    
    # ── 调试输出：打印分型到文件并检查交替性 ──
    print_fractals_to_file(result, source_rows)
    is_alt, violate_idx = check_fractal_alternation(result)
    if not is_alt:
        v0 = result[violate_idx]
        v1 = result[violate_idx + 1]
        def ts_to_dt(ts_ms):
            return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[WARNING] 分型未交替出现! 第{violate_idx}和{violate_idx+1}个分型类型相同")
        print(f"  分型[{violate_idx}]: {'顶' if v0['label']==1 else '底'}, "
              f"high={v0['high']}, low={v0['low']}, time={ts_to_dt(v0['start'])}")
        print(f"  分型[{violate_idx+1}]: {'顶' if v1['label']==1 else '底'}, "
              f"high={v1['high']}, low={v1['low']}, time={ts_to_dt(v1['start'])}")
    else:
        print(f"[OK] 分型严格交替出现, 共{len(result)}个分型")
    
    return result


def _has_free_kline_between_fast(a, b, intervals, a_idx, b_idx, valid, kline_fractal, all_times):
    """
    检查分型 A 和 B 之间是否有至少1根自由K线。
    
    使用预计算的 intervals 和 kline_fractal 映射，O(1) 判断每根K线是否自由。
    只检查 [A.end, B.end) 之间的K线。
    """
    a_right = intervals[a_idx][1]
    b_right = intervals[b_idx][1]
    
    # 检查范围：从 A 的结束位置到 B 的结束位置
    if a_right >= b_right:
        return False
    
    # 遍历检查范围内的K线，看是否有不属于任何有效分型的自由K线
    for t_idx in range(a_right, b_right):
        owner = kline_fractal[t_idx]
        if owner == -1 or not valid[owner]:
            return True  # 找到了自由K线
    
    return False


@kline_bp.route('/api/intervals', methods=['GET'])
def get_intervals():
    """获取可用的时间级别"""
    return jsonify(list(KLINE_TABLE_MAP.keys()))


@kline_bp.route('/api/fractals', methods=['GET'])
def get_fractals():
    """
    获取指定时间范围内的分型数据（用于回测）
    参数:
        interval: 时间级别 (1m, 5m, 15m, 1h, 4h, 1d)
        start: 起始时间戳(毫秒)
        end: 结束时间戳(毫秒)
        limit: 最大返回数量 (默认20000, 最大50000)
    返回:
        [{start_time: 秒, confirm_time: 秒, high: float, low: float, label: int}, ...]
        confirm_time: 分型确认时间（需要看到第3根K线才能确认）
    """
    interval = request.args.get('interval', '1m')
    start = request.args.get('start', None, type=int)
    end = request.args.get('end', None, type=int)
    limit = min(int(request.args.get('limit', 20000)), 50000)

    if interval not in FRACTAL_TABLE_MAP:
        return jsonify({"error": f"不支持的时间级别: {interval}"}), 400

    std_table = FRACTAL_TABLE_MAP[interval]
    interval_ms = INTERVAL_MS.get(interval, 60000)

    try:
        struct_conn = get_structure_connection()
        cursor = struct_conn.cursor()

        # 查所有标准K线（含非分型行），用于定位每个分型的下一根K线（K3）
        conditions = []  # 不限制 fractal_label
        params = []

        if start:
            conditions.append("start_time >= ?")
            params.append(start)
        if end:
            conditions.append("start_time <= ?")
            params.append(end)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 多查一条，确保最后一个分型也能找到下一行
        cursor.execute(f"""
        SELECT start_time, end_time, high, low, fractal_label
        FROM {std_table}
        WHERE {where_clause}
        ORDER BY start_time ASC
        LIMIT ?
        """, params + [limit + 1])

        # 使用 fetchmany 分批读取
        all_rows = []
        batch_size = 5000
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            all_rows.extend(batch)
        
        struct_conn.close()

        if not all_rows:
            return jsonify([])

        # 构建所有标准K线的 start_time → (end_time, fractal_label) 映射（保持顺序）
        # 用于快速找到每个分型的下一行
        result = []
        for idx, row in enumerate(all_rows):
            label = row['fractal_label']
            if label == 0:
                continue  # 跳过非分型行，但保留它在 all_rows 中用于定位K3

            item = {
                "start_time": row['start_time'] // 1000,
                "high": float(row['high']),
                "low": float(row['low']),
                "label": label,
            }

            # 分型的确认时间 = 下一根标准K线（K3）覆盖的最后一根原始K线的 open_time
            # 即 K3.end_time - interval_ms
            if idx + 1 < len(all_rows):
                next_row = all_rows[idx + 1]
                confirm_time_ms = next_row['end_time'] - interval_ms
                item['confirm_time'] = confirm_time_ms // 1000  # 转秒
            else:
                # 最后一个分型没有下一根K线，用自身的 end_time 兜底
                confirm_time_ms = row['end_time'] - interval_ms
                item['confirm_time'] = confirm_time_ms // 1000

            result.append(item)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kline_bp.route('/api/stats', methods=['GET'])
def get_stats():
    """获取数据库统计信息"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 一次 UNION ALL 查询所有表，替代逐个查询
        parts = []
        for interval, table_name in KLINE_TABLE_MAP.items():
            parts.append(
                f"SELECT '{interval}' as interval, COUNT(*), "
                f"MIN(open_time), MAX(open_time) FROM {table_name}"
            )
        sql = " UNION ALL ".join(parts)
        cursor.execute(sql)
        
        # 使用 fetchmany 分批读取统计结果
        stats = {}
        while True:
            batch = cursor.fetchmany(10)  # 只有6个时间级别，一次取10个足够
            if not batch:
                break
            for row in batch:
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

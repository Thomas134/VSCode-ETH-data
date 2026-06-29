"""
实时缠论K线API - 本地历史 + Bybit实时 + 实时计算分型
最小改动方案：复用 structure_analyzer 的计算逻辑
"""
import sys
from pathlib import Path
import sqlite3

# 添加路径导入现有模块
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bybit_eth_data" / "scripts"))

from flask import Blueprint, jsonify, request
from bybit_client import BybitClient
from structure_analyzer import process_containing_relationship, identify_fractals
from .config import DB_PATH, STRUCTURE_DB, KLINE_TABLE_MAP, FRACTAL_TABLE_MAP, INTERVAL_MS

realtime_bp = Blueprint('realtime_kline', __name__)
bybit_client = BybitClient()

# Bybit时间级别映射
BYBIT_INTERVAL = {'1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D'}


def get_db_connection():
    """获取源数据库连接"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_structure_connection():
    """获取结构数据库连接"""
    conn = sqlite3.connect(f"file:{STRUCTURE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_local_klines_with_fractal(interval, limit=500):
    """从本地获取已有分型的K线数据"""
    table = KLINE_TABLE_MAP[interval]
    std_table = FRACTAL_TABLE_MAP[interval]
    interval_ms = INTERVAL_MS[interval]
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 获取K线数据
    cur.execute(f"""
        SELECT open_time, open, high, low, close, volume
        FROM {table}
        ORDER BY open_time DESC
        LIMIT ?
    """, (limit,))
    
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        return []
    
    # 获取分型数据
    times = [r['open_time'] for r in rows]
    min_time, max_time = min(times), max(times)
    
    fractal_map = {}
    try:
        conn = get_structure_connection()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT start_time, fractal_label
            FROM {std_table}
            WHERE start_time >= ? AND start_time <= ? AND fractal_label != 0
        """, (min_time, max_time))
        
        for row in cur.fetchall():
            fractal_map[row['start_time']] = row['fractal_label']
        conn.close()
    except Exception as e:
        print(f"[DB Error] 获取分型失败: {e}")
    
    # 组装数据（structure_analyzer需要的格式）
    klines = []
    for row in reversed(rows):
        start_time = row['open_time']
        klines.append({
            'start_time': start_time,
            'end_time': start_time + interval_ms,
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume']),
            'fractal_label': fractal_map.get(start_time, 0)
        })
    
    return klines


def get_bybit_latest(interval, limit=5):
    """从Bybit获取最新K线"""
    if interval not in BYBIT_INTERVAL:
        return []
    
    try:
        klines = bybit_client.get_klines("ETHUSDT", BYBIT_INTERVAL[interval], limit=limit)
        if not klines:
            return []
        
        interval_ms = INTERVAL_MS[interval]
        result = []
        for k in klines:
            start_time = int(k[0])
            result.append({
                'start_time': start_time,
                'end_time': start_time + interval_ms,
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'fractal_label': 0  # 未计算分型
            })
        return result
    except Exception as e:
        print(f"[Bybit Error] {e}")
        return []


def fill_gap_klines(interval, start_time, end_time):
    """
    从Bybit获取指定时间区间的K线数据，填补断层
    简化逻辑：直接获取区间内的所有数据
    """
    if interval not in BYBIT_INTERVAL:
        return []
    
    try:
        interval_ms = INTERVAL_MS[interval]
        
        # 直接获取整个区间的数据（Bybit最多返回200条，应该够用了）
        klines = bybit_client.get_klines(
            "ETHUSDT", 
            BYBIT_INTERVAL[interval], 
            start_time=start_time,
            limit=200
        )
        
        if not klines:
            print(f"[Fill Gap] 无数据返回")
            return []
        
        # 过滤在目标区间内的数据
        all_klines = []
        for k in klines:
            k_time = int(k[0])
            if start_time <= k_time <= end_time:
                all_klines.append({
                    'start_time': k_time,
                    'end_time': k_time + interval_ms,
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),
                    'fractal_label': 0
                })
        
        print(f"[Fill Gap] 区间 {start_time} ~ {end_time}, 获取 {len(all_klines)} 条数据")
        return all_klines
        
    except Exception as e:
        print(f"[Fill Gap Error] {e}")
        import traceback
        traceback.print_exc()
        return []


def format_kline_for_frontend(k):
    """转换为前端需要的格式"""
    return {
        'time': k['start_time'] // 1000,  # 转秒
        'open': k['open'],
        'high': k['high'],
        'low': k['low'],
        'close': k['close'],
        'volume': k['volume'],
        'fractal_label': k.get('fractal_label', 0)
    }


@realtime_bp.route('/api/kline/realtime', methods=['GET'])
def get_realtime_kline():
    """
    获取带缠论分型的实时K线
    逻辑：本地历史 + Bybit最新 → 合并 → 计算最后10根分型 → 返回
    """
    interval = request.args.get('interval', '1m')
    limit = int(request.args.get('limit', 500))
    
    if interval not in KLINE_TABLE_MAP:
        return jsonify({"error": f"不支持的时间级别: {interval}"}), 400
    
    try:
        # 1. 获取本地数据（已有分型）
        local_klines = get_local_klines_with_fractal(interval, limit)
        
        # 2. 获取Bybit实时数据
        live_klines = get_bybit_latest(interval, limit=5)
        
        # 3. 【新增】检测并填补断层（仅在第一次加载时执行，limit > 100认为是首次加载）
        interval_ms = INTERVAL_MS[interval]
        gap_filled_count = 0
        
        # 只在首次加载时判断断层，轮询更新时不判断
        if limit > 100 and local_klines and live_klines:
            # 获取本地最后一条的结束时间和实时第一条的开始时间
            local_last_end = local_klines[-1]['end_time']
            live_first_start = live_klines[0]['start_time']
            
            # 检测是否有断层（间隔超过一个K线周期）
            gap_threshold = interval_ms * 2
            
            if live_first_start > local_last_end + gap_threshold:
                gap_size = (live_first_start - local_last_end) // interval_ms - 1
                print(f"[Gap Detected] 本地结束: {local_last_end}, 实时开始: {live_first_start}, 断层: {gap_size} 根K线")
                
                # 限制最大填补数量（避免一次性获取太多数据）
                MAX_GAP_FILL = 200  # 最多填补200条
                
                # 计算需要填补的区间
                # 从本地最后一条的下一条开始，到实时第一条的前一条结束（或最多MAX_GAP_FILL条）
                gap_start = local_last_end
                
                if gap_size > MAX_GAP_FILL:
                    print(f"[Gap Warning] 断层太大({gap_size}条)，只填补最近{MAX_GAP_FILL}条")
                    # 只填补最近的MAX_GAP_FILL条
                    gap_start = live_first_start - interval_ms * (MAX_GAP_FILL + 1)
                
                gap_end = live_first_start - interval_ms
                
                # 获取缺失的数据
                gap_klines = fill_gap_klines(interval, gap_start, gap_end)
                
                if gap_klines:
                    gap_filled_count = len(gap_klines)
                    print(f"[Gap Filled] 成功填补 {gap_filled_count} 条数据")
                    # 将填补的数据插入到实时数据之前
                    live_klines = gap_klines + live_klines
                else:
                    print("[Gap Warning] 无法获取断层数据")
        
        # 4. 合并数据（新数据覆盖旧数据）
        time_map = {k['start_time']: k for k in local_klines}
        
        for live_k in live_klines:
            time_map[live_k['start_time']] = live_k  # 新数据覆盖
        
        # 按时间排序
        merged = sorted(time_map.values(), key=lambda x: x['start_time'])
        
        # 4. 关键：对最后12根重新计算分型（因为新增K线可能影响前2根的分型判断）
        CALC_WINDOW = 12
        
        if len(merged) > CALC_WINDOW:
            # 前部分保持不变（已有分型）
            result = merged[:-CALC_WINDOW]
            to_calc = merged[-CALC_WINDOW:]
            
            # 重新计算分型
            std_klines = process_containing_relationship(to_calc)
            fractal_labels = identify_fractals(std_klines)
            
            # 将分型标记写回
            for i, k in enumerate(std_klines):
                k['fractal_label'] = fractal_labels[i]
            
            result.extend(std_klines)
        else:
            # 数据量少，全部重新计算
            std_klines = process_containing_relationship(merged)
            fractal_labels = identify_fractals(std_klines)
            
            for i, k in enumerate(std_klines):
                k['fractal_label'] = fractal_labels[i]
            
            result = std_klines
        
        # 5. 构建分型区间（给前端画线用）
        fractal_regions = build_fractal_regions(result, interval)
        
        # 6. 转换为前端格式
        data = [format_kline_for_frontend(k) for k in result]
        
        return jsonify({
            "data": data,
            "fractal_regions": fractal_regions,
            "source": "realtime",
            "is_realtime": len(live_klines) > 0,
            "local_count": len(local_klines),
            "live_count": len(live_klines),
            "gap_filled_count": gap_filled_count
        })
        
    except Exception as e:
        print(f"[Realtime API Error] {e}")
        import traceback
        traceback.print_exc()
        
        # 出错时返回本地数据保底
        try:
            local_klines = get_local_klines_with_fractal(interval, limit)
            data = [format_kline_for_frontend(k) for k in local_klines]
            return jsonify({
                "data": data,
                "fractal_regions": [],
                "source": "local_fallback",
                "error": str(e)
            })
        except:
            return jsonify({"error": str(e)}), 500


def build_fractal_regions(klines, interval):
    """
    构建立分型区间（复用 kline_api.py 的逻辑）
    用于前端画水平线
    """
    interval_ms = INTERVAL_MS[interval]
    regions = []
    
    for i, k in enumerate(klines):
        label = k.get('fractal_label', 0)
        if label == 0:
            continue
        
        # 分型区间：从分型K线开始，到下一根K线结束
        start_time = k['start_time']
        
        # 找下一根K线作为结束
        if i + 1 < len(klines):
            end_time = klines[i + 1]['end_time']
            confirm_time = klines[i + 1]['start_time']  # 确认时间 = 下一根K线开始
        else:
            # 最后一根，用自身结束时间
            end_time = k['end_time']
            confirm_time = k['end_time'] - interval_ms
        
        regions.append({
            "start_time": start_time // 1000,
            "end_time": (end_time - interval_ms) // 1000,
            "high": k['high'],
            "low": k['low'],
            "label": label,
            "confirm_time": confirm_time // 1000
        })
    
    return regions


@realtime_bp.route('/api/kline/latest_tick', methods=['GET'])
def get_latest_tick():
    """获取最新价格（轻量级，用于顶部价格栏）"""
    interval = request.args.get('interval', '1m')
    
    try:
        live = get_bybit_latest(interval, limit=1)
        if live:
            k = live[0]
            return jsonify({
                "price": k['close'],
                "open": k['open'],
                "high": k['high'],
                "low": k['low'],
                "volume": k['volume'],
                "time": k['start_time'] // 1000,
                "source": "bybit"
            })
        else:
            return jsonify({"error": "获取失败"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500
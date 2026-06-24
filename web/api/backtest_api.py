# web/api/backtest_api.py
"""回测API - 由Flask进程内直接执行回测（不再走subprocess）"""
import json
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request
from .config import (
    DB_PATH, STRUCTURE_DB,
    KLINE_TABLE_MAP, FRACTAL_TABLE_MAP, INTERVAL_MS
)

backtest_bp = Blueprint('backtest', __name__)

# 验证参数合法性
VALID_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
VALID_MODES = ["long", "short", "both"]
VALID_POS_MODES = ["fixed", "percent"]


def _load_kline_with_signals(interval, start_date, end_date):
    """
    从数据库加载K线数据，并将分型信号直接附加到每根K线上。
    返回: [{time, open, high, low, close, volume, signal}, ...]
    """
    import sqlite3
    import datetime

    table_name = KLINE_TABLE_MAP.get(interval, "kline_1m")
    std_table = FRACTAL_TABLE_MAP.get(interval, "kline_1m_std")
    interval_ms = INTERVAL_MS.get(interval, 60000)

    # 转换日期
    start_ms = None
    end_ms = None
    if start_date:
        dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        start_ms = int(dt.timestamp() * 1000)
    if end_date:
        dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
        end_ms = int(dt.timestamp() * 1000)

    # 1. 加载K线数据
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()

    conditions = ["open_time IS NOT NULL"]
    params = []
    if start_ms:
        conditions.append("open_time >= ?")
        params.append(start_ms)
    if end_ms:
        conditions.append("open_time < ?")
        params.append(end_ms)
    where = " AND ".join(conditions)

    cursor.execute(f"""
    SELECT open_time, open, high, low, close, volume
    FROM {table_name}
    WHERE {where}
    ORDER BY open_time ASC
    """, params)
    kline_rows = cursor.fetchall()
    conn.close()

    if not kline_rows:
        return []

    # 2. 加载分型数据（一次查询获取所有标准K行，计算每个分型的confirm_time）
    min_time = kline_rows[0][0]
    max_time = kline_rows[-1][0]

    conn = sqlite3.connect(f"file:{STRUCTURE_DB}?mode=ro", uri=True)
    cursor = conn.cursor()

    cursor.execute(f"""
    SELECT start_time, end_time, fractal_label
    FROM {std_table}
    WHERE start_time >= ? AND start_time < ?
    ORDER BY start_time ASC
    """, (min_time, max_time))
    all_std_rows = cursor.fetchall()
    conn.close()

    # 构建 trigger_map: confirm_time(秒) → signal(-1或1)
    trigger_map = {}
    for idx, row in enumerate(all_std_rows):
        label = row[2]
        if label == 0:
            continue
        # confirm_time = 下一根标准K线的end_time - interval
        if idx + 1 < len(all_std_rows):
            confirm_time_ms = all_std_rows[idx + 1][1] - interval_ms
        else:
            confirm_time_ms = row[1] - interval_ms
        trigger_map[confirm_time_ms // 1000] = label

    # 3. 构建带信号的K线数据
    kline_data = []
    for row in kline_rows:
        ot_sec = int(row[0]) // 1000
        signal = trigger_map.get(ot_sec, 0)
        kline_data.append({
            "time": ot_sec,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "signal": signal,
        })

    return kline_data


@backtest_bp.route('/api/backtest', methods=['POST'])
def run_backtest():
    """
    全量回测入口 - 在Flask进程内直接执行
    """
    try:
        params = request.get_json()
        if not params:
            return jsonify({"error": "请求体为空"}), 400

        # 参数校验
        interval = params.get("interval", "1m")
        if interval not in VALID_INTERVALS:
            return jsonify({"error": f"不支持的时间级别: {interval}"}), 400

        mode = params.get("mode", "both")
        if mode not in VALID_MODES:
            return jsonify({"error": f"不支持的交易模式: {mode}"}), 400

        pos_mode = params.get("position_mode", "percent")
        if pos_mode not in VALID_POS_MODES:
            return jsonify({"error": f"不支持的仓位模式: {pos_mode}"}), 400

        stop_loss = float(params.get("stop_loss_pct", 2.0))
        if not (0.01 <= stop_loss <= 100):
            return jsonify({"error": "止损%范围 0.01~100"}), 400

        take_profit = float(params.get("take_profit_pct", 5.0))
        if not (0.01 <= take_profit <= 100):
            return jsonify({"error": "止盈%范围 0.01~100"}), 400

        capital = float(params.get("initial_capital", 10000))
        if capital < 1:
            return jsonify({"error": "初始资金至少 1"}), 400

        # 加载K线数据并匹配分型信号
        kline_data = _load_kline_with_signals(
            interval,
            params.get("start_date", ""),
            params.get("end_date", ""),
        )

        if len(kline_data) < 10:
            return jsonify({"error": f"K线数据不足 ({len(kline_data)} 根)"}), 400

        # 在Flask进程内直接执行回测
        engine_path = Path(__file__).resolve().parents[2] / "backtest" / "engine.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("backtest_engine_module", engine_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        BacktestEngine = mod.BacktestEngine

        engine = BacktestEngine({
            "kline_data": kline_data,
            "mode": mode,
            "stop_loss_pct": stop_loss,
            "take_profit_pct": take_profit,
            "initial_capital": capital,
            "fee_rate": float(params.get("fee_rate", 0.05)),
            "position_mode": pos_mode,
            "percent_per_trade": float(params.get("percent_per_trade", 20)),
            "fixed_amount": float(params.get("fixed_amount", 1000)),
            "max_positions": int(params.get("max_positions", 3)),
            "use_stop_profit": params.get("use_stop_profit", True),
        })

        result = engine.run()

        if "error" in result:
            return jsonify(result), 400

        return jsonify(result)

    except Exception as e:
        print(f"[Backtest] 错误: {e}")
        return jsonify({"error": str(e)}), 500

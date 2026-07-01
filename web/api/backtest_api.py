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
from .cache_manager import backtest_cache
from .memory_monitor import log_memory, force_gc
from .json_profiler import JSONProfiler  # JSON性能测试
from .logger import get_logger

logger = get_logger(__name__)

backtest_bp = Blueprint('backtest', __name__)

# 验证参数合法性
VALID_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
VALID_MODES = ["long", "short", "both"]
VALID_POS_MODES = ["fixed", "percent"]


def _get_cache_key_params(params, interval, start_date, end_date):
    """
    生成用于缓存的参数字典
    使用日期范围和interval作为数据指纹
    """
    return {
        "interval": interval,
        "start_date": start_date,
        "end_date": end_date,
        "mode": params.get("mode"),
        "stop_loss_pct": params.get("stop_loss_pct"),
        "take_profit_pct": params.get("take_profit_pct"),
        "initial_capital": params.get("initial_capital"),
        "fee_rate": params.get("fee_rate"),
        "position_mode": params.get("position_mode"),
        "percent_per_trade": params.get("percent_per_trade"),
        "fixed_amount": params.get("fixed_amount"),
        "max_positions": params.get("max_positions"),
        "use_stop_profit": params.get("use_stop_profit"),
    }


@backtest_bp.route('/api/backtest', methods=['POST'])
def run_backtest():
    """
    全量回测入口 - 在Flask进程内直接执行（支持缓存）
    """
    log_memory("回测开始")
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

        # 生成缓存key参数（不依赖kline_data）
        cache_params = _get_cache_key_params(params, interval, 
                                            params.get("start_date", ""),
                                            params.get("end_date", ""))
        
        # 检查缓存（除非明确要求跳过缓存）
        skip_cache = params.get("_skip_cache", False)
        if not skip_cache:
            cached_result = backtest_cache.get(cache_params)
            if cached_result:
                logger.info("回测缓存命中，直接返回结果")
                return JSONProfiler.profile(cached_result, "backtest_cached")

        # 使用流式回测引擎 - 边读边算，不存储全部K线
        from backtest.streaming_engine import StreamingBacktestEngine
        
        engine = StreamingBacktestEngine({
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

        # 流式执行 - 不加载全部K线到内存
        result = engine.run_streaming(
            interval,
            params.get("start_date", ""),
            params.get("end_date", "")
        )
        log_memory("回测引擎完成")

        if "error" in result:
            return jsonify(result), 400

        # 保存结果到缓存
        if not skip_cache:
            backtest_cache.set(cache_params, result)
            logger.info("回测结果已缓存")
        
        # 删除引用
        del engine
        force_gc()
        log_memory("清理后")

        return JSONProfiler.profile(result, "backtest")

    except Exception as e:
        logger.error("回测错误: %s", e)
        return jsonify({"error": str(e)}), 500


@backtest_bp.route('/api/backtest/cache/clear', methods=['POST'])
def clear_backtest_cache():
    """
    清除回测缓存
    
    请求体可选参数:
        params: 指定参数则只清除该参数的缓存，不传则清除所有
    """
    try:
        data = request.get_json() or {}
        target_params = data.get("params")
        
        if target_params:
            backtest_cache.clear(target_params)
            return jsonify({"status": "ok", "message": "指定参数的缓存已清除"})
        else:
            backtest_cache.clear_all()
            return jsonify({"status": "ok", "message": "所有回测缓存已清除"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backtest_bp.route('/api/backtest/cache/stats', methods=['GET'])
def get_backtest_cache_stats():
    """获取回测缓存统计信息"""
    try:
        stats = backtest_cache.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
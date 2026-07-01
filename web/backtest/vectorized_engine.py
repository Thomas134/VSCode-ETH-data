"""
向量化回测引擎 - DuckDB 一次性加载 + 内存计算

核心设计：
1. 一次性从 DuckDB 加载全部 K 线和分型信号到内存
2. 回测逻辑和 streaming_engine.py 完全一致（逐条处理）
3. 唯一区别：数据在内存中，避免数据库 IO 开销

参数、开仓/平仓/止损止盈逻辑 和流式引擎 100% 一致
"""
import logging
import sys
import time
from pathlib import Path

import numpy as np

# 添加config路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from config import (
    KLINE_TABLE_MAP, FRACTAL_TABLE_MAP, INTERVAL_MS,
    get_duckdb_kline_connection, get_duckdb_structure_connection,
    DUCKDB_AVAILABLE
)

logger = logging.getLogger(__name__)


def log(msg):
    logger.info(msg)


def _timer_start():
    """开始计时"""
    return time.time()


def _timer_end(start, label):
    """结束计时并打印"""
    elapsed = time.time() - start
    log(f"[计时] {label}: {elapsed:.3f} 秒")
    return elapsed


class VectorizedBacktestEngine:
    """
    向量化回测引擎（内存计算版）
    特点：
    1. 一次性从 DuckDB 加载全部数据到内存
    2. 回测逻辑和 StreamingBacktestEngine 完全一致
    """

    def __init__(self, config: dict):
        self.config = config
        self.capital = float(config.get("initial_capital", 10000))
        self.peak_equity = self.capital
        self.max_drawdown = 0.0
        self.trades = []
        self.equity_times = []
        self.equity_values = []
        self.open_positions = []

    def run(self, interval: str, start_date: str, end_date: str) -> dict:
        """
        执行回测 - 一次性加载数据，内存中计算
        每个步骤都计时，用于性能分析
        """
        total_start = _timer_start()

        if not DUCKDB_AVAILABLE:
            return {"error": "DuckDB 未安装，无法使用向量化回测"}

        # 1. 参数解析
        t1 = _timer_start()
        # 参数校验：所有参数必须显式传入，不能使用默认值
        required_params = [
            "mode", "stop_loss_pct", "take_profit_pct", "initial_capital",
            "fee_rate", "position_mode", "percent_per_trade", "fixed_amount",
            "max_positions", "use_stop_profit"
        ]
        missing = [p for p in required_params if p not in self.config]
        if missing:
            raise ValueError(f"向量化回测缺少必需参数: {missing}")

        mode = self.config["mode"]
        stop_loss_pct = float(self.config["stop_loss_pct"]) / 100
        take_profit_pct = float(self.config["take_profit_pct"]) / 100
        fee_rate = float(self.config["fee_rate"]) / 100
        position_mode = self.config["position_mode"]
        percent_per_trade = float(self.config["percent_per_trade"])
        fixed_amount = float(self.config["fixed_amount"])
        max_positions = int(self.config["max_positions"])
        use_stop_profit = self.config["use_stop_profit"]
        _timer_end(t1, "参数解析")

        # 2. 一次性加载数据到内存（直接返回 numpy 数组）
        t2 = _timer_start()
        closes, times, trigger_map = self._load_data(interval, start_date, end_date)
        _timer_end(t2, "数据加载（DuckDB）")
        log(f"[向量化回测] 加载了 {len(closes)} 条 K 线，{len(trigger_map)} 个分型信号")

        total_rows = len(closes)
        equity_sample_interval = 1000

        log("=" * 60)
        log(f"[回测] 开始 - 资金={self.capital}")
        log("[回测] 使用事件驱动 + numpy 向量化扫描")
        log("=" * 60)

        # 3. 构建信号数组（numpy searchsorted，纯 C 层，无 Python 循环）
        t3 = _timer_start()
        trigger_times = np.array(sorted(trigger_map.keys()), dtype=np.int64)
        trigger_values = np.array([trigger_map[t] for t in trigger_times], dtype=np.int8)

        # 二分查找信号对应的 K 线索引
        indices = np.searchsorted(times, trigger_times)
        valid = (indices < total_rows) & (times[indices] == trigger_times)
        signals = np.zeros(total_rows, dtype=np.int8)
        signals[indices[valid]] = trigger_values[valid]

        # 找到所有信号索引（numpy C 层操作，瞬时完成）
        signal_indices = np.where(signals != 0)[0]
        _timer_end(t3, "信号数组构建（searchsorted）")

        # 预绑定局部变量，避免属性查找
        positions = self.open_positions
        close_position = self._close_position
        _open_position = self._open_position
        _record_equity = self._record_equity

        # 4. 事件驱动主循环：只遍历信号索引（23万次 vs 70万次）
        current_idx = 0
        processed = 0

        for sig_idx in signal_indices:
            # 记录信号K线之前的资产曲线（采样）
            for eq_idx in range(current_idx, sig_idx, equity_sample_interval):
                _record_equity(closes[eq_idx], times[eq_idx])

            # 止损止盈：numpy 向量化扫描 [current_idx, sig_idx) 区间
            if use_stop_profit and positions:
                self._scan_stop_take(closes, times, current_idx, sig_idx,
                                     fee_rate, close_position)

            # 处理信号
            current_idx = sig_idx
            signal_val = int(signals[sig_idx])
            price = float(closes[sig_idx])
            time_sec = int(times[sig_idx])

            # 内联平仓逻辑
            if signal_val == 1:
                for i, pos in enumerate(positions):
                    if pos["direction"] == 1:
                        close_position(pos, price, time_sec, fee_rate, "顶分型平多")
                        break
            elif signal_val == -1:
                for i, pos in enumerate(positions):
                    if pos["direction"] == -1:
                        close_position(pos, price, time_sec, fee_rate, "底分型平空")
                        break

            # 内联开仓逻辑
            allow_long = (mode in ("both", "long")) and signal_val == -1
            allow_short = (mode in ("both", "short")) and signal_val == 1
            can_open = len(positions) < max_positions

            if allow_long and can_open:
                _open_position(1, price, time_sec, position_mode,
                               percent_per_trade, fixed_amount, fee_rate,
                               stop_loss_pct, take_profit_pct)
            if allow_short and can_open:
                _open_position(-1, price, time_sec, position_mode,
                               percent_per_trade, fixed_amount, fee_rate,
                               stop_loss_pct, take_profit_pct)

            processed += 1
            if processed % 50000 == 0:
                log(f"[回测] 已处理 {processed} 个信号 (K线索引: {sig_idx}/{total_rows})")

        # 处理最后一个信号之后的止损止盈
        if use_stop_profit and positions:
            self._scan_stop_take(closes, times, current_idx, total_rows,
                                 fee_rate, close_position)

        # 记录最后的资产曲线
        for eq_idx in range(current_idx, total_rows, equity_sample_interval):
            _record_equity(closes[eq_idx], times[eq_idx])
        if total_rows > 0:
            _record_equity(closes[-1], times[-1])

        calc_time = _timer_end(t3, "回测计算（事件驱动 + numpy）")

        # 4. 构建结果
        t4 = _timer_start()
        result = self._build_result(total_rows)
        _timer_end(t4, "结果构建")

        _timer_end(total_start, "总耗时")
        log(f"[回测] 完成! 总交易: {len(self.trades)}, K线: {total_rows}")

        return result

    def _load_data(self, interval: str, start_date: str, end_date: str):
        """一次性加载 K 线和分型信号到内存（带详细计时）"""
        import datetime

        table_name = KLINE_TABLE_MAP.get(interval, "kline_1m")
        std_table = FRACTAL_TABLE_MAP.get(interval, "kline_1m_std")
        interval_ms = INTERVAL_MS.get(interval, 60000)
        log(f"[向量化回测] 时间级别={interval}, K线表={table_name}, 分型表={std_table}")

        # 转换日期
        start_ms = None
        end_ms = None
        if start_date:
            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            start_ms = int(dt.timestamp() * 1000)
        if end_date:
            dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
            end_ms = int(dt.timestamp() * 1000)

        # 1. 加载 K 线
        t_kline = _timer_start()
        conn = get_duckdb_kline_connection(read_only=True)

        conditions = ["open_time IS NOT NULL"]
        params = []
        if start_ms:
            conditions.append("open_time >= ?")
            params.append(start_ms)
        if end_ms:
            conditions.append("open_time < ?")
            params.append(end_ms)
        where = " AND ".join(conditions)

        t_query = _timer_start()
        kline_df = conn.execute(f"""
            SELECT open_time, close
            FROM {table_name}
            WHERE {where}
            ORDER BY open_time ASC
        """, params).fetchdf()
        _timer_end(t_query, "  - K线 SQL 查询")

        conn.close()

        t_convert = _timer_start()
        # 直接返回 numpy 数组（C 层连续内存），不经过 list 中转
        closes = kline_df['close'].to_numpy(dtype=np.float64)
        times = kline_df['open_time'].to_numpy(dtype=np.int64) // 1000
        _timer_end(t_convert, "  - K线 numpy 数组转换（零拷贝）")
        _timer_end(t_kline, "K线加载总计")

        # 2. 加载分型信号
        t_fractal = _timer_start()
        conn2 = get_duckdb_structure_connection(read_only=True)

        all_params = (start_ms or 0, end_ms or 9999999999999)

        t_all = _timer_start()
        all_df = conn2.execute(f"""
            SELECT start_time, end_time
            FROM {std_table}
            WHERE start_time >= ? AND start_time < ?
            ORDER BY start_time ASC
        """, all_params).fetchdf()
        _timer_end(t_all, "  - 全部标准K线查询")

        t_frac = _timer_start()
        fractal_df = conn2.execute(f"""
            SELECT start_time, end_time, fractal_label
            FROM {std_table}
            WHERE fractal_label != 0
            AND start_time >= ? AND start_time < ?
            ORDER BY start_time ASC
        """, all_params).fetchdf()
        _timer_end(t_frac, "  - 分型信号查询")

        conn2.close()

        # 构建 trigger_map（用 numpy 向量化）
        t_build = _timer_start()
        # 纯 numpy 向量化构建 trigger_map，无 Python 循环
        all_starts = all_df['start_time'].to_numpy(dtype=np.int64)
        all_ends = all_df['end_time'].to_numpy(dtype=np.int64)

        frac_starts = fractal_df['start_time'].to_numpy(dtype=np.int64)
        frac_ends = fractal_df['end_time'].to_numpy(dtype=np.int64)
        frac_labels = fractal_df['fractal_label'].to_numpy(dtype=np.int64)

        # 用 searchsorted 二分查找分型信号在 all_starts 中的位置
        frac_indices = np.searchsorted(all_starts, frac_starts)
        valid = (frac_indices < len(all_starts)) & (all_starts[frac_indices] == frac_starts)
        has_next = valid & (frac_indices + 1 < len(all_starts))

        # 默认用 frac_ends - interval_ms，有效且有下一行则用 all_ends[idx+1] - interval_ms
        confirm_times = frac_ends - interval_ms
        confirm_times[has_next] = all_ends[frac_indices[has_next] + 1] - interval_ms

        # 一次遍历构建 dict（23万次，但只做 dict 插入，无其他计算）
        trigger_map = {}
        for i in range(len(frac_starts)):
            trigger_map[int(confirm_times[i] // 1000)] = int(frac_labels[i])
        _timer_end(t_build, "  - trigger_map 构建（numpy searchsorted）")
        _timer_end(t_fractal, "分型信号加载总计")

        return closes, times, trigger_map

    # ── 以下方法和 streaming_engine.py 完全一致 ──

    def _scan_stop_take(self, closes, times, start_idx, end_idx, fee_rate, close_position):
        """numpy 向量化扫描止损止盈：在 [start_idx, end_idx) 区间内找第一个触发点"""
        n = end_idx - start_idx
        if n <= 0:
            return

        positions = self.open_positions
        if not positions:
            return

        segment = closes[start_idx:end_idx]

        for i in range(len(positions) - 1, -1, -1):
            pos = positions[i]
            if pos["direction"] == 1:
                stop_mask = segment <= pos["stop_loss"]
                take_mask = segment >= pos["take_profit"]
            else:
                stop_mask = segment >= pos["stop_loss"]
                take_mask = segment <= pos["take_profit"]

            stop_idx = np.argmax(stop_mask) if stop_mask.any() else n
            take_idx = np.argmax(take_mask) if take_mask.any() else n

            first = min(stop_idx, take_idx)
            if first < n:
                is_stop = stop_idx < take_idx
                reason = "止损" if is_stop else "止盈"
                abs_idx = start_idx + first
                close_position(pos, float(closes[abs_idx]), int(times[abs_idx]),
                               fee_rate, reason)

    def _record_equity(self, current_price: float, current_time: int):
        """记录资产曲线"""
        unrealized_pnl = 0
        for pos in self.open_positions:
            if pos["direction"] == 1:
                unrealized_pnl += (current_price - pos["entry_price"]) * pos["amount"]
            else:
                unrealized_pnl += (pos["entry_price"] - current_price) * pos["amount"]

        total_equity = self.capital + unrealized_pnl
        self.equity_times.append(current_time)
        self.equity_values.append(round(total_equity, 2))

        if total_equity > self.peak_equity:
            self.peak_equity = total_equity

        dd = (self.peak_equity - total_equity) / self.peak_equity
        if dd > self.max_drawdown:
            self.max_drawdown = dd

    def _check_stop_profit_loss(self, current_price: float, current_time: int,
                                 fee_rate: float, stop_loss_pct: float,
                                 take_profit_pct: float):
        """检查止损止盈"""
        for pos in list(self.open_positions):
            should_close = False
            reason = ""

            if pos["direction"] == 1:
                if pos["stop_loss"] and current_price <= pos["stop_loss"]:
                    should_close, reason = True, "止损"
                elif pos["take_profit"] and current_price >= pos["take_profit"]:
                    should_close, reason = True, "止盈"
            else:
                if pos["stop_loss"] and current_price >= pos["stop_loss"]:
                    should_close, reason = True, "止损"
                elif pos["take_profit"] and current_price <= pos["take_profit"]:
                    should_close, reason = True, "止盈"

            if should_close:
                self._close_position(pos, current_price, current_time, fee_rate, reason)

    def _close_position(self, pos: dict, current_price: float, current_time: int,
                       fee_rate: float, reason: str):
        """平仓"""
        close_fee = current_price * pos["amount"] * fee_rate
        total_fee = pos["fee"] + close_fee

        if pos["direction"] == 1:
            gross_pnl = (current_price - pos["entry_price"]) * pos["amount"]
        else:
            gross_pnl = (pos["entry_price"] - current_price) * pos["amount"]

        pnl = gross_pnl - total_fee
        self.capital += gross_pnl - close_fee
        pnl_pct = pnl / (pos["entry_price"] * pos["amount"]) * 100

        self.trades.append({
            "direction": "多" if pos["direction"] == 1 else "空",
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(current_price, 2),
            "entry_time": pos["entry_time"],
            "exit_time": current_time,
            "amount": round(pos["amount"], 6),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "fee": round(total_fee, 2),
            "reason": reason,
        })
        self.open_positions.remove(pos)

    def _process_signal(self, signal: int, current_price: float, current_time: int,
                       mode: str, max_positions: int, position_mode: str,
                       percent_per_trade: float, fixed_amount: float,
                       fee_rate: float, stop_loss_pct: float, take_profit_pct: float):
        """处理分型信号"""
        label = signal

        if label == 1:
            for pos in list(self.open_positions):
                if pos["direction"] == 1:
                    self._close_position(pos, current_price, current_time,
                                        fee_rate, "顶分型平多")
                    break

        if label == -1:
            for pos in list(self.open_positions):
                if pos["direction"] == -1:
                    self._close_position(pos, current_price, current_time,
                                        fee_rate, "底分型平空")
                    break

        allow_long = (mode in ("both", "long")) and label == -1
        allow_short = (mode in ("both", "short")) and label == 1
        can_open = len(self.open_positions) < max_positions

        if allow_long and can_open:
            self._open_position(1, current_price, current_time, position_mode,
                              percent_per_trade, fixed_amount, fee_rate,
                              stop_loss_pct, take_profit_pct)

        if allow_short and can_open:
            self._open_position(-1, current_price, current_time, position_mode,
                              percent_per_trade, fixed_amount, fee_rate,
                              stop_loss_pct, take_profit_pct)

    def _open_position(self, direction: int, current_price: float, current_time: int,
                      position_mode: str, percent_per_trade: float,
                      fixed_amount: float, fee_rate: float,
                      stop_loss_pct: float, take_profit_pct: float):
        """开仓"""
        trade_capital = self.capital / max(1, len(self.open_positions) + 1)

        if position_mode == "percent":
            amount = (trade_capital * percent_per_trade / 100) / current_price
        else:
            amount = fixed_amount / current_price

        open_fee = amount * current_price * fee_rate
        self.capital -= open_fee

        if direction == 1:
            stop_loss = current_price * (1 - stop_loss_pct)
            take_profit = current_price * (1 + take_profit_pct)
        else:
            stop_loss = current_price * (1 + stop_loss_pct)
            take_profit = current_price * (1 - take_profit_pct)

        self.open_positions.append({
            "direction": direction,
            "entry_price": current_price,
            "entry_time": current_time,
            "amount": amount,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fee": open_fee,
        })

    def _build_result(self, total_rows: int) -> dict:
        """构建结果（确保所有值为原生 Python 类型，可 JSON 序列化）"""
        total = int(len(self.trades))
        win = int(sum(1 for t in self.trades if float(t["pnl"]) > 0))
        initial = float(self.config.get("initial_capital", 10000))
        total_return = float((self.capital - initial) / initial * 100)

        # 转换 trades 中的 numpy 类型
        clean_trades = []
        for t in self.trades:
            clean_trades.append({
                "direction": str(t["direction"]),  # "多" 或 "空"，保持字符串
                "entry_time": int(t["entry_time"]),
                "entry_price": float(t["entry_price"]),
                "exit_time": int(t["exit_time"]),
                "exit_price": float(t["exit_price"]),
                "amount": float(t["amount"]),
                "pnl": float(t["pnl"]),
                "pnl_pct": float(t["pnl_pct"]),
                "fee": float(t["fee"]),
                "reason": str(t["reason"]),
            })

        return {
            "trades": clean_trades,
            "equity_curve": [
                {"time": int(t), "equity": float(v)}
                for t, v in zip(self.equity_times, self.equity_values)
            ],
            "summary": {
                "initial_capital": float(initial),
                "final_capital": round(float(self.capital), 2),
                "total_trades": int(total),
                "win_trades": int(win),
                "win_rate": round(float(win) / total * 100, 2) if total > 0 else 0.0,
                "total_return": round(total_return, 2),
                "max_drawdown": round(float(self.max_drawdown) * 100, 2),
            },
            "kline_count": int(total_rows),
        }
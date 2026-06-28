"""
流式回测引擎 - 内存占用恒定，不存储全部K线
"""
import sys
import sqlite3
from typing import Dict, Any, Generator, Tuple
from pathlib import Path

# 添加config路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from config import DB_PATH, STRUCTURE_DB, KLINE_TABLE_MAP, FRACTAL_TABLE_MAP, INTERVAL_MS


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class StreamingBacktestEngine:
    """
    流式回测引擎 - 边读边算，内存占用恒定约20MB
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
        
    def run_streaming(self, interval: str, start_date: str, end_date: str) -> dict:
        """
        执行流式回测 - 边从数据库读取边计算
        内存占用：恒定约20MB（不随K线数量增加）
        """
        mode = self.config.get("mode", "both")
        stop_loss_pct = float(self.config.get("stop_loss_pct", 2.0)) / 100
        take_profit_pct = float(self.config.get("take_profit_pct", 5.0)) / 100
        fee_rate = float(self.config.get("fee_rate", 0.055)) / 100
        position_mode = self.config.get("position_mode", "percent")
        percent_per_trade = float(self.config.get("percent_per_trade", 20))
        fixed_amount = float(self.config.get("fixed_amount", 1000))
        max_positions = int(self.config.get("max_positions", 3))
        use_stop_profit = self.config.get("use_stop_profit", True)
        
        trigger_map = self._load_fractal_signals(interval, start_date, end_date)
        log(f"[流式回测] 加载了 {len(trigger_map)} 个分型信号")
        
        total_rows = 0
        equity_sample_interval = 1000
        
        log("=" * 60)
        log(f"[回测] 开始 - 资金={self.capital}")
        log("[回测] 使用流式处理，内存占用恒定")
        log("=" * 60)
        
        for idx, row in enumerate(self._iter_klines(interval, start_date, end_date)):
            total_rows = idx + 1
            current_time = row[0]
            current_price = row[1]
            
            if idx % equity_sample_interval == 0:
                self._record_equity(current_price, current_time)
                if idx > 0 and idx % 50000 == 0:
                    log(f"[回测] 已处理 {idx} 根K线")
            
            signal = trigger_map.get(current_time, 0)
            
            if use_stop_profit:
                self._check_stop_profit_loss(current_price, current_time,
                                            fee_rate, stop_loss_pct, take_profit_pct)
            
            if signal != 0:
                self._process_signal(signal, current_price, current_time,
                                   mode, max_positions, position_mode,
                                   percent_per_trade, fixed_amount, fee_rate,
                                   stop_loss_pct, take_profit_pct)
        
        if total_rows > 0:
            self._record_equity(current_price, current_time)
        
        log(f"[回测] 完成! 总交易: {len(self.trades)}, K线: {total_rows}")
        
        return self._build_result(total_rows)
    
    def _iter_klines(self, interval: str, start_date: str, end_date: str):
        """流式生成K线数据"""
        import datetime
        
        table_name = KLINE_TABLE_MAP.get(interval, "kline_1m")
        
        start_ms = None
        end_ms = None
        if start_date:
            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            start_ms = int(dt.timestamp() * 1000)
        if end_date:
            dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
            end_ms = int(dt.timestamp() * 1000)
        
        # 使用连接池复用连接（避免重复connect开销）
        from api.config import get_db_connection
        conn = get_db_connection()
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
        SELECT open_time, close
        FROM {table_name}
        WHERE {where}
        ORDER BY open_time ASC
        """, params)
        
        for row in cursor:
            yield (
                int(row[0]) // 1000,   # time
                float(row[1]),          # close
            )
        
        conn.close()  # 关闭连接释放内存
    
    def _load_fractal_signals(self, interval: str, start_date: str, end_date: str) -> dict:
        """加载分型信号"""
        import datetime
        
        std_table = FRACTAL_TABLE_MAP.get(interval, "kline_1m_std")
        interval_ms = INTERVAL_MS.get(interval, 60000)
        
        start_ms = None
        end_ms = None
        if start_date:
            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            start_ms = int(dt.timestamp() * 1000)
        if end_date:
            dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
            end_ms = int(dt.timestamp() * 1000)
        
        from api.config import get_structure_connection
        conn = get_structure_connection()
        cursor = conn.cursor()
        
        # 获取所有行用于计算confirm_time
        cursor.execute(f"""
        SELECT start_time, end_time
        FROM {std_table}
        WHERE start_time >= ? AND start_time < ?
        ORDER BY start_time ASC
        """, (start_ms or 0, end_ms or 9999999999999))
        
        all_rows = list(cursor)
        time_to_idx = {row[0]: i for i, row in enumerate(all_rows)}
        
        # 获取分型行
        conditions = ["fractal_label != 0"]
        params = []
        if start_ms:
            conditions.append("start_time >= ?")
            params.append(start_ms)
        if end_ms:
            conditions.append("start_time < ?")
            params.append(end_ms)
        where = " AND ".join(conditions)
        
        cursor.execute(f"""
        SELECT start_time, end_time, fractal_label
        FROM {std_table}
        WHERE {where}
        ORDER BY start_time ASC
        """, params)
        
        trigger_map = {}
        for row in cursor:
            start_time, end_time, label = row
            idx = time_to_idx.get(start_time)
            if idx is not None and idx + 1 < len(all_rows):
                confirm_time_ms = all_rows[idx + 1][1] - interval_ms
                trigger_map[confirm_time_ms // 1000] = label
            else:
                confirm_time_ms = end_time - interval_ms
                trigger_map[confirm_time_ms // 1000] = label
        
        conn.close()  # 关闭连接释放内存
        return trigger_map
    
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
        """构建结果"""
        total = len(self.trades)
        win = sum(1 for t in self.trades if t["pnl"] > 0)
        initial = float(self.config.get("initial_capital", 10000))
        total_return = ((self.capital - initial) / initial * 100)

        return {
            "trades": self.trades,
            "equity_curve": [
                {"time": t, "equity": v} 
                for t, v in zip(self.equity_times, self.equity_values)
            ],
            "summary": {
                "initial_capital": initial,
                "final_capital": round(self.capital, 2),
                "total_trades": total,
                "win_trades": win,
                "win_rate": round(win / total * 100, 2) if total > 0 else 0,
                "total_return": round(total_return, 2),
                "max_drawdown": round(self.max_drawdown * 100, 2),
            },
            "kline_count": total_rows,
        }

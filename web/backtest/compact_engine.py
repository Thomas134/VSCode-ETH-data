"""
内存优化的回测引擎 - 使用 __slots__ 减少内存占用
"""
import sys
from typing import List, Dict, Any, Optional

# 紧凑的K线记录 - 相比字典可节省70%内存
class KlineRecord:
    __slots__ = ['time', 'open', 'high', 'low', 'close', 'volume', 'signal']
    
    def __init__(self, time: int, open_p: float, high: float, low: float, 
                 close: float, volume: float, signal: int = 0):
        self.time = int(time)
        self.open = float(open_p)
        self.high = float(high)
        self.low = float(low)
        self.close = float(close)
        self.volume = float(volume)
        self.signal = int(signal)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'KlineRecord':
        return cls(
            d['time'], d['open'], d['high'],
            d['low'], d['close'], d['volume'], d.get('signal', 0)
        )
    
    def to_dict(self) -> Dict:
        return {
            'time': self.time,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'signal': self.signal
        }


# 紧凑的交易记录
class TradeRecord:
    __slots__ = ['direction', 'entry_price', 'exit_price', 'entry_time',
                 'exit_time', 'amount', 'pnl', 'pnl_pct', 'fee', 'reason']
    
    def __init__(self, direction: str, entry_price: float, exit_price: float,
                 entry_time: int, exit_time: int, amount: float, 
                 pnl: float, pnl_pct: float, fee: float, reason: str):
        self.direction = direction
        self.entry_price = round(entry_price, 2)
        self.exit_price = round(exit_price, 2)
        self.entry_time = int(entry_time)
        self.exit_time = int(exit_time)
        self.amount = round(amount, 6)
        self.pnl = round(pnl, 2)
        self.pnl_pct = round(pnl_pct, 2)
        self.fee = round(fee, 2)
        self.reason = reason
    
    def to_dict(self) -> Dict:
        return {
            'direction': self.direction,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'entry_time': self.entry_time,
            'exit_time': self.exit_time,
            'amount': self.amount,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'fee': self.fee,
            'reason': self.reason
        }


class CompactBacktestEngine:
    """内存优化的回测引擎"""
    
    def __init__(self, config: dict):
        self.config = config
        self.capital = float(config.get("initial_capital", 10000))
        self.peak_equity = self.capital
        self.max_drawdown = 0.0
        self.trades: List[TradeRecord] = []
        self.equity_times: List[int] = []      # 用两个列表代替字典列表
        self.equity_values: List[float] = []   # 节省内存
        self.open_positions: List[dict] = []
        
        # 转换K线数据为紧凑格式
        kline_dicts = config.get("kline_data", [])
        if kline_dicts and isinstance(kline_dicts[0], dict):
            self.kline_data = [KlineRecord.from_dict(d) for d in kline_dicts]
        else:
            self.kline_data = kline_dicts  # 已经是KlineRecord
    
    def run(self) -> dict:
        """执行回测"""
        total_rows = len(self.kline_data)
        
        if total_rows < 10:
            return {"error": f"K线数据不足 ({total_rows} 根)"}

        # 参数
        mode = self.config.get("mode", "both")
        stop_loss_pct = float(self.config.get("stop_loss_pct", 2.0)) / 100
        take_profit_pct = float(self.config.get("take_profit_pct", 5.0)) / 100
        fee_rate = float(self.config.get("fee_rate", 0.055)) / 100
        position_mode = self.config.get("position_mode", "percent")
        percent_per_trade = float(self.config.get("percent_per_trade", 20))
        fixed_amount = float(self.config.get("fixed_amount", 1000))
        max_positions = int(self.config.get("max_positions", 3))
        use_stop_profit = self.config.get("use_stop_profit", True)

        # 资产曲线采样：从2000点减少到500点（减少75%内存）
        equity_sample_interval = max(1, total_rows // 500)

        for idx, row in enumerate(self.kline_data):
            current_price = row.close  # 属性访问比字典快
            current_time = row.time

            # 采样记录资产曲线
            if idx % equity_sample_interval == 0 or idx == total_rows - 1:
                self._record_equity(current_price, current_time)

            # 止损止盈检查
            if use_stop_profit:
                self._check_stop_profit_loss(current_price, current_time, 
                                            fee_rate, stop_loss_pct, take_profit_pct)

            # 分型信号处理
            if row.signal != 0:
                self._process_signal(row.signal, current_price, current_time,
                                   mode, max_positions, position_mode,
                                   percent_per_trade, fixed_amount, fee_rate,
                                   stop_loss_pct, take_profit_pct)

        return self._build_result(total_rows)
    
    def _record_equity(self, current_price: float, current_time: int):
        """记录资产曲线 - 使用并行列表"""
        unrealized_pnl = 0
        for pos in self.open_positions:
            if pos["direction"] == 1:
                unrealized_pnl += (current_price - pos["entry_price"]) * pos["amount"]
            else:
                unrealized_pnl += (pos["entry_price"] - current_price) * pos["amount"]
        
        total_equity = self.capital + unrealized_pnl
        
        # 用列表存储，节省内存
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

            if pos["direction"] == 1:  # 多头
                if pos["stop_loss"] and current_price <= pos["stop_loss"]:
                    should_close, reason = True, "止损"
                elif pos["take_profit"] and current_price >= pos["take_profit"]:
                    should_close, reason = True, "止盈"
            else:  # 空头
                if pos["stop_loss"] and current_price >= pos["stop_loss"]:
                    should_close, reason = True, "止损"
                elif pos["take_profit"] and current_price <= pos["take_profit"]:
                    should_close, reason = True, "止盈"

            if should_close:
                self._close_position(pos, current_price, current_time, fee_rate, reason)
    
    def _close_position(self, pos: dict, current_price: float, current_time: int,
                       fee_rate: float, reason: str):
        """平仓 - 使用TradeRecord"""
        close_fee = current_price * pos["amount"] * fee_rate
        total_fee = pos["fee"] + close_fee

        if pos["direction"] == 1:
            gross_pnl = (current_price - pos["entry_price"]) * pos["amount"]
        else:
            gross_pnl = (pos["entry_price"] - current_price) * pos["amount"]

        pnl = gross_pnl - total_fee
        self.capital += gross_pnl - close_fee
        pnl_pct = pnl / (pos["entry_price"] * pos["amount"]) * 100

        # 使用TradeRecord代替字典
        trade = TradeRecord(
            direction="多" if pos["direction"] == 1 else "空",
            entry_price=pos["entry_price"],
            exit_price=current_price,
            entry_time=pos["entry_time"],
            exit_time=current_time,
            amount=pos["amount"],
            pnl=pnl,
            pnl_pct=pnl_pct,
            fee=total_fee,
            reason=reason
        )
        self.trades.append(trade)
        self.open_positions.remove(pos)
    
    def _process_signal(self, signal: int, current_price: float, current_time: int,
                       mode: str, max_positions: int, position_mode: str,
                       percent_per_trade: float, fixed_amount: float,
                       fee_rate: float, stop_loss_pct: float, take_profit_pct: float):
        """处理分型信号"""
        label = signal
        
        # 平仓逻辑
        if label == 1:  # 顶分型平多
            for pos in list(self.open_positions):
                if pos["direction"] == 1:
                    self._close_position(pos, current_price, current_time, 
                                        fee_rate, "顶分型平多")
                    break
        
        if label == -1:  # 底分型平空
            for pos in list(self.open_positions):
                if pos["direction"] == -1:
                    self._close_position(pos, current_price, current_time,
                                        fee_rate, "底分型平空")
                    break
        
        # 开仓逻辑
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
        win = sum(1 for t in self.trades if t.pnl > 0)
        initial = float(self.config.get("initial_capital", 10000))
        total_return = ((self.capital - initial) / initial * 100)

        # 转换回字典格式
        return {
            "trades": [t.to_dict() for t in self.trades],
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

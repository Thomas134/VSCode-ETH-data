# backtest/engine.py
"""
全量回测引擎 - 接收已带分型信号的K线数据，逐K线回测
不再独立读取数据库（由API层预先匹配好分型信号）
"""
import json
import sys


# ── 日志辅助：输出到 stderr，不污染 stdout ──
def _log(*args, **kwargs):
    """将日志打印到 stderr（不会污染 stdout），stdout 只保留最终 JSON"""
    print(*args, **kwargs, file=sys.stderr, flush=True)


class BacktestEngine:
    """回测引擎 - 逐K线遍历 + 资金管理"""

    def __init__(self, config: dict):
        self.config = config

        # 回测状态
        self.capital = float(config.get("initial_capital", 10000))
        self.peak_equity = self.capital
        self.max_drawdown = 0.0
        self.trades = []
        self.equity_curve = []
        self.open_positions = []

    def run(self) -> dict:
        """执行回测，返回结果字典"""
        # 1. 读取已带分型信号的K线数据（由API层传入）
        kline_rows = self.config.get("kline_data", [])
        total_rows = len(kline_rows)
        _log("=" * 60)
        _log(f"[回测] 开始 - 资金={self.capital}")
        _log(f"[回测] 日期范围: {self.config.get('start_date','最早')} ~ {self.config.get('end_date','最新')}")
        _log(f"[回测] 加载K线: {total_rows} 根")
        _log("=" * 60)

        if total_rows < 10:
            return {"error": f"K线数据不足 ({total_rows} 根)"}

        # 2. 回测参数
        mode = self.config.get("mode", "both")
        stop_loss_pct = float(self.config.get("stop_loss_pct", 2.0)) / 100
        take_profit_pct = float(self.config.get("take_profit_pct", 5.0)) / 100
        fee_rate = float(self.config.get("fee_rate", 0.055)) / 100
        position_mode = self.config.get("position_mode", "percent")
        percent_per_trade = float(self.config.get("percent_per_trade", 20))
        fixed_amount = float(self.config.get("fixed_amount", 1000))
        max_positions = int(self.config.get("max_positions", 3))
        use_stop_profit = self.config.get("use_stop_profit", True)  # 止盈止损开关

        _log(f"[回测] 止盈止损: {'开启' if use_stop_profit else '关闭'}")

        # 资产曲线采样间隔：最多采2000个点
        equity_sample_interval = max(1, total_rows // 2000)

        # 3. 逐K线遍历
        for idx, row in enumerate(kline_rows):
            current_price = row["close"]
            current_time = row["time"]

            # 进度提示
            if total_rows > 100000 and idx % max(1, total_rows // 20) == 0:
                pct = idx / total_rows * 100
                _log(f"[回测] 进度: {pct:.0f}% ({idx}/{total_rows})")

            # ---- 记录资产曲线 ----
            if idx % equity_sample_interval == 0 or idx == total_rows - 1:
                unrealized_pnl = 0
                for pos in self.open_positions:
                    if pos["direction"] == 1:
                        unrealized_pnl += (current_price - pos["entry_price"]) * pos["amount"]
                    else:
                        unrealized_pnl += (pos["entry_price"] - current_price) * pos["amount"]
                total_equity = self.capital + unrealized_pnl
                self.equity_curve.append({"time": current_time, "equity": round(total_equity, 2)})

                # 更新最大回撤
                if total_equity > self.peak_equity:
                    self.peak_equity = total_equity
                dd = (self.peak_equity - total_equity) / self.peak_equity
                if dd > self.max_drawdown:
                    self.max_drawdown = dd

            # ---- 止损止盈检查（use_stop_profit为True时才触发）----
            if use_stop_profit:
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
                        # 开仓费已在开仓时从 capital 扣除
                        close_fee = current_price * pos["amount"] * fee_rate
                        total_fee = pos["fee"] + close_fee

                        if pos["direction"] == 1:
                            gross_pnl = (current_price - pos["entry_price"]) * pos["amount"]
                        else:
                            gross_pnl = (pos["entry_price"] - current_price) * pos["amount"]

                        pnl = gross_pnl - total_fee          # 净盈亏（用于记录到交易）
                        self.capital += gross_pnl - close_fee  # 加回资金（开仓已扣过）
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

            # ---- 分型信号检查：先平仓再开仓（一对一）----
            signal = row.get("signal", 0)
            if signal != 0:
                label = signal  # -1 = 底分型, +1 = 顶分型

                # ── 顶分型 → 平一个多仓 ──
                if label == 1:
                    for pos in list(self.open_positions):
                        if pos["direction"] != 1:
                            continue
                        close_fee = current_price * pos["amount"] * fee_rate
                        total_fee = pos["fee"] + close_fee
                        gross_pnl = (current_price - pos["entry_price"]) * pos["amount"]
                        pnl = gross_pnl - total_fee
                        self.capital += gross_pnl - close_fee
                        pnl_pct = pnl / (pos["entry_price"] * pos["amount"]) * 100
                        self.trades.append({
                            "direction": "多",
                            "entry_price": round(pos["entry_price"], 2),
                            "exit_price": round(current_price, 2),
                            "entry_time": pos["entry_time"],
                            "exit_time": current_time,
                            "amount": round(pos["amount"], 6),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "fee": round(total_fee, 2),
                            "reason": "顶分型平多",
                        })
                        self.open_positions.remove(pos)
                        break

                # ── 底分型 → 平一个空仓 ──
                if label == -1:
                    for pos in list(self.open_positions):
                        if pos["direction"] != -1:
                            continue
                        close_fee = current_price * pos["amount"] * fee_rate
                        total_fee = pos["fee"] + close_fee
                        gross_pnl = (pos["entry_price"] - current_price) * pos["amount"]
                        pnl = gross_pnl - total_fee
                        self.capital += gross_pnl - close_fee
                        pnl_pct = pnl / (pos["entry_price"] * pos["amount"]) * 100
                        self.trades.append({
                            "direction": "空",
                            "entry_price": round(pos["entry_price"], 2),
                            "exit_price": round(current_price, 2),
                            "entry_time": pos["entry_time"],
                            "exit_time": current_time,
                            "amount": round(pos["amount"], 6),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "fee": round(total_fee, 2),
                            "reason": "底分型平空",
                        })
                        self.open_positions.remove(pos)
                        break

                # ── 开仓逻辑 ──
                allow_long = (mode in ("both", "long")) and label == -1
                allow_short = (mode in ("both", "short")) and label == 1
                can_open = len(self.open_positions) < max_positions

                if allow_long and can_open:
                    entry_price = current_price
                    trade_capital = self.capital / max(1, len(self.open_positions) + 1)
                    if position_mode == "percent":
                        amount = (trade_capital * percent_per_trade / 100) / entry_price
                    else:
                        amount = fixed_amount / entry_price

                    open_fee = amount * entry_price * fee_rate
                    self.capital -= open_fee  # 开仓时立即扣除开仓费
                    self.open_positions.append({
                        "direction": 1,
                        "entry_price": entry_price,
                        "entry_time": current_time,
                        "amount": amount,
                        "stop_loss": entry_price * (1 - stop_loss_pct),
                        "take_profit": entry_price * (1 + take_profit_pct),
                        "fee": open_fee,
                    })

                if allow_short and can_open:
                    entry_price = current_price
                    trade_capital = self.capital / max(1, len(self.open_positions) + 1)
                    if position_mode == "percent":
                        amount = (trade_capital * percent_per_trade / 100) / entry_price
                    else:
                        amount = fixed_amount / entry_price

                    open_fee = amount * entry_price * fee_rate
                    self.capital -= open_fee  # 开仓时立即扣除开仓费
                    self.open_positions.append({
                        "direction": -1,
                        "entry_price": entry_price,
                        "entry_time": current_time,
                        "amount": amount,
                        "stop_loss": entry_price * (1 + stop_loss_pct),
                        "take_profit": entry_price * (1 - take_profit_pct),
                        "fee": open_fee,
                    })

        # ---- 回测结束：未平仓的持仓直接丢弃，不强制平仓 ----

        # ---- 统计汇总 ----
        total = len(self.trades)
        win = sum(1 for t in self.trades if t["pnl"] > 0)
        total_return = ((self.capital - float(self.config.get("initial_capital", 10000))) / float(self.config.get("initial_capital", 10000)) * 100)

        if total > 0:
            _log(f"[回测] 完成! 总交易: {total}, 胜率: {win/total*100:.1f}% 收益: {total_return:+.2f}%")
        else:
            _log(f"[回测] 完成! 无交易, 最终资金: {self.capital:.2f}")

        return {
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "summary": {
                "initial_capital": float(self.config.get("initial_capital", 10000)),
                "final_capital": round(self.capital, 2),
                "total_trades": total,
                "win_trades": win,
                "win_rate": round(win / total * 100, 2) if total > 0 else 0,
                "total_return": round(total_return, 2),
                "max_drawdown": round(self.max_drawdown * 100, 2),
            },
            "kline_count": total_rows,
        }

# backtest/run.py
"""回测CLI入口 - 被Flask subprocess调用"""
import sys
import json
from engine import BacktestEngine

if __name__ == "__main__":
    # 读取JSON参数（从stdin传入）
    config = json.loads(sys.stdin.read())

    engine = BacktestEngine(config)
    result = engine.run()

    # stdout输出JSON（Flask读取）
    print(json.dumps(result, ensure_ascii=False))

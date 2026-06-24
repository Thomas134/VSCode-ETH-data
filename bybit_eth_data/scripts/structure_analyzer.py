# structure_analyzer.py
# 标准化K线算法模块 - 纯函数，不依赖数据库和文件路径
#
# 本模块包含禅分型理论的 K线包含关系处理和顶底分型识别算法。
# 所有函数均为纯函数：输入K线列表 → 输出处理结果，无副作用。
#
# 可独立运行测试，也可被 structure_engine.py 或其他模块调用。

import numpy as np


def is_containing(k1, k2):
    """
    判断两根K线是否存在包含关系。

    包含关系: 一根K线的高低点完全包含另一根。

    参数:
        k1: 第一根K线，需包含 'high' 和 'low' 键
        k2: 第二根K线，需包含 'high' 和 'low' 键

    返回:
        (是否包含, 被包含的K线索引)
        - (True, 1): k1 包含 k2
        - (True, 0): k2 包含 k1
        - (False, None): 无包含关系
    """
    # k1 包含 k2
    if k1['high'] >= k2['high'] and k1['low'] <= k2['low']:
        return True, 1
    # k2 包含 k1
    if k2['high'] >= k1['high'] and k2['low'] <= k1['low']:
        return True, 0
    return False, None


def merge_klines(k1, k2, direction):
    """
    合并两根有包含关系的K线。

    方向规则:
        - direction >= 0 (上涨或未定): 取 "高高低低"（高点取更高、低点取更高）
        - direction < 0  (下跌): 取 "低低高高"（高点取更低、低点取更低）

    参数:
        k1: 第一根K线 (较旧的)
        k2: 第二根K线 (较新的)
        direction: 趋势方向，1=上涨，-1=下跌，0=未定

    返回:
        合并后的K线字典，包含 start_time, end_time, open, high, low, close, volume, source_count
    """
    if direction >= 0:  # 上涨或未定，取高高低低
        merged = {
            'start_time': k1['start_time'],
            'end_time': k2['end_time'],
            'open': k1['open'],
            'high': max(k1['high'], k2['high']),
            'low': max(k1['low'], k2['low']),
            'close': k2['close'],
            'volume': k1['volume'] + k2['volume'],
            'source_count': k1.get('source_count', 1) + k2.get('source_count', 1),
        }
    else:  # 下跌，取低低高高
        merged = {
            'start_time': k1['start_time'],
            'end_time': k2['end_time'],
            'open': k1['open'],
            'high': min(k1['high'], k2['high']),
            'low': min(k1['low'], k2['low']),
            'close': k2['close'],
            'volume': k1['volume'] + k2['volume'],
            'source_count': k1.get('source_count', 1) + k2.get('source_count', 1),
        }
    return merged


def get_direction(k1, k2):
    """
    根据两根无包含关系的K线判断趋势方向。

    规则:
        - K2的高点 > K1的高点 且 K2的低点 > K1的低点 → 上涨 (1)
        - K2的高点 < K1的高点 且 K2的低点 < K1的低点 → 下跌 (-1)
        - 其他情况 → 横盘 (0)

    参数:
        k1: 第一根K线 (较旧的)
        k2: 第二根K线 (较新的)

    返回:
        1=上涨, -1=下跌, 0=横盘
    """
    if k2['high'] > k1['high'] and k2['low'] > k1['low']:
        return 1  # 上涨
    elif k2['high'] < k1['high'] and k2['low'] < k1['low']:
        return -1  # 下跌
    else:
        return 0  # 横盘


def process_containing_relationship(klines):
    """
    处理K线包含关系 - 连续合并直到无法继续。

    算法: O(n) 时间复杂度
        - 从左到右遍历
        - 检测到包含关系时，持续向右合并直到无法继续
        - 合并后回溯检查与前一个结果K线是否产生新的包含关系
        - 趋势方向只在无包含关系时更新

    参数:
        klines: 原始K线列表，按时间升序排列。
                每根K线需包含: start_time, end_time, open, high, low, close, volume

    返回:
        处理后的标准化K线列表，每根K线额外包含:
        - source_count: 合并的原始K线数量
        - direction: 相对于前一根标准K线的趋势方向
    """
    if len(klines) < 2:
        result = []
        for k in klines:
            item = dict(k)
            item['source_count'] = 1
            item['direction'] = 0
            result.append(item)
        return result

    result = []
    direction = 0  # 初始方向未定

    for i in range(len(klines)):
        # 初始化当前K线
        current = dict(klines[i])
        current['source_count'] = 1

        # 回溯合并：检查与result最后一个K线是否有包含关系
        while len(result) > 0:
            last = result[-1]
            has_containing, _ = is_containing(last, current)

            if has_containing:
                # 存在包含关系，弹出最后一个，合并
                result.pop()
                # 使用合并前的方向
                prev_direction = last.get('direction', 0)
                current = merge_klines(last, current, prev_direction)
            else:
                # 无包含关系，停止回溯
                break

        # 更新趋势方向（基于result倒数第一和当前K线）
        if len(result) >= 1:
            direction = get_direction(result[-1], current)

        # 保存当前K线
        current['direction'] = direction
        result.append(current)

    return result


def identify_fractals(std_klines):
    """
    识别标准化K线序列中的顶底分型（numpy向量化版本）。

    顶分型: 连续3根K线，中间K线的高点是三者中最高的，且中间K线的低点也是三者中最高的。
            即 K2.high > K1.high 且 K2.high > K3.high
               K2.low  > K1.low  且 K2.low  > K3.low

    底分型: 连续3根K线，中间K线的低点是三者中最低的，且中间K线的高点也是三者中最低的。
            即 K2.low  < K1.low  且 K2.low  < K3.low
               K2.high < K1.high 且 K2.high < K3.high

    参数:
        std_klines: 已处理包含关系的标准化K线列表（按时间升序）

    返回:
        与 std_klines 等长的标记数组:
        - +1 = 顶分型
        - -1 = 底分型
        -  0 = 非分型
    """
    n = len(std_klines)
    if n < 3:
        return [0] * n

    # 一次性提取 high/low 到 numpy 数组
    highs = np.array([k['high'] for k in std_klines], dtype=np.float64)
    lows = np.array([k['low'] for k in std_klines], dtype=np.float64)

    labels = np.zeros(n, dtype=np.int8)

    # 顶分型: 中间高点 > 左边 且 > 右边，中间低点 > 左边 且 > 右边
    top_high = (highs[1:-1] > highs[:-2]) & (highs[1:-1] > highs[2:])
    top_low = (lows[1:-1] > lows[:-2]) & (lows[1:-1] > lows[2:])
    labels[1:-1][top_high & top_low] = 1

    # 底分型: 中间低点 < 左边 且 < 右边，中间高点 < 左边 且 < 右边
    bottom_low = (lows[1:-1] < lows[:-2]) & (lows[1:-1] < lows[2:])
    bottom_high = (highs[1:-1] < highs[:-2]) & (highs[1:-1] < highs[2:])
    labels[1:-1][bottom_low & bottom_high] = -1

    return labels.tolist()

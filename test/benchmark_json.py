#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 性能测试 - 最小可用版本
对比标准库 json vs orjson（可选）

运行方式:
    python test/benchmark_json.py
    python test/benchmark_json.py --size 5000
    python test/benchmark_json.py --iterations 100

安装 orjson 后再次运行查看对比:
    pip install orjson
    python test/benchmark_json.py
"""

import json
import time
import random
import sys
import argparse
from typing import List, Dict, Any, Optional

# 尝试导入 orjson，没有也不报错
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False
    orjson = None


def generate_kline_data(count: int) -> List[Dict[str, Any]]:
    """生成真实的K线数据"""
    base_time = 1704067200000  # 2024-01-01 00:00:00 UTC (毫秒)
    data = []
    price = 2000.0
    
    for i in range(count):
        # 模拟价格波动
        change = random.uniform(-10, 10)
        price += change
        
        open_p = price + random.uniform(-5, 5)
        high = max(open_p, price) + random.uniform(0, 5)
        low = min(open_p, price) - random.uniform(0, 5)
        close = price
        
        data.append({
            "time": (base_time + i * 60000) // 1000,  # 转秒级时间戳
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(random.uniform(100, 10000), 4),
        })
    
    return data


class JsonBenchmark:
    """JSON性能测试器"""
    
    def __init__(self, iterations: int = 50):
        self.iterations = iterations
        self.results = []
        
    def test_stdlib_json(self, data: List[Dict]) -> Dict[str, float]:
        """测试标准库 json"""
        # 预生成JSON字符串用于反序列化测试
        json_str = json.dumps(data)
        json_bytes = json_str.encode('utf-8')
        
        # 序列化测试
        start = time.perf_counter()
        for _ in range(self.iterations):
            result = json.dumps(data)
        serialize_time = (time.perf_counter() - start) * 1000  # 转毫秒
        
        # 反序列化测试
        start = time.perf_counter()
        for _ in range(self.iterations):
            result = json.loads(json_str)
        deserialize_time = (time.perf_counter() - start) * 1000
        
        return {
            "name": "json (标准库)",
            "serialize_ms": serialize_time / self.iterations,
            "deserialize_ms": deserialize_time / self.iterations,
            "total_ms": (serialize_time + deserialize_time) / self.iterations,
            "size_bytes": len(json_bytes),
            "available": True
        }
    
    def test_orjson(self, data: List[Dict]) -> Optional[Dict[str, float]]:
        """测试 orjson"""
        if not HAS_ORJSON:
            return None
            
        # 预生成
        json_bytes = orjson.dumps(data)
        json_str = json_bytes.decode('utf-8')
        
        # 序列化测试（orjson输出bytes）
        start = time.perf_counter()
        for _ in range(self.iterations):
            result = orjson.dumps(data)
        serialize_time = (time.perf_counter() - start) * 1000
        
        # 反序列化测试
        start = time.perf_counter()
        for _ in range(self.iterations):
            result = orjson.loads(json_bytes)
        deserialize_time = (time.perf_counter() - start) * 1000
        
        return {
            "name": "orjson (Rust)",
            "serialize_ms": serialize_time / self.iterations,
            "deserialize_ms": deserialize_time / self.iterations,
            "total_ms": (serialize_time + deserialize_time) / self.iterations,
            "size_bytes": len(json_bytes),
            "available": True
        }
    
    def run(self, data_sizes: List[int]) -> None:
        """运行完整测试"""
        print("=" * 70)
        print("🚀 JSON 性能测试 - 最小可用版本")
        print("=" * 70)
        print(f"测试次数: {self.iterations} 次取平均")
        print(f"可用库: json (内置)" + (", orjson ✅" if HAS_ORJSON else ", orjson ❌ (pip install orjson)"))
        print("=" * 70)
        
        for size in data_sizes:
            print(f"\n📊 测试数据: {size} 条K线")
            print("-" * 70)
            
            # 生成数据
            data = generate_kline_data(size)
            
            # 测试标准库
            result_std = self.test_stdlib_json(data)
            self.print_result(result_std)
            
            # 测试 orjson
            result_or = self.test_orjson(data)
            if result_or:
                self.print_result(result_or)
                self.print_comparison(result_std, result_or)
            else:
                print("\n⚠️  安装 orjson 后可以看到性能对比")
                print("   运行: pip install orjson")
            
            self.results.append({
                "size": size,
                "stdlib": result_std,
                "orjson": result_or
            })
        
        self.print_summary()
    
    def print_result(self, result: Dict[str, float]) -> None:
        """打印单次结果"""
        print(f"\n  {result['name']}:")
        print(f"    序列化:   {result['serialize_ms']:>8.3f} ms")
        print(f"    反序列化: {result['deserialize_ms']:>8.3f} ms")
        print(f"    总时间:   {result['total_ms']:>8.3f} ms")
        print(f"    结果大小: {result['size_bytes']:>8,} bytes ({result['size_bytes']/1024:.1f} KB)")
    
    def print_comparison(self, std: Dict[str, float], opt: Dict[str, float]) -> None:
        """打印对比"""
        speedup = std['total_ms'] / opt['total_ms']
        print(f"\n  ⚡ 性能对比:")
        print(f"    orjson 比标准库快: {speedup:.1f}x")
        print(f"    序列化提升: {(std['serialize_ms']/opt['serialize_ms']):.1f}x")
        print(f"    反序列化提升: {(std['deserialize_ms']/opt['deserialize_ms']):.1f}x")
        
        # 性能评级
        if speedup > 10:
            rating = "🚀 极致提升"
        elif speedup > 5:
            rating = "✨ 显著提升"
        elif speedup > 2:
            rating = "👍 良好提升"
        else:
            rating = "😐 轻微提升"
        print(f"    评级: {rating}")
    
    def print_summary(self) -> None:
        """打印汇总表格"""
        print("\n" + "=" * 70)
        print("📋 汇总表格")
        print("=" * 70)
        
        # 表头
        header = f"{'数据量':>10} | {'库':>15} | {'序列化(ms)':>12} | {'反序列化(ms)':>14} | {'总时间(ms)':>12} | {'提升':>8}"
        print(header)
        print("-" * len(header))
        
        # 数据行
        for r in self.results:
            size = r['size']
            std = r['stdlib']
            
            # 标准库行
            print(f"{size:>10,} | {std['name']:>15} | {std['serialize_ms']:>12.3f} | "
                  f"{std['deserialize_ms']:>14.3f} | {std['total_ms']:>12.3f} | {'基准':>8}")
            
            # orjson行
            if r['orjson']:
                opt = r['orjson']
                speedup = std['total_ms'] / opt['total_ms']
                print(f"{'':>10} | {opt['name']:>15} | {opt['serialize_ms']:>12.3f} | "
                      f"{opt['deserialize_ms']:>14.3f} | {opt['total_ms']:>12.3f} | "
                      f"{speedup:>7.1f}x")
        
        print("=" * 70)
        
        # 安装建议
        if not HAS_ORJSON:
            print("\n💡 提示: 安装 orjson 可获得显著性能提升")
            print("   pip install orjson")
        else:
            print("\n✅ orjson 已安装，建议在项目中使用")


def main():
    parser = argparse.ArgumentParser(description='JSON性能测试')
    parser.add_argument('--size', type=int, default=None, help='单条测试的数据量')
    parser.add_argument('--iterations', type=int, default=50, help='测试迭代次数')
    args = parser.parse_args()
    
    benchmark = JsonBenchmark(iterations=args.iterations)
    
    if args.size:
        # 单条测试
        benchmark.run([args.size])
    else:
        # 默认测试多种规模
        benchmark.run([500, 2000, 10000])


if __name__ == "__main__":
    main()

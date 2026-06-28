#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线API高并发压测脚本 - 固定参数版 (带内存监控)
测试端点: /api/kline
"""
import asyncio
import aiohttp
import time
import statistics
import argparse
import threading
from datetime import datetime

# ==================== 配置区域 ====================
BASE_URL = "http://localhost:8080"
CONCURRENT_USERS = 500
REQUESTS_PER_USER = 1
MAX_CONCURRENT_REQUESTS = 1000
WAIT_MIN = 0.0
WAIT_MAX = 0.1
KLINE_PARAMS = {"interval": "1m", "limit": 500}
TIMEOUT = 30
MEMORY_CHECK_INTERVAL = 0.5
# =================================================


class MemoryMonitor:
    """内存监控器 - 后台线程定期采集内存使用"""
    
    def __init__(self, interval=MEMORY_CHECK_INTERVAL):
        self.interval = interval
        self.running = False
        self.thread = None
        self.samples = []
        self.peak_memory = 0
        self.initial_memory = 0
        self._lock = threading.Lock()
        
        try:
            import psutil
            self.psutil = psutil
            self.process = psutil.Process()
            self.available = True
        except ImportError:
            self.available = False
            print("[!] 未安装 psutil，内存监控功能不可用")
            print("    安装命令: pip install psutil")
    
    def get_memory_mb(self):
        """获取当前进程内存使用（MB）"""
        if not self.available:
            return 0
        return self.process.memory_info().rss / 1024 / 1024
    
    def _monitor_loop(self):
        """后台监控线程"""
        while self.running:
            try:
                mem_mb = self.get_memory_mb()
                with self._lock:
                    self.samples.append((time.time(), mem_mb))
                    if mem_mb > self.peak_memory:
                        self.peak_memory = mem_mb
            except Exception:
                pass
            time.sleep(self.interval)
    
    def start(self):
        """启动内存监控"""
        if not self.available:
            return
        self.initial_memory = self.get_memory_mb()
        self.peak_memory = self.initial_memory
        self.samples = [(time.time(), self.initial_memory)]
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止内存监控"""
        if not self.available:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        final_mem = self.get_memory_mb()
        with self._lock:
            self.samples.append((time.time(), final_mem))
            if final_mem > self.peak_memory:
                self.peak_memory = final_mem
    
    def get_stats(self):
        """获取内存统计信息"""
        if not self.available or not self.samples:
            return None
        
        with self._lock:
            samples = self.samples.copy()
        
        if len(samples) < 2:
            return {
                "initial_mb": self.initial_memory,
                "peak_mb": self.peak_memory,
                "final_mb": samples[-1][1] if samples else 0,
                "growth_mb": 0,
                "sample_count": len(samples),
            }
        
        memories = [s[1] for s in samples]
        return {
            "initial_mb": self.initial_memory,
            "peak_mb": self.peak_memory,
            "final_mb": samples[-1][1],
            "growth_mb": self.peak_memory - self.initial_memory,
            "avg_mb": statistics.mean(memories),
            "min_mb": min(memories),
            "sample_count": len(samples),
        }


class KlineLoadTester:
    def __init__(self):
        self.results = []
        self.lock = asyncio.Lock()
        self.start_time = None
        self.memory_monitor = MemoryMonitor()
        
    async def worker(self, session, worker_id, semaphore):
        """单个用户（worker）"""
        worker_results = []
        
        for i in range(REQUESTS_PER_USER):
            async with semaphore:
                start = time.time()
                url = f"{BASE_URL}/api/kline"
                params = KLINE_PARAMS.copy()
                
                try:
                    async with session.get(url, params=params) as resp:
                        elapsed = time.time() - start
                        
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("error"):
                                worker_results.append(("fail", elapsed, data.get("error")))
                                print(f"[User {worker_id:02d}] Req {i+1:02d}: [FAIL] 业务错误 - {elapsed:.2f}s")
                            else:
                                kline_count = len(data.get("data", []))
                                worker_results.append(("success", elapsed, None))
                                print(f"[User {worker_id:02d}] Req {i+1:02d}: [OK] {kline_count}条K线 - {elapsed:.2f}s")
                        else:
                            worker_results.append(("http_error", elapsed, f"HTTP {resp.status}"))
                            print(f"[User {worker_id:02d}] Req {i+1:02d}: [ERR] HTTP {resp.status} - {elapsed:.2f}s")
                            
                except asyncio.TimeoutError:
                    worker_results.append(("timeout", TIMEOUT, "Timeout"))
                    print(f"[User {worker_id:02d}] Req {i+1:02d}: [TIMEOUT]")
                except Exception as e:
                    worker_results.append(("error", 0, str(e)))
                    print(f"[User {worker_id:02d}] Req {i+1:02d}: [EXCEPTION] {str(e)[:50]}")
                
                async with self.lock:
                    self.results.extend(worker_results)
                
                if WAIT_MAX > 0:
                    await asyncio.sleep(__import__('random').uniform(WAIT_MIN, WAIT_MAX))
        
        return worker_results
    
    async def run(self):
        """主运行函数"""
        print("=" * 70)
        print("K线API高并发压测")
        print("=" * 70)
        print(f"目标: {BASE_URL}/api/kline")
        print(f"固定参数: interval={KLINE_PARAMS['interval']}, limit={KLINE_PARAMS['limit']}")
        print("-" * 70)
        print(f"并发用户: {CONCURRENT_USERS}")
        print(f"每用户请求: {REQUESTS_PER_USER}")
        print(f"总请求数: {CONCURRENT_USERS * REQUESTS_PER_USER}")
        print(f"全局并发限制: {MAX_CONCURRENT_REQUESTS}")
        
        if self.memory_monitor.available:
            initial_mem = self.memory_monitor.get_memory_mb()
            print(f"初始内存: {initial_mem:.1f} MB")
        print("=" * 70)
        print()
        
        self.start_time = time.time()
        self.memory_monitor.start()
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=50, enable_cleanup_closed=True, force_close=True)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers={"Content-Type": "application/json"}) as session:
            # 预热
            print("[WARMUP] 预热中...")
            try:
                async with session.get(f"{BASE_URL}/api/kline", params=KLINE_PARAMS) as resp:
                    await resp.text()
                print("[WARMUP] 完成\n")
            except Exception as e:
                print(f"[WARMUP] 失败: {e}\n")
            
            # 启动所有用户
            print(f"[START] 启动 {CONCURRENT_USERS} 个并发用户...\n")
            tasks = [self.worker(session, i, semaphore) for i in range(CONCURRENT_USERS)]
            await asyncio.gather(*tasks)
        
        self.memory_monitor.stop()
        total_time = time.time() - self.start_time
        self.print_report(total_time)
    
    def print_report(self, total_time):
        """打印报告"""
        success_results = [r for r in self.results if r[0] == "success"]
        fail_results = [r for r in self.results if r[0] != "success"]
        success_times = [r[1] for r in success_results]
        total_requests = len(self.results)
        mem_stats = self.memory_monitor.get_stats()
        
        print("\n" + "=" * 70)
        print("压测报告")
        print("=" * 70)
        print(f"目标端点: {BASE_URL}/api/kline")
        print(f"查询参数: interval={KLINE_PARAMS['interval']}, limit={KLINE_PARAMS['limit']}")
        print()
        print("并发配置:")
        print(f"  并发用户: {CONCURRENT_USERS}")
        print(f"  每用户请求: {REQUESTS_PER_USER}")
        print(f"  总请求数: {total_requests}")
        print()
        print("结果统计:")
        print(f"  总耗时: {total_time:.2f} 秒")
        print(f"  成功: {len(success_results)} ({len(success_results)/total_requests*100:.1f}%)")
        print(f"  失败: {len(fail_results)} ({len(fail_results)/total_requests*100:.1f}%)")
        
        if total_time > 0:
            print(f"  QPS: {len(success_results)/total_time:.2f} (每秒成功请求)")
        
        if success_times:
            print()
            print("响应时间统计:")
            print(f"  平均: {statistics.mean(success_times):.3f}s")
            print(f"  最快: {min(success_times):.3f}s")
            print(f"  最慢: {max(success_times):.3f}s")
            sorted_times = sorted(success_times)
            p50 = sorted_times[int(len(sorted_times)*0.5)]
            p95 = sorted_times[int(len(sorted_times)*0.95)] if len(sorted_times) >= 20 else sorted_times[-1]
            p99 = sorted_times[int(len(sorted_times)*0.99)] if len(sorted_times) >= 100 else sorted_times[-1]
            print(f"  P50:  {p50:.3f}s")
            print(f"  P95:  {p95:.3f}s")
            print(f"  P99:  {p99:.3f}s")
        
        # 内存统计
        if mem_stats:
            print()
            print("内存使用统计:")
            print(f"  初始内存: {mem_stats['initial_mb']:.1f} MB")
            print(f"  峰值内存: {mem_stats['peak_mb']:.1f} MB")
            print(f"  最终内存: {mem_stats['final_mb']:.1f} MB")
            print(f"  内存增长: {mem_stats['growth_mb']:+.1f} MB")
            if mem_stats['growth_mb'] > 0 and mem_stats['initial_mb'] > 0:
                growth_pct = (mem_stats['growth_mb'] / mem_stats['initial_mb']) * 100
                print(f"  增长比例: {growth_pct:+.1f}%")
            print(f"  采样次数: {mem_stats['sample_count']}")
            
            if mem_stats['growth_mb'] < 50:
                mem_rating = "[OK] 内存稳定"
            elif mem_stats['growth_mb'] < 200:
                mem_rating = "[WARN] 内存增长可控"
            else:
                mem_rating = "[ALERT] 内存增长较高"
            print(f"  内存评级: {mem_rating}")
        
        if fail_results:
            print()
            print("错误分布:")
            error_types = {}
            for r in fail_results:
                err_type = r[0]
                error_types[err_type] = error_types.get(err_type, 0) + 1
            for err_type, count in error_types.items():
                print(f"  {err_type}: {count}")
        
        print()
        if len(fail_results) == 0 and success_times:
            avg = statistics.mean(success_times)
            qps = len(success_results)/total_time if total_time > 0 else 0
            if avg < 0.1:
                rating = "[优秀] 极快 (平均<100ms)"
            elif avg < 0.5:
                rating = "[优秀] 良好 (平均<500ms)"
            elif avg < 1.0:
                rating = "[良好] 一般 (平均<1s)"
            elif avg < 3.0:
                rating = "[一般] 较慢 (平均1-3s)"
            else:
                rating = "[较差] 很慢 (平均>3s)"
            print(f"性能评级: {rating}")
            print(f"吞吐量: {qps:.2f} req/s")
        elif len(fail_results) / total_requests < 0.05:
            print("性能评级: [可用] 错误率<5%")
        else:
            print("性能评级: [不稳定] 错误率>5%")
        
        print("=" * 70)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='K线API高并发压测')
    parser.add_argument('--url', default=BASE_URL, help='目标服务器地址')
    parser.add_argument('--users', type=int, default=CONCURRENT_USERS, help='并发用户数')
    parser.add_argument('--requests', type=int, default=REQUESTS_PER_USER, help='每用户请求数')
    parser.add_argument('--interval', default=KLINE_PARAMS['interval'], help='时间级别')
    parser.add_argument('--limit', type=int, default=KLINE_PARAMS['limit'], help='返回数量')
    parser.add_argument('--max-concurrent', type=int, default=MAX_CONCURRENT_REQUESTS, help='全局最大并发')
    parser.add_argument('--timeout', type=int, default=TIMEOUT, help='超时时间秒')
    parser.add_argument('--mem-interval', type=float, default=MEMORY_CHECK_INTERVAL, help='内存检查间隔秒')
    return parser.parse_args()


if __name__ == "__main__":
    # Windows 上需要这行
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        import aiohttp
    except ImportError:
        print("请先安装依赖: pip install aiohttp")
        exit(1)
    
    args = parse_args()
    BASE_URL = args.url.rstrip('/')
    CONCURRENT_USERS = args.users
    REQUESTS_PER_USER = args.requests
    MAX_CONCURRENT_REQUESTS = args.max_concurrent
    TIMEOUT = args.timeout
    MEMORY_CHECK_INTERVAL = args.mem_interval
    KLINE_PARAMS['interval'] = args.interval
    KLINE_PARAMS['limit'] = args.limit
    
    tester = KlineLoadTester()
    asyncio.run(tester.run())

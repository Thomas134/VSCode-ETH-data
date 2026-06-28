#!/usr/bin/env python3
"""
纯 asyncio 高并发压测脚本
Windows 完美支持，无 gevent，无 multiprocessing 限制
"""
import asyncio
import aiohttp
import time
import statistics
import random
from datetime import datetime

# ==================== 配置区域（修改这里） ====================

# 目标服务器
TARGET_URL = "http://localhost:8080/api/backtest"
# TARGET_URL = "https://your-project.zeabur.app/api/backtest"

# 并发配置
CONCURRENT_USERS = 1     # 同时在线的虚拟用户数
REQUESTS_PER_USER = 1     # 每个用户发送多少请求
MAX_CONCURRENT_REQUESTS = 3000  # 全局最大并发请求数（防止瞬间压垮服务器）

# 请求间隔（模拟真实用户思考时间）
WAIT_MIN = 0.1             # 最短间隔（秒）
WAIT_MAX = 0.1             # 最长间隔（秒）

# 回测参数
PAYLOAD = {
    "interval": "1m",
    "start_date": "2025-01-01",
    "end_date": "2025-03-01",
    "mode": "both",
    "stop_loss_pct": 2.0,
    "take_profit_pct": 5.0,
    "initial_capital": 10000,
    "fee_rate": 0.055,
    "position_mode": "percent",
    "percent_per_trade": 20,
    "fixed_amount": 1000,
    "max_positions": 3,
    "use_stop_profit": True,
    "_skip_cache": True  # True=压力测试，False=测试缓存
}

# 超时设置（秒）
TIMEOUT = 60

# =============================================================

class LoadTester:
    def __init__(self):
        self.results = []
        self.lock = asyncio.Lock()
        self.start_time = None
        
    async def worker(self, session, worker_id, semaphore):
        """单个用户（worker）"""
        worker_results = []
        
        for i in range(REQUESTS_PER_USER):
            # 使用信号量控制全局并发数
            async with semaphore:
                start = time.time()
                
                # 准备请求数据（随机化）
                payload = PAYLOAD.copy()
                payload["mode"] = random.choice(["long", "short", "both"])
                
                try:
                    async with session.post(TARGET_URL, json=payload) as resp:
                        elapsed = time.time() - start
                        
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("error"):
                                worker_results.append(("fail", elapsed, data.get("error")))
                                print(f"[User {worker_id:02d}] Req {i+1:02d}: ❌ 业务错误 - {elapsed:.2f}s")
                            else:
                                cache_status = "[缓存]" if data.get("_cache_hit") else "[计算]"
                                worker_results.append(("success", elapsed, None))
                                print(f"[User {worker_id:02d}] Req {i+1:02d}: ✅ 成功{cache_status} - {elapsed:.2f}s")
                        else:
                            worker_results.append(("http_error", elapsed, f"HTTP {resp.status}"))
                            print(f"[User {worker_id:02d}] Req {i+1:02d}: ❌ HTTP {resp.status} - {elapsed:.2f}s")
                            
                except asyncio.TimeoutError:
                    worker_results.append(("timeout", TIMEOUT, "Timeout"))
                    print(f"[User {worker_id:02d}] Req {i+1:02d}: ⏱️  超时")
                except Exception as e:
                    worker_results.append(("error", 0, str(e)))
                    print(f"[User {worker_id:02d}] Req {i+1:02d}: 💥 异常 - {str(e)[:50]}")
                
                # 记录结果（线程安全）
                async with self.lock:
                    self.results.extend(worker_results)
                
                # 用户思考时间
                await asyncio.sleep(random.uniform(WAIT_MIN, WAIT_MAX))
        
        return worker_results
    
    async def run(self):
        """主运行函数"""
        print("=" * 70)
        print("Asyncio 高并发压测")
        print("=" * 70)
        print(f"目标: {TARGET_URL}")
        print(f"并发用户: {CONCURRENT_USERS}")
        print(f"每用户请求: {REQUESTS_PER_USER}")
        print(f"总请求数: {CONCURRENT_USERS * REQUESTS_PER_USER}")
        print(f"全局并发限制: {MAX_CONCURRENT_REQUESTS}")
        print(f"数据范围: {PAYLOAD['start_date']} ~ {PAYLOAD['end_date']}")
        print(f"跳过缓存: {PAYLOAD['_skip_cache']}")
        print("=" * 70)
        print()
        
        self.start_time = time.time()
        
        # 信号量控制全局并发（防止瞬间压垮服务器）
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        # 创建HTTP会话（连接池）
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        connector = aiohttp.TCPConnector(
            limit=100,              # 连接池大小
            limit_per_host=50,      # 单域名连接数
            enable_cleanup_closed=True,
            force_close=True        # 防止连接复用问题
        )
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        ) as session:
            
            # 预热（避免冷启动）
            print("预热中...")
            try:
                async with session.post(TARGET_URL, json=PAYLOAD) as resp:
                    await resp.text()
                print("✅ 预热完成\n")
            except Exception as e:
                print(f"⚠️ 预热失败: {e}\n")
            
            # 启动所有用户
            print(f"启动 {CONCURRENT_USERS} 个并发用户...\n")
            tasks = [
                self.worker(session, i, semaphore)
                for i in range(CONCURRENT_USERS)
            ]
            
            await asyncio.gather(*tasks)
        
        total_time = time.time() - self.start_time
        self.print_report(total_time)
    
    def print_report(self, total_time):
        """打印报告"""
        success_results = [r for r in self.results if r[0] == "success"]
        fail_results = [r for r in self.results if r[0] != "success"]
        
        success_times = [r[1] for r in success_results]
        total_requests = len(self.results)
        
        print("\n" + "=" * 70)
        print("📊 压测报告")
        print("=" * 70)
        print(f"总耗时: {total_time:.2f} 秒")
        print(f"总请求: {total_requests}")
        print(f"成功: {len(success_results)} ({len(success_results)/total_requests*100:.1f}%)")
        print(f"失败: {len(fail_results)} ({len(fail_results)/total_requests*100:.1f}%)")
        
        if total_time > 0:
            print(f"QPS: {len(success_results)/total_time:.2f} (每秒成功请求)")
        
        if success_times:
            print()
            print("响应时间统计:")
            print(f"  平均: {statistics.mean(success_times):.2f}s")
            print(f"  最快: {min(success_times):.2f}s")
            print(f"  最慢: {max(success_times):.2f}s")
            
            sorted_times = sorted(success_times)
            p50 = sorted_times[int(len(sorted_times)*0.5)]
            p95 = sorted_times[int(len(sorted_times)*0.95)]
            p99 = sorted_times[int(len(sorted_times)*0.99)]
            
            print(f"  P50:  {p50:.2f}s (中位数)")
            print(f"  P95:  {p95:.2f}s (95%请求快于此)")
            print(f"  P99:  {p99:.2f}s (99%请求快于此)")
        
        # 错误分类
        if fail_results:
            print()
            print("错误分布:")
            error_types = {}
            for r in fail_results:
                err_type = r[0]
                error_types[err_type] = error_types.get(err_type, 0) + 1
            for err_type, count in error_types.items():
                print(f"  {err_type}: {count}")
        
        # 性能评级
        print()
        if len(fail_results) == 0 and success_times:
            avg = statistics.mean(success_times)
            if avg < 1:
                rating = "🟢 优秀 (平均<1s)"
            elif avg < 3:
                rating = "🟡 良好 (平均1-3s)"
            elif avg < 10:
                rating = "🟠 一般 (平均3-10s)"
            else:
                rating = "🔴 较差 (平均>10s)"
            print(f"性能评级: {rating}")
        elif len(fail_results) / total_requests < 0.05:
            print("性能评级: 🟡 可用 (错误率<5%)")
        else:
            print("性能评级: 🔴 不稳定 (错误率>5%)")
        
        print("=" * 70)


if __name__ == "__main__":
    # Windows 上需要这行
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 安装检查
    try:
        import aiohttp
    except ImportError:
        print("请先安装依赖: pip install aiohttp")
        exit(1)
    
    # 运行测试
    tester = LoadTester()
    asyncio.run(tester.run())

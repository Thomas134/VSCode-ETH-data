"""
内存监控工具 - 用于诊断内存泄漏
"""
import os
import psutil
import gc

process = psutil.Process(os.getpid())

def get_memory_mb():
    """获取当前进程内存占用（MB）"""
    return process.memory_info().rss / 1024 / 1024

def log_memory(tag=""):
    """打印当前内存状态"""
    mem = get_memory_mb()
    print(f"[Memory {tag}] 当前占用: {mem:.1f} MB")
    return mem

def force_gc():
    """强制垃圾回收"""
    gc.collect()
    print(f"[GC] 已执行垃圾回收")

def get_object_count():
    """获取当前对象数量统计"""
    gc.collect()
    counts = {}
    for obj in gc.get_objects():
        typename = type(obj).__name__
        counts[typename] = counts.get(typename, 0) + 1
    
    # 排序显示最多的类型
    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    print("[Object Count] Top 10:")
    for typename, count in sorted_counts[:10]:
        print(f"  {typename}: {count}")
    
    return sorted_counts

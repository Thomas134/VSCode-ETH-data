# cache_manager.py
# K线数据缓存管理器
# 缓存分型计算结果，避免每次切周期都重新计算

import time
from threading import Lock

class KlineCacheManager:
    """K线数据缓存管理器，线程安全"""
    
    def __init__(self):
        self._lock = Lock()
        # 缓存结构: {
        #   "5m": {

        #       "fractal_regions": [...], # 缓存的分型区间
        #       "cached_at": 1234567890,  # 缓存时间戳


        #   },
        #   ...
        # }
        self._cache = {}
    






    def get_fractals(self, interval):
        """获取缓存的指定时间级别的分型结果，返回 fractal_regions 或 None"""
        with self._lock:

            entry = self._cache.get(interval)
            if entry:


                return entry["fractal_regions"]
            return None
    



    def set_fractals(self, interval, fractal_regions):
        """存入指定时间级别的分型结果"""
        with self._lock:


            self._cache[interval] = {
                "fractal_regions": fractal_regions,
                "cached_at": time.time(),
            }
    
    def clear(self, interval=None):





        """清除缓存。指定 interval 则只清除该级别，否则清除所有"""
        with self._lock:
            if interval is None:
                self._cache.clear()
            else:





                self._cache.pop(interval, None)
    
    def clear_all(self):
        """清除所有缓存"""
        with self._lock:
            self._cache.clear()






# 全局单例
kline_cache = KlineCacheManager()

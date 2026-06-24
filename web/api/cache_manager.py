# cache_manager.py
# K线数据缓存管理器
# 缓存分型计算结果，避免每次切周期都重新计算

import hashlib
import json
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


class BacktestCacheManager:
    """
    回测结果缓存管理器
    
    缓存策略：
    1. 基于所有回测参数的哈希值作为缓存key
    2. 缓存回测引擎的计算结果（包括trades, equity_curve等）
    3. 默认缓存1小时，可通过 ttl_seconds 调整
    """
    
    def __init__(self, ttl_seconds=3600):
        self._lock = Lock()
        self._ttl = ttl_seconds
        # 缓存结构: {
        #   "cache_key_hash": {
        #       "result": {...},       # 回测结果
        #       "cached_at": 1234567890, # 缓存时间戳
        #       "params_hash": "...",  # 参数哈希（用于调试）
        #   },
        #   ...
        # }
        self._cache = {}
    
    def _generate_key(self, params):
        """
        基于参数生成缓存key
        
        注意：参数需要是可JSON序列化的
        """
        # 排序参数确保顺序不影响哈希
        sorted_params = json.dumps(params, sort_keys=True, separators=(',', ':'))
        return hashlib.md5(sorted_params.encode('utf-8')).hexdigest()
    
    def get(self, params):
        """
        获取缓存的回测结果
        
        参数:
            params: 回测参数字典
            
        返回:
            缓存的结果字典，或 None（未缓存或已过期）
        """
        cache_key = self._generate_key(params)
        
        with self._lock:
            entry = self._cache.get(cache_key)
            if not entry:
                return None
            
            # 检查是否过期
            if time.time() - entry["cached_at"] > self._ttl:
                # 过期了，删除并返回None
                self._cache.pop(cache_key, None)
                return None
            
            # 返回缓存结果，添加缓存命中标记
            result = entry["result"].copy()
            result["_cache_hit"] = True
            result["_cached_at"] = entry["cached_at"]
            return result
    
    def set(self, params, result):
        """
        保存回测结果到缓存
        
        参数:
            params: 回测参数字典
            result: 回测结果字典
        """
        cache_key = self._generate_key(params)
        
        # 清理内部标记字段，避免污染缓存
        result_to_cache = {k: v for k, v in result.items() if not k.startswith('_')}
        
        with self._lock:
            self._cache[cache_key] = {
                "result": result_to_cache,
                "cached_at": time.time(),
                "params_hash": cache_key,
            }
    
    def clear(self, params=None):
        """
        清除缓存
        
        参数:
            params: 指定参数则只清除该参数的缓存，None则清除所有
        """
        with self._lock:
            if params is None:
                self._cache.clear()
            else:
                cache_key = self._generate_key(params)
                self._cache.pop(cache_key, None)
    
    def clear_all(self):
        """清除所有缓存"""
        with self._lock:
            self._cache.clear()
    
    def get_stats(self):
        """获取缓存统计信息"""
        with self._lock:
            now = time.time()
            total = len(self._cache)
            expired = sum(1 for e in self._cache.values() if now - e["cached_at"] > self._ttl)
            valid = total - expired
            
            return {
                "total_entries": total,
                "valid_entries": valid,
                "expired_entries": expired,
                "ttl_seconds": self._ttl,
            }


# 全局单例
kline_cache = KlineCacheManager()
backtest_cache = BacktestCacheManager(ttl_seconds=3600)  # 默认1小时过期

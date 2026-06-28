#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 序列化性能分析器 - 支持 orjson/标准库 切换
使用方式:
    1. 修改 USE_ORJSON = True/False 切换引擎
    2. 保持 enabled = True/False 控制是否输出性能日志

开关说明:
    USE_ORJSON = True  → 使用 orjson (需安装: pip install orjson)
    USE_ORJSON = False → 使用 Flask 默认 jsonify (标准库)
"""

import time
import json as json_stdlib
from flask import Response

# ═══════════════════════════════════════════════════════
# JSON 引擎开关（只改这里！）
# ═══════════════════════════════════════════════════════
USE_ORJSON = True   # ← True = 使用 orjson, False = 使用 Flask 默认 jsonify
# ═══════════════════════════════════════════════════════

# 尝试导入 orjson（可选依赖）
try:
    import orjson
    ORJSON_AVAILABLE = True
except ImportError:
    ORJSON_AVAILABLE = False
    orjson = None


class JSONProfiler:
    """JSON 序列化性能分析器"""

    enabled = False  # 性能测试输出开关

    @classmethod
    def profile(cls, data_dict, endpoint_name=""):
        """
        包装返回，支持 orjson / 标准库 切换，可选性能测试
        """
        if not cls.enabled:
            # 未开启性能测试时，根据 USE_ORJSON 选择序列化方式
            return cls._serialize(data_dict)

        # 开启性能测试，计时并输出
        start = time.perf_counter()
        response = cls._serialize(data_dict)
        elapsed_ms = (time.perf_counter() - start) * 1000
        # 分析数据
        data_info = cls._analyze_data(data_dict)

        # 显示使用的引擎
        engine = "orjson" if (USE_ORJSON and ORJSON_AVAILABLE) else "json"
        prefix = f"[{endpoint_name}]" if endpoint_name else "[JSON]"
        print(f"{prefix:12s} {elapsed_ms:>7.2f}ms | {data_info} | engine={engine}")

        return response
    
    @classmethod
    def _serialize(cls, data_dict):
        """内部序列化：根据 USE_ORJSON 选择库"""
        if USE_ORJSON and ORJSON_AVAILABLE:
            # 使用 orjson
            json_bytes = orjson.dumps(data_dict)
            return Response(
                json_bytes,
                mimetype='application/json'
            )
        else:
            # 使用 Flask 默认 jsonify（标准库）
            from flask import jsonify
            return jsonify(data_dict)

    @classmethod
    def _analyze_data(cls, data):
        """分析数据特征"""
        try:
            item_count = 0
            if isinstance(data, dict):
                if 'data' in data and isinstance(data['data'], list):
                    item_count = len(data['data'])
                elif 'fractal_regions' in data and isinstance(data['fractal_regions'], list):
                    item_count = len(data['fractal_regions'])
            # 估算大小
            if USE_ORJSON and ORJSON_AVAILABLE:
                size = len(orjson.dumps(data))
            else:
                size = len(json_stdlib.dumps(data))

            size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"

            if item_count > 0:
                return f"{item_count:>4} items | {size_str:>8}"
            else:
                return f"{size_str}"
        except Exception:
            return "analyze failed"


# 启动时打印当前配置
print(f"[JSONProfiler] USE_ORJSON={USE_ORJSON}, enabled={JSONProfiler.enabled}")
if USE_ORJSON and not ORJSON_AVAILABLE:
    print("[JSONProfiler] ⚠️  USE_ORJSON=True 但 orjson 未安装，将回退到标准库")
    print("[JSONProfiler]    安装命令: pip install orjson")


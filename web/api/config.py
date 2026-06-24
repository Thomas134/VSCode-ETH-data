# config.py
# 项目配置集中管理
# 所有API共享的配置统一放在这里，避免重复定义

from pathlib import Path

# ── 项目根目录 ──
# web/api/config.py → web → 项目根
BASE_DIR = Path(__file__).resolve().parents[2]

# ── 数据库路径 ──
DB_PATH = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_perpetual.db"
STRUCTURE_DB = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_structure.db"

# structure_api 中叠加显示也需要源数据库
SOURCE_DB = DB_PATH  # 跟原始K线库是同一个

# ── 时间级别与表名映射 ──
# kline_api.py 用：interval → K线表名
KLINE_TABLE_MAP = {
    "1m": "kline_1m",
    "5m": "kline_5m",
    "15m": "kline_15m",
    "1h": "kline_1h",
    "4h": "kline_4h",
    "1d": "kline_1d",
}

# structure_api.py 用：interval → (K线表名, 结构K线表名)
STRUCTURE_TABLE_MAP = {
    "1m": ("kline_1m", "kline_1m_std"),
    "5m": ("kline_5m", "kline_5m_std"),
    "15m": ("kline_15m", "kline_15m_std"),
    "1h": ("kline_1h", "kline_1h_std"),
    "4h": ("kline_4h", "kline_4h_std"),
    "1d": ("kline_1d", "kline_1d_std"),
}

# kline_api.py 中分型计算也用这个
FRACTAL_TABLE_MAP = {
    "1m": "kline_1m_std",
    "5m": "kline_5m_std",
    "15m": "kline_15m_std",
    "1h": "kline_1h_std",
    "4h": "kline_4h_std",
    "1d": "kline_1d_std",
}

# ── 时间间隔毫秒 ──
INTERVAL_MS = {
    "1m": 60000,
    "5m": 300000,
    "15m": 900000,
    "1h": 3600000,
    "4h": 14400000,
    "1d": 86400000,
}

# ── 默认参数 ──
DEFAULT_SYMBOL = "ETHUSDT"
DEFAULT_LIMIT = 500


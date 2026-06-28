# config.py
# 项目配置集中管理
# 所有API共享的配置统一放在这里，避免重复定义

from pathlib import Path
import sqlite3
import threading

# ── 数据库连接工厂（用完即关，避免内存泄漏） ──
# 注意：虽然 connect() 有 50-100ms 开销，但回测算 3-5 秒，占比很小
# 连接池会导致内存持续增长，所以采用"即用即关"模式

def get_db_connection():
    """
    获取数据库连接（WAL模式优化）
    每次新建连接，用完务必调用 conn.close()！
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=5000")  # 减小到 20MB，避免内存过大
    return conn

def get_structure_connection():
    """获取结构数据库连接（WAL模式优化）"""
    conn = sqlite3.connect(f"file:{STRUCTURE_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=5000")  # 减小缓存
    return conn

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


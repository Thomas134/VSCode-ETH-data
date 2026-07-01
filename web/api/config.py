# config.py
# 项目配置集中管理
# 所有API共享的配置统一放在这里，避免重复定义

from pathlib import Path
import sqlite3
import threading

# ── DuckDB 支持（阶段2：回测大数据查询专用） ──
# 条件：1) duckdb 库已安装  2) 数据库文件实际存在
try:
    import duckdb
    _duckdb_installed = True
except ImportError:
    _duckdb_installed = False

# 检查数据库文件是否存在（在导入时检查，避免运行时重复判断）
BASE_DIR = Path(__file__).resolve().parents[2]
DUCKDB_KLINE_PATH = BASE_DIR / "duckdb_migration" / "duckdb_data" / "eth_perpetual.duckdb"
DUCKDB_STRUCTURE_PATH = BASE_DIR / "duckdb_migration" / "duckdb_data" / "eth_structure.duckdb"

DUCKDB_AVAILABLE = _duckdb_installed and DUCKDB_KLINE_PATH.exists() and DUCKDB_STRUCTURE_PATH.exists()

# ── 数据库连接工厂（用完即关，避免内存泄漏） ──
# 注意：虽然 connect() 有 50-100ms 开销，但回测算 3-5 秒，占比很小
# 连接池会导致内存持续增长，所以采用"即用即关"模式

def get_db_connection():
    """
    获取数据库连接（只读，WAL模式已在写入端设置，此处无需重复）
    每次新建连接，用完务必调用 conn.close()！
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=5000")  # 减小到 20MB，避免内存过大
    conn.row_factory = sqlite3.Row
    return conn

def get_structure_connection():
    """获取结构数据库连接（只读，WAL模式已在写入端设置，此处无需重复）"""
    conn = sqlite3.connect(f"file:{STRUCTURE_DB}?mode=ro", uri=True)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=5000")  # 减小缓存
    conn.row_factory = sqlite3.Row
    return conn


# ── DuckDB 连接工厂（回测专用，阶段2） ──
def get_duckdb_kline_connection(read_only=True):
    """
    获取 DuckDB K线库连接（回测大数据查询专用）
    用法：conn.execute(...).fetchdf() 返回 pandas DataFrame
    """
    if not DUCKDB_AVAILABLE:
        raise ImportError("duckdb 未安装，请运行: pip install duckdb")
    if not DUCKDB_KLINE_PATH.exists():
        raise FileNotFoundError(f"DuckDB K线库不存在: {DUCKDB_KLINE_PATH}")
    conn = duckdb.connect(str(DUCKDB_KLINE_PATH), read_only=read_only)
    return conn

def get_duckdb_structure_connection(read_only=True):
    """
    获取 DuckDB 结构库连接（回测分型数据查询专用）
    """
    if not DUCKDB_AVAILABLE:
        raise ImportError("duckdb 未安装，请运行: pip install duckdb")
    if not DUCKDB_STRUCTURE_PATH.exists():
        raise FileNotFoundError(f"DuckDB 结构库不存在: {DUCKDB_STRUCTURE_PATH}")
    conn = duckdb.connect(str(DUCKDB_STRUCTURE_PATH), read_only=read_only)
    return conn

# ── 项目根目录 ──
# web/api/config.py → web → 项目根
BASE_DIR = Path(__file__).resolve().parents[2]

# ── 数据库路径 ──
DB_PATH = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_perpetual.db"
STRUCTURE_DB = BASE_DIR / "bybit_eth_data" / "data" / "processed" / "eth_structure.db"

# ── DuckDB 迁移后的路径（阶段1生成） ──
# 注意：这些路径已在上面定义，用于判断 DUCKDB_AVAILABLE
# DUCKDB_KLINE_PATH = BASE_DIR / "duckdb_migration" / "duckdb_data" / "eth_perpetual.duckdb"
# DUCKDB_STRUCTURE_PATH = BASE_DIR / "duckdb_migration" / "duckdb_data" / "eth_structure.duckdb"

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
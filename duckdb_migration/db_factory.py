"""
DuckDB 连接工厂（供后续阶段替换 web/api/config.py 使用）
=====================================================

用法示例：
    from duckdb_migration.db_factory import get_duckdb_kline_connection, get_duckdb_structure_connection

    conn = get_duckdb_kline_connection()
    result = conn.execute("SELECT * FROM kline_1m LIMIT 10").fetchall()
    conn.close()
"""

from pathlib import Path

# ── 路径配置 ──
MIGRATION_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = MIGRATION_DIR / "duckdb_data"

KLINE_DB_PATH = OUTPUT_DIR / "eth_perpetual.duckdb"
STRUCTURE_DB_PATH = OUTPUT_DIR / "eth_structure.duckdb"


def _ensure_duckdb():
    """延迟导入，避免未安装时报错"""
    try:
        import duckdb
        return duckdb
    except ImportError:
        raise ImportError("未安装 duckdb，请先执行：pip install duckdb")


def get_duckdb_kline_connection(read_only: bool = True):
    """
    获取原始K线数据库的 DuckDB 连接

    Args:
        read_only: 是否只读模式（推荐 API 查询使用只读）

    Returns:
        duckdb.DuckDBPyConnection
    """
    duckdb = _ensure_duckdb()

    if not KLINE_DB_PATH.exists():
        raise FileNotFoundError(f"K线数据库不存在: {KLINE_DB_PATH}，请先运行 migrate.py")

    conn = duckdb.connect(str(KLINE_DB_PATH), read_only=read_only)
    return conn


def get_duckdb_structure_connection(read_only: bool = True):
    """
    获取结构K线数据库的 DuckDB 连接

    Args:
        read_only: 是否只读模式

    Returns:
        duckdb.DuckDBPyConnection
    """
    duckdb = _ensure_duckdb()

    if not STRUCTURE_DB_PATH.exists():
        raise FileNotFoundError(f"结构数据库不存在: {STRUCTURE_DB_PATH}，请先运行 migrate.py")

    conn = duckdb.connect(str(STRUCTURE_DB_PATH), read_only=read_only)
    return conn


def get_duckdb_connection(db_path: Path, read_only: bool = True):
    """
    通用 DuckDB 连接工厂

    Args:
        db_path: 数据库文件路径
        read_only: 是否只读模式

    Returns:
        duckdb.DuckDBPyConnection
    """
    duckdb = _ensure_duckdb()

    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    return duckdb.connect(str(db_path), read_only=read_only)
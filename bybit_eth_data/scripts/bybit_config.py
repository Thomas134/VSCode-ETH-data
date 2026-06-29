# config.py
from pathlib import Path

# 基础路径配置 - 动态推断项目根目录
BASE_DIR = Path(__file__).resolve().parents[1]  # scripts的父目录即项目根目录
DATA_DIR = BASE_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DATA_DIR = DATA_DIR / "raw"
SCRIPTS_DIR = BASE_DIR / "scripts"

def init_directories():
    """初始化所有必要的目录（显式调用，避免导入时副作用）"""
    for directory in [DATA_DIR, PROCESSED_DIR, RAW_DATA_DIR, SCRIPTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

# 数据库配置
DB_NAME = "eth_perpetual.db"
DB_PATH = PROCESSED_DIR / DB_NAME

# Bybit API 配置
BYBIT_API_KEY = "你的API_KEY"
BYBIT_API_SECRET = "你的API_SECRET"

# 数据配置
SYMBOL = "ETHUSDT"  # 交易对

# 多时间级别配置
TIME_INTERVALS = {
    "1m": {
        "interval": "1",
        "table_name": "kline_1m",
        "description": "1分钟K线"
    },
    "5m": {
        "interval": "5", 
        "table_name": "kline_5m",
        "description": "5分钟K线"
    },
    "15m": {
        "interval": "15",
        "table_name": "kline_15m", 
        "description": "15分钟K线"
    },
    "1h": {
        "interval": "60",
        "table_name": "kline_1h",
        "description": "1小时K线"
    },
    "4h": {
        "interval": "240",
        "table_name": "kline_4h",
        "description": "4小时K线"
    },
    "1d": {
        "interval": "D",
        "table_name": "kline_1d",
        "description": "日K线"
    }
}

# 默认时间间隔（用于向后兼容）
DEFAULT_INTERVAL = "1m"
INTERVAL = TIME_INTERVALS[DEFAULT_INTERVAL]["interval"]

def print_config_info():
    """打印配置信息（需要时显式调用）"""
    print("✓ 配置文件加载成功")
    print(f"项目根目录: {BASE_DIR}")
    print(f"数据库路径: {DB_PATH}")
    print(f"支持的时间级别: {list(TIME_INTERVALS.keys())}")
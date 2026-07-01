import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    level=logging.INFO,
    log_dir="logs",
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
):
    """
    统一日志配置
    """
    # 确保日志目录存在
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 文件输出（自动轮转）
    file_handler = RotatingFileHandler(
        log_path / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # 根日志器配置
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 避免重复添加 handler（热重载时）
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # 第三方库降噪
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("engineio").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)


def get_logger(name):
    """
    获取模块级日志器
    用法：logger = get_logger(__name__)
    """
    return logging.getLogger(name)
"""统一错误日志 — 防止异常被静默吞没"""

import logging
import os
import traceback
from datetime import datetime

LOG_DIR = os.path.expanduser("~/.research-copilot-os/logs")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("rco_error")
logger.setLevel(logging.WARNING)

# 文件 handler
fh = logging.FileHandler(
    os.path.join(LOG_DIR, f"errors_{datetime.now().strftime('%Y%m%d')}.log"),
    encoding="utf-8",
)
fh.setLevel(logging.WARNING)
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(fh)


def log_error(module: str, e: Exception, context: str = ""):
    """记录错误到文件，包含完整 traceback"""
    tb = traceback.format_exc()
    logger.error(f"[{module}] {context}\n{tb}")


def safe_call(func, *args, default=None, module: str = "", **kwargs):
    """安全调用函数，出错时记录日志并返回默认值"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log_error(module or func.__name__, e, f"args={str(args)[:200]}")
        return default

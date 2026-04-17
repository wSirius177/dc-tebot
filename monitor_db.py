"""
专用于本地文件夹监控上传功能的数据库操作模块
使用 SQLite 独立存储上传过的文件记录，与 Discord 转发状态隔离。
"""

import sqlite3
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 数据库文件路径
_db_dir = os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_db_dir, "monitor_data.db")


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接。"""
    return sqlite3.connect(DB_PATH)


def init_monitor_db() -> None:
    """初始化数据库，创建已上传文件记录表（如不存在）。"""
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_files (
                filepath TEXT PRIMARY KEY
            )
            """
        )
        conn.commit()
    logger.info("监控专用数据库初始化完成: %s", DB_PATH)


def is_file_uploaded(filepath: str) -> bool:
    """
    检查指定文件是否已上传过。
    
    Args:
        filepath: 文件名的相对或绝对路径
        
    Returns:
        如果已上传返回 True，否则返回 False
    """
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM uploaded_files WHERE filepath = ?",
            (filepath,),
        )
        row = cursor.fetchone()
    return row is not None


def mark_file_uploaded(filepath: str) -> None:
    """
    将文件标记为已上传。
    
    Args:
        filepath: 文件名的相对或绝对路径
    """
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO uploaded_files (filepath) VALUES (?)",
            (filepath,),
        )
        conn.commit()
    logger.debug("已记录文件上传状态: %s", filepath)

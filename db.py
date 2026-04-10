"""
数据库操作模块
使用 SQLite 持久化存储消息同步状态，支持断线补发。
"""

import sqlite3
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 数据库文件路径
# 优先使用环境变量 DB_DIR 指定的目录（Docker 环境），否则使用脚本所在目录
_db_dir = os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_db_dir, "sync_data.db")


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接。"""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """初始化数据库，创建同步状态表（如不存在）。"""
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_status (
                channel_id TEXT PRIMARY KEY,
                last_msg_id TEXT NOT NULL
            )
            """
        )
        conn.commit()
    logger.info("数据库初始化完成: %s", DB_PATH)


def get_last_msg_id(channel_id: str) -> Optional[str]:
    """
    获取指定频道上次成功同步的最后一条消息 ID。

    Args:
        channel_id: Discord 频道 ID（字符串形式）

    Returns:
        消息 ID 字符串，如果不存在则返回 None
    """
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT last_msg_id FROM sync_status WHERE channel_id = ?",
            (channel_id,),
        )
        row = cursor.fetchone()
    if row:
        logger.debug("频道 %s 上次同步位置: %s", channel_id, row[0])
        return row[0]
    logger.debug("频道 %s 无同步记录（首次运行）", channel_id)
    return None


def update_last_msg_id(channel_id: str, msg_id: str) -> None:
    """
    更新指定频道的最后同步消息 ID。

    Args:
        channel_id: Discord 频道 ID（字符串形式）
        msg_id: 最新成功转发的消息 ID（字符串形式）
    """
    with _get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_status (channel_id, last_msg_id) VALUES (?, ?)",
            (channel_id, msg_id),
        )
        conn.commit()
    logger.debug("已更新频道 %s 同步位置: %s", channel_id, msg_id)

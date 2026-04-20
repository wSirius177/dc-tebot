"""
数据库操作模块
使用 SQLite 持久化存储消息同步状态，支持断线补发。
新增 failed_tasks 表用于记录转发失败的消息，由后台任务自动重试。
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
    """初始化数据库，创建同步状态表和失败任务表（如不存在）。"""
    with _get_connection() as conn:
        # 同步水位线表（原有）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_status (
                channel_id TEXT PRIMARY KEY,
                last_msg_id TEXT NOT NULL
            )
            """
        )
        # 失败任务表（新增）
        # message_id: Discord 消息 ID
        # channel_id: 消息所在频道 ID
        # fail_count: 累计失败次数（超过上限后放弃重试）
        # created_at: 首次记录时间
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS failed_tasks (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                fail_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    logger.info("数据库初始化完成: %s", DB_PATH)


# ── 同步水位线操作（原有）────────────────────────────────

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


# ── 失败任务操作（新增）────────────────────────────────

def add_failed_message(channel_id: str, msg_id: str) -> None:
    """
    记录一条转发失败的消息。如果该消息已在失败列表中，则累加失败次数。

    Args:
        channel_id: Discord 频道 ID
        msg_id: 转发失败的 Discord 消息 ID
    """
    with _get_connection() as conn:
        # 先检查是否已存在
        cursor = conn.execute(
            "SELECT fail_count FROM failed_tasks WHERE message_id = ?",
            (msg_id,),
        )
        row = cursor.fetchone()
        if row:
            # 已存在，累加失败次数
            conn.execute(
                "UPDATE failed_tasks SET fail_count = fail_count + 1 WHERE message_id = ?",
                (msg_id,),
            )
        else:
            # 首次失败，插入新记录
            conn.execute(
                "INSERT INTO failed_tasks (message_id, channel_id, fail_count) VALUES (?, ?, 1)",
                (msg_id, channel_id),
            )
        conn.commit()
    logger.info("已记录失败消息: ID=%s (频道: %s)", msg_id, channel_id)


def get_failed_messages(max_fail_count: int = 10) -> list:
    """
    获取所有待重试的失败消息（失败次数未超过上限的）。

    Args:
        max_fail_count: 最大失败次数，超过该次数的消息不再重试（默认 10 次）

    Returns:
        列表，每项为 (message_id, channel_id, fail_count) 元组
    """
    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT message_id, channel_id, fail_count FROM failed_tasks WHERE fail_count < ? ORDER BY created_at ASC",
            (max_fail_count,),
        )
        rows = cursor.fetchall()
    return rows


def clear_failed_message(msg_id: str) -> None:
    """
    重试成功后，从失败列表中清除该消息的记录。

    Args:
        msg_id: 已成功重发的 Discord 消息 ID
    """
    with _get_connection() as conn:
        conn.execute(
            "DELETE FROM failed_tasks WHERE message_id = ?",
            (msg_id,),
        )
        conn.commit()
    logger.info("已清除失败记录: ID=%s（重试成功）", msg_id)

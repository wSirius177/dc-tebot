"""
Discord → Telegram 消息转发机器人
主入口脚本：启动 Discord 客户端，监听目标频道消息并转发到 Telegram。
支持断线补发（History Backfill）和状态持久化。
"""

import asyncio
import logging
import sys

import discord

from config import DISCORD_TOKEN, DISCORD_CHANNEL_ID, BACKFILL_DELAY, PROXY_URL
from db import init_db, get_last_msg_id, update_last_msg_id
from forwarder import forward_message

# ── 日志配置 ────────────────────────────────────────────

def setup_logging() -> None:
    """配置日志：同时输出到控制台和文件。"""
    log_format = "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)

    # 文件处理器（日志文件与数据库存放在同一目录）
    import os
    _log_dir = os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__)))
    _log_path = os.path.join(_log_dir, "bot.log")
    file_handler = logging.FileHandler(_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(file_handler)

    # 降低第三方库日志等级
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

# ── Discord 客户端 ──────────────────────────────────────

# 配置所需的 Intents
intents = discord.Intents.default()
intents.message_content = True  # 需要在 Discord 开发者后台开启
intents.messages = True

client = discord.Client(intents=intents, proxy=PROXY_URL)


@client.event
async def on_ready():
    """
    Discord 客户端就绪事件。
    执行断线补发逻辑：检查上次同步位置，补发遗漏的消息。
    """
    logger.info("Discord 机器人已登录: %s (ID: %s)", client.user.name, client.user.id)
    logger.info("监听频道 ID: %s", DISCORD_CHANNEL_ID)

    # 获取目标频道
    channel = client.get_channel(DISCORD_CHANNEL_ID)
    if channel is None:
        logger.error("无法找到频道 ID: %s，请检查配置和机器人权限。", DISCORD_CHANNEL_ID)
        return

    logger.info("已连接到频道: #%s", channel.name)

    # ── 断线补发 (History Backfill) ──
    channel_id_str = str(DISCORD_CHANNEL_ID)
    last_msg_id = get_last_msg_id(channel_id_str)

    if last_msg_id is None:
        # 首次运行：获取频道最新消息 ID 作为起始点，不进行历史补发
        logger.info("首次运行，不进行历史补发。记录当前频道最新消息位置...")
        try:
            async for msg in channel.history(limit=1):
                update_last_msg_id(channel_id_str, str(msg.id))
                logger.info("已记录起始位置: 消息 ID %s", msg.id)
                break
        except Exception as e:
            logger.error("获取频道最新消息失败: %s", e)
        return

    # 存在上次同步位置 → 补发遗漏消息
    logger.info("检测到上次同步位置: %s，开始补发遗漏消息...", last_msg_id)
    backfill_count = 0
    fail_count = 0

    try:
        after_obj = discord.Object(id=int(last_msg_id))
        async for msg in channel.history(after=after_obj, oldest_first=True):
            # 跳过机器人消息
            if msg.author.bot:
                continue

            success = await forward_message(msg)
            if success:
                update_last_msg_id(channel_id_str, str(msg.id))
                backfill_count += 1
            else:
                fail_count += 1

            # 频率控制，防止触发 Telegram API 速率限制
            await asyncio.sleep(BACKFILL_DELAY)

    except Exception as e:
        logger.error("补发过程中出错: %s", e, exc_info=True)

    logger.info("补发完成: 成功 %d 条, 失败 %d 条", backfill_count, fail_count)


@client.event
async def on_message(message: discord.Message):
    """
    实时消息监听事件。
    仅处理来自目标频道的非机器人消息。
    """
    # 仅处理目标频道的消息
    if message.channel.id != DISCORD_CHANNEL_ID:
        return

    # 跳过机器人消息（包括自己）
    if message.author.bot:
        return

    # 日志中显示消息类型摘要
    if message.content:
        content_preview = message.content[:50]
    elif message.attachments:
        content_preview = f"(附件×{len(message.attachments)})"
    elif getattr(message, "message_snapshots", None):
        content_preview = "(转发消息)"
    elif message.embeds:
        content_preview = "(嵌入内容)"
    elif message.stickers:
        content_preview = f"(贴纸: {message.stickers[0].name})"
    else:
        content_preview = "(未知类型)"

    logger.info("收到新消息: [%s] %s (ID: %s)",
                message.author.display_name,
                content_preview,
                message.id)

    # 转发到 Telegram
    success = await forward_message(message)

    if success:
        # 更新同步位置
        update_last_msg_id(str(DISCORD_CHANNEL_ID), str(message.id))
        logger.info("消息 %s 转发并记录成功", message.id)
    else:
        logger.warning("消息 %s 转发失败", message.id)


# ── 主入口 ──────────────────────────────────────────────

def main():
    """程序主入口。"""
    setup_logging()
    logger.info("=" * 50)
    logger.info("Discord → Telegram 转发机器人启动中...")
    logger.info("=" * 50)

    # 初始化数据库
    init_db()

    # 启动 Discord 客户端（自带自动重连机制）
    try:
        client.run(DISCORD_TOKEN, log_handler=None)  # log_handler=None 避免重复日志
    except discord.LoginFailure:
        logger.critical("Discord 登录失败！请检查 DISCORD_TOKEN 是否正确。")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号，程序关闭。")
    except Exception as e:
        logger.critical("程序异常退出: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

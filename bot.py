"""
Discord → Telegram 消息转发机器人
主入口脚本：启动 Discord 客户端，监听目标频道消息并转发到 Telegram。
支持断线补发（History Backfill）、故障自动重试和状态持久化。
支持通过 ENABLE_DISCORD_FORWARDING 开关控制是否启动 Discord 客户端。
"""

import asyncio
import logging
import sys

import discord

from config import (
    DISCORD_TOKEN, DISCORD_CHANNEL_ID, BACKFILL_DELAY,
    PROXY_URL, MONITOR_FOLDER_PATH, ENABLE_DISCORD_FORWARDING,
    RETRY_INTERVAL,
)
from db import (
    init_db, get_last_msg_id, update_last_msg_id,
    add_failed_message, get_failed_messages, clear_failed_message,
)
from forwarder import forward_message
from folder_monitor import monitor_loop

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


# ── 故障重试后台任务 ────────────────────────────────────

async def retry_loop(discord_client=None):
    """
    后台任务协程：定期扫描 failed_tasks 表，对失败消息进行自动重试。
    每隔 RETRY_INTERVAL 秒执行一次扫描。
    如果消息累计失败超过 10 次，将放弃重试并记录警告日志。

    Args:
        discord_client: Discord 客户端实例（如果启用了 Discord 转发功能）
    """
    # 等待一小段时间再开始首次扫描，避免启动时和补发逻辑冲突
    await asyncio.sleep(30)

    logger.info("故障重试任务已启动，扫描间隔: %s 秒", RETRY_INTERVAL)

    while True:
        try:
            failed_list = get_failed_messages(max_fail_count=10)

            if failed_list:
                logger.info("发现 %d 条待重试的失败消息，开始补发...", len(failed_list))

                for msg_id, channel_id, fail_count in failed_list:
                    success = False

                    # 尝试通过 Discord API 重新获取消息并转发
                    if discord_client and discord_client.is_ready():
                        try:
                            channel = discord_client.get_channel(int(channel_id))
                            if channel:
                                message = await channel.fetch_message(int(msg_id))
                                success = await forward_message(message)
                            else:
                                logger.warning(
                                    "[重试] 无法找到频道 %s，跳过消息 %s",
                                    channel_id, msg_id,
                                )
                        except discord.NotFound:
                            # 消息已被删除，无需再重试
                            logger.warning(
                                "[重试] 消息 %s 已被删除，清除失败记录", msg_id,
                            )
                            clear_failed_message(msg_id)
                            continue
                        except Exception as e:
                            logger.error(
                                "[重试] 获取消息 %s 失败: %s", msg_id, e,
                            )
                    else:
                        logger.debug(
                            "[重试] Discord 客户端未就绪，跳过本轮重试"
                        )
                        break  # 客户端未就绪，等下一轮

                    if success:
                        # 重试成功，清除记录并更新水位线
                        clear_failed_message(msg_id)
                        update_last_msg_id(channel_id, msg_id)
                        logger.info(
                            "[重试] 消息 %s 补发成功（第 %d 次尝试）",
                            msg_id, fail_count + 1,
                        )
                    else:
                        # 重试仍然失败，fail_count 已在 add_failed_message 中累加
                        add_failed_message(channel_id, msg_id)
                        logger.warning(
                            "[重试] 消息 %s 补发仍失败，累计 %d 次",
                            msg_id, fail_count + 1,
                        )

                    # 频率控制
                    await asyncio.sleep(BACKFILL_DELAY)

        except Exception as e:
            logger.error("重试任务异常: %s", e, exc_info=True)

        # 等待下一轮扫描
        await asyncio.sleep(RETRY_INTERVAL)


# ── Discord 客户端 ──────────────────────────────────────

# 配置所需的 Intents
intents = discord.Intents.default()
intents.message_content = True  # 需要在 Discord 开发者后台开启
intents.messages = True

client = discord.Client(intents=intents, proxy=PROXY_URL) if ENABLE_DISCORD_FORWARDING else None


def _setup_discord_events():
    """注册 Discord 事件处理器（仅在启用转发时调用）。"""
    if client is None:
        return

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

        # ── 启动本地文件夹监控 ──
        if MONITOR_FOLDER_PATH:
            logger.info("检测到配置了 MONITOR_FOLDER_PATH，正在启动后台文件监控任务...")
            client.loop.create_task(monitor_loop())

        # ── 启动故障重试任务 ──
        client.loop.create_task(retry_loop(discord_client=client))

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
                    # 补发失败 → 记录到故障名单
                    add_failed_message(channel_id_str, str(msg.id))
                    fail_count += 1

                # 频率控制，防止触发 Telegram API 速率限制
                await asyncio.sleep(BACKFILL_DELAY)

        except Exception as e:
            logger.error("补发过程中出错: %s", e, exc_info=True)

        logger.info("补发完成: 成功 %d 条, 失败 %d 条（失败消息已记录，稍后自动重试）", backfill_count, fail_count)

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
            # 转发失败 → 记录到故障名单，由后台任务自动重试
            add_failed_message(str(DISCORD_CHANNEL_ID), str(message.id))
            logger.warning("消息 %s 转发失败，已加入重试队列", message.id)


# 注册事件处理器
_setup_discord_events()


# ── 独立模式（不启用 Discord 转发时）──────────────────

async def standalone_loop():
    """
    独立运行模式：不启动 Discord 客户端，仅运行本地文件监控和故障重试任务。
    当 ENABLE_DISCORD_FORWARDING=False 时使用此入口。
    """
    logger.info("Discord 转发功能已关闭，程序以独立模式运行")
    logger.info("仅启动以下后台任务:")

    tasks = []

    if MONITOR_FOLDER_PATH:
        logger.info(" - 本地文件夹监控")
        tasks.append(asyncio.create_task(monitor_loop()))
    else:
        logger.info(" - 本地文件夹监控（未配置，跳过）")

    # 独立模式下也启动重试任务（但由于没有 Discord 客户端，重试会跳过）
    logger.info(" - 故障重试任务（注意：无 Discord 客户端，无法重试 DC 消息）")
    tasks.append(asyncio.create_task(retry_loop(discord_client=None)))

    if not tasks:
        logger.warning("没有任何后台任务可运行，程序即将退出。")
        return

    # 保持运行
    await asyncio.gather(*tasks)


# ── 主入口 ──────────────────────────────────────────────

def main():
    """程序主入口。"""
    setup_logging()
    logger.info("=" * 50)
    logger.info("Discord → Telegram 转发机器人启动中...")
    logger.info("=" * 50)

    # 初始化数据库
    init_db()

    if ENABLE_DISCORD_FORWARDING:
        # 启用 Discord 转发 → 使用 Discord 客户端作为主事件循环
        logger.info("Discord 转发功能: 已启用")
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
    else:
        # 不启用 Discord 转发 → 使用 asyncio 独立运行后台任务
        logger.info("Discord 转发功能: 已关闭")
        try:
            asyncio.run(standalone_loop())
        except KeyboardInterrupt:
            logger.info("收到退出信号，程序关闭。")
        except Exception as e:
            logger.critical("程序异常退出: %s", e, exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

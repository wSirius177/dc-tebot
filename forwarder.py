"""
Telegram 消息转发模块
负责将 Discord 消息格式化并发送到 Telegram 群组。
支持文字、图片、文件附件的转发，以及通过代理发送请求。
"""

import logging
import io
from typing import Optional

import httpx
import telegram
from telegram.request import HTTPXRequest

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROXY_URL

logger = logging.getLogger(__name__)

# ── 初始化 Telegram Bot ──────────────────────────────────

def _create_bot() -> telegram.Bot:
    """
    创建 Telegram Bot 实例。
    如果配置了代理，则使用 httpx 代理客户端。
    设置较长的超时时间以应对代理网络波动。
    """
    if PROXY_URL:
        logger.info("Telegram Bot 使用代理: %s", PROXY_URL)
        request = HTTPXRequest(
            proxy=PROXY_URL,
            read_timeout=120.0,
            write_timeout=120.0,
            connect_timeout=30.0,
        )
        return telegram.Bot(token=TELEGRAM_BOT_TOKEN, request=request)
    else:
        logger.info("Telegram Bot 未使用代理（直连）")
        request = HTTPXRequest(
            read_timeout=60.0,
            write_timeout=60.0,
            connect_timeout=30.0,
        )
        return telegram.Bot(token=TELEGRAM_BOT_TOKEN, request=request)


bot = _create_bot()


# ── 附件下载 ────────────────────────────────────────────

async def _download_attachment(url: str) -> Optional[bytes]:
    """
    下载 Discord 附件内容。

    Args:
        url: 附件的 URL 地址

    Returns:
        文件字节内容，下载失败返回 None
    """
    try:
        transport_kwargs = {}
        if PROXY_URL:
            transport_kwargs["proxy"] = PROXY_URL
        async with httpx.AsyncClient(**transport_kwargs) as client:
            response = await client.get(url, timeout=60.0)
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error("下载附件失败 (%s): %s", url, e)
        return None


# ── 嵌入内容处理 ────────────────────────────────────────

async def _forward_embeds(embeds: list, author_name: str, text_content: str, already_sent_header: bool) -> bool:
    """
    处理 Discord 嵌入内容（转发消息、链接预览等）并发送到 Telegram。

    Args:
        embeds: discord.Embed 列表
        author_name: 消息作者名称
        text_content: 消息文字内容
        already_sent_header: 是否已经发送过作者头信息（比如附件已发送）

    Returns:
        True 表示至少成功发送了一条嵌入内容
    """
    sent_any = False
    sent_header = already_sent_header

    for embed in embeds:
        # 提取嵌入文字
        embed_parts = []
        if embed.author and embed.author.name:
            embed_parts.append(f"[{embed.author.name}]")
        if embed.title:
            embed_parts.append(f"📌 {embed.title}")
        if embed.description:
            embed_parts.append(embed.description)
        if embed.url and not embed.image:
            embed_parts.append(embed.url)
        # 提取字段
        if embed.fields:
            for field in embed.fields:
                embed_parts.append(f"{field.name}: {field.value}")

        embed_text = "\n".join(embed_parts)

        # 构建前缀（作者信息 + 原始文字）
        if not sent_header:
            prefix = f"[{author_name}]: {text_content}" if text_content else f"[{author_name}]"
            sent_header = True
        else:
            prefix = ""

        # 嵌入有图片 → 发送图片
        image_url = None
        if embed.image and embed.image.url:
            image_url = embed.image.url
        elif embed.thumbnail and embed.thumbnail.url and not embed.video:
            image_url = embed.thumbnail.url

        if image_url:
            caption = f"{prefix}\n{embed_text}".strip() if embed_text else prefix
            # Telegram caption 最大长度 1024
            if len(caption) > 1024:
                caption = caption[:1021] + "..."
            image_data = await _download_attachment(image_url)
            if image_data:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHAT_ID,
                    photo=io.BytesIO(image_data),
                    caption=caption or None,
                )
                logger.info("转发嵌入图片成功 (%s)", author_name)
                sent_any = True
                continue

        # 纯文字嵌入 → 发送文字
        if embed_text:
            full_text = f"{prefix}\n{embed_text}".strip() if prefix else embed_text
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=full_text,
            )
            logger.info("转发嵌入文字成功 (%s)", author_name)
            sent_any = True

    return sent_any


# ── 转发快照处理（Discord 新版转发消息）──────────────────

async def _forward_snapshots(message, author_name: str) -> bool:
    """
    处理 Discord 新版转发消息（message_snapshots）。

    Args:
        message: discord.Message 对象
        author_name: 转发者名称

    Returns:
        True 表示成功处理了快照内容
    """
    snapshots = getattr(message, "message_snapshots", None)
    if not snapshots:
        return False

    sent_any = False
    for snapshot in snapshots:
        # 提取快照中的消息数据
        snap_msg = getattr(snapshot, "message", snapshot)
        snap_content = getattr(snap_msg, "content", "") or ""
        snap_attachments = getattr(snap_msg, "attachments", [])
        snap_embeds = getattr(snap_msg, "embeds", [])

        # 发送快照文字
        if snap_content:
            formatted = f"[{author_name} 转发]: {snap_content}"
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=formatted,
            )
            logger.info("转发快照文字成功 (%s)", author_name)
            sent_any = True

        # 发送快照附件
        for attachment in snap_attachments:
            url = getattr(attachment, "url", None)
            filename = getattr(attachment, "filename", "file")
            content_type = getattr(attachment, "content_type", "") or ""
            if not url:
                continue

            file_data = await _download_attachment(url)
            if file_data is None:
                continue

            caption = f"[{author_name} 转发]" if not sent_any else None
            if content_type.startswith("image/"):
                await bot.send_photo(
                    chat_id=TELEGRAM_CHAT_ID,
                    photo=io.BytesIO(file_data),
                    caption=caption,
                )
                logger.info("转发快照图片成功: %s (%s)", filename, author_name)
            else:
                await bot.send_document(
                    chat_id=TELEGRAM_CHAT_ID,
                    document=io.BytesIO(file_data),
                    filename=filename,
                    caption=caption,
                )
                logger.info("转发快照文件成功: %s (%s)", filename, author_name)
            sent_any = True

        # 发送快照嵌入
        if snap_embeds:
            result = await _forward_embeds(snap_embeds, author_name, "", sent_any)
            if result:
                sent_any = True

    return sent_any


# ── 核心转发逻辑 ────────────────────────────────────────

async def forward_message(message) -> bool:
    """
    将一条 Discord 消息转发到 Telegram 群组。

    处理逻辑:
    1. 过滤机器人消息
    2. 转发文字内容
    3. 逐个处理附件（图片 → send_photo，其他 → send_document）
    4. 处理嵌入内容（转发消息、链接预览等）
    5. 处理贴纸

    Args:
        message: discord.Message 对象

    Returns:
        True 表示转发成功，False 表示失败或被过滤
    """
    # 过滤机器人消息
    if message.author.bot:
        logger.debug("跳过机器人消息: %s (作者: %s)", message.id, message.author)
        return False

    author_name = message.author.display_name or message.author.name
    text_content = message.content or ""
    has_attachments = bool(message.attachments)
    has_embeds = bool(message.embeds)
    has_stickers = bool(message.stickers)
    has_snapshots = bool(getattr(message, "message_snapshots", None))

    try:
        # ── 情况1: 纯文字消息（无附件、无嵌入、无贴纸、无快照）──
        if not has_attachments and not has_embeds and not has_stickers and not has_snapshots:
            if text_content:
                formatted = f"[{author_name}]: {text_content}"
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=formatted,
                )
                logger.info("转发文字消息成功: %s (ID: %s)", author_name, message.id)
                return True
            else:
                logger.debug("跳过空消息: %s", message.id)
                return False

        sent_something = False

        # ── 情况2: 带附件的消息 ──
        if has_attachments:
            for idx, attachment in enumerate(message.attachments):
                # 为第一个附件附带文字内容作为 caption
                caption = f"[{author_name}]: {text_content}" if (idx == 0 and text_content) else None
                # 如果没有文字内容，至少标注来源
                if caption is None and idx == 0:
                    caption = f"[{author_name}]"

                # 下载附件
                file_data = await _download_attachment(attachment.url)
                if file_data is None:
                    logger.warning("跳过下载失败的附件: %s", attachment.filename)
                    continue

                content_type = attachment.content_type or ""

                if content_type.startswith("image/"):
                    # 图片 → send_photo
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHAT_ID,
                        photo=io.BytesIO(file_data),
                        caption=caption,
                    )
                    logger.info("转发图片成功: %s (%s)", attachment.filename, author_name)
                else:
                    # 其他文件 → send_document
                    await bot.send_document(
                        chat_id=TELEGRAM_CHAT_ID,
                        document=io.BytesIO(file_data),
                        filename=attachment.filename,
                        caption=caption,
                    )
                    logger.info("转发文件成功: %s (%s)", attachment.filename, author_name)

                sent_something = True

        # ── 情况3: Discord 新版转发消息（message_snapshots）──
        if has_snapshots:
            result = await _forward_snapshots(message, author_name)
            if result:
                sent_something = True

        # ── 情况4: 嵌入内容（转发消息、链接预览等）──
        if has_embeds:
            result = await _forward_embeds(
                message.embeds, author_name, text_content,
                already_sent_header=sent_something,
            )
            if result:
                sent_something = True

        # ── 情况5: 贴纸 ──
        if has_stickers and not sent_something:
            sticker = message.stickers[0]
            sticker_text = f"[{author_name}]: [贴纸: {sticker.name}]"
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=sticker_text,
            )
            logger.info("转发贴纸成功: %s (%s)", sticker.name, author_name)
            sent_something = True

        # ── 兜底: 如果以上都没有发送，尝试发送纯文字 ──
        if not sent_something and text_content:
            formatted = f"[{author_name}]: {text_content}"
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=formatted,
            )
            logger.info("转发文字消息成功（兜底）: %s (ID: %s)", author_name, message.id)
            sent_something = True

        if not sent_something:
            logger.warning("消息无可转发内容 (ID: %s, 类型: %s)", message.id, message.type)
            return False

        return True

    except Exception as e:
        logger.error("转发消息失败 (ID: %s): %s", message.id, e, exc_info=True)
        return False


# ── 本地文件上传 ────────────────────────────────────────

async def send_local_file(filepath: str, chat_id: str, max_retries: int = 3) -> bool:
    """
    将本地文件发送到指定的 Telegram 群组。
    自动通过扩展名判断是作为图片(photo)还是普通文件(document)发送。
    网络失败时自动重试，最多重试 max_retries 次。
    """
    import os
    import asyncio
    if not os.path.isfile(filepath):
        logger.error("文件不存在: %s", filepath)
        return False
        
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    is_image = ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    
    for attempt in range(1, max_retries + 1):
        try:
            with open(filepath, 'rb') as f:
                if is_image:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=f"[自动上传] {filename}",
                        read_timeout=120,
                        write_timeout=120,
                    )
                    logger.info("本地图片上传成功: %s", filename)
                else:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=filename,
                        caption=f"[自动上传] {filename}",
                        read_timeout=120,
                        write_timeout=120,
                    )
                    logger.info("本地文件上传成功: %s", filename)
            return True
        except Exception as e:
            if attempt < max_retries:
                wait_time = attempt * 10  # 第1次等10秒，第2次等20秒
                logger.warning(
                    "本地文件上传失败 (%s)，第 %d/%d 次尝试，%d 秒后重试: %s",
                    filename, attempt, max_retries, wait_time, e
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "本地文件上传最终失败 (%s)，已重试 %d 次: %s",
                    filepath, max_retries, e, exc_info=True
                )
                return False

"""
配置加载模块
从 .env 文件或系统环境变量中读取所有配置项，并进行类型转换和校验。
"""

import os
import sys
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()


def _require(name: str) -> str:
    """获取必填环境变量，缺失时终止程序并给出提示。"""
    value = os.getenv(name)
    if not value:
        print(f"[错误] 缺少必填环境变量: {name}，请在 .env 文件中配置。")
        sys.exit(1)
    return value


# ── Discord 转发开关 ──────────────────────────────────────
# True = 启用 Discord 消息转发功能；False = 仅运行其他后台任务（如本地监控）
ENABLE_DISCORD_FORWARDING: bool = os.getenv(
    "ENABLE_DISCORD_FORWARDING", "True"
).strip().lower() in ("true", "1", "yes")

# ── Discord 配置（仅当 ENABLE_DISCORD_FORWARDING 为 True 时必填）──
if ENABLE_DISCORD_FORWARDING:
    DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
    DISCORD_CHANNEL_ID: int = int(_require("DISCORD_CHANNEL_ID"))
else:
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    _channel_id_raw = os.getenv("DISCORD_CHANNEL_ID", "")
    DISCORD_CHANNEL_ID: int = int(_channel_id_raw) if _channel_id_raw else 0

# ── Telegram 配置（始终必填）────────────────────────────
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

# ── 可选配置 ──────────────────────────────────────────────
PROXY_URL: str | None = os.getenv("PROXY_URL") or None
BACKFILL_DELAY: float = float(os.getenv("BACKFILL_DELAY", "1.0"))

# ── 故障重试配置 ──────────────────────────────────────────
# 后台重试任务的扫描间隔（秒），默认 300 秒（5 分钟）
RETRY_INTERVAL: float = float(os.getenv("RETRY_INTERVAL", "300.0"))

# ── 监控上传配置 ──────────────────────────────────────────
MONITOR_FOLDER_PATH: str | None = os.getenv("MONITOR_FOLDER_PATH") or None
MONITOR_INTERVAL: float = float(os.getenv("MONITOR_INTERVAL", "60.0"))
# 如果没有独立设置监控的TG群ID，默认使用主发TG群ID
MONITOR_TG_CHAT_ID: str = os.getenv("MONITOR_TG_CHAT_ID") or TELEGRAM_CHAT_ID

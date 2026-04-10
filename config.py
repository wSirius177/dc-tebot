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


# ── 必填配置 ──────────────────────────────────────────────
DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
DISCORD_CHANNEL_ID: int = int(_require("DISCORD_CHANNEL_ID"))
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

# ── 可选配置 ──────────────────────────────────────────────
PROXY_URL: str | None = os.getenv("PROXY_URL") or None
BACKFILL_DELAY: float = float(os.getenv("BACKFILL_DELAY", "1.0"))

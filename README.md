# Discord → Telegram 消息转发机器人

将指定 Discord 频道的消息实时转发到 Telegram 群组。支持文字、图片、文件附件的转发，具备断线补发和状态记忆能力。

## ✨ 功能特性

- 📡 **实时转发** — 监听 Discord 频道消息，即时转发到 Telegram
- 📎 **多类型支持** — 文字、图片、文件、嵌入内容、贴纸均可转发
- 📂 **文件夹监控** — 自动监控本地文件夹新文件并上传到 Telegram
- 📦 **自动归档** — 文件上传成功后自动移动到 `uploaded` 子目录，方便清理
- 🔄 **断线补发** — 程序重启后自动补发遗漏的消息
- 💾 **状态记忆** — SQLite 持久化存储同步位置（双数据库隔离）
- 🌐 **代理支持** — 通过 HTTP 代理连接 Telegram API
- 🔌 **自动重连** — Discord 断线后自动重连
- 📝 **日志记录** — 控制台 + 文件双重日志
- 🐳 **Docker 支持** — 一键部署，无需配置 Python 环境

## 📋 前置条件

- **Docker**（推荐）或 **Python 3.10+**
- **Discord 机器人令牌** — 在 [Discord 开发者后台](https://discord.com/developers/applications) 创建
- **Telegram 机器人令牌** — 通过 [@BotFather](https://t.me/BotFather) 创建

## 🤖 Discord 机器人设置

1. 前往 [Discord 开发者后台](https://discord.com/developers/applications)
2. 创建一个新应用 → 进入 **Bot** 页面
3. 开启以下 **Privileged Gateway Intents**：
   - ✅ **MESSAGE CONTENT INTENT**（必须开启！）
4. 复制 **Bot Token**
5. 使用 OAuth2 URL 将机器人邀请到你的服务器，所需权限：
   - `Read Messages/View Channels`
   - `Read Message History`

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/wSirius177/de-tebot.git
cd de-tebot
```

### 2. 配置环境变量

```bash
cp .env.example .env   # Linux/macOS
copy .env.example .env  # Windows
```

编辑 `.env` 文件，填写你的配置：

```env
DISCORD_TOKEN=你的Discord机器人令牌
DISCORD_CHANNEL_ID=123456789012345678
TELEGRAM_BOT_TOKEN=你的Telegram机器人令牌
TELEGRAM_CHAT_ID=-1001234567890
PROXY_URL=http://127.0.0.1:7890
```

> **说明**：
> - `DISCORD_CHANNEL_ID`: 在 Discord 中右键频道 → 复制频道 ID（需开启开发者模式）
> - `TELEGRAM_CHAT_ID`: 以 `-100` 开头的群组 ID，可通过 [@userinfobot](https://t.me/userinfobot) 获取
> - `PROXY_URL`: 如果不需要代理可留空或删除该行
> 
> **本地文件夹监控（可选）**:
> - `MONITOR_FOLDER_PATH`: 要监控的本地文件夹绝对路径（例如 `D:\images`）。留空则关闭此功能。
> - `MONITOR_INTERVAL`: 扫描频率（秒），默认 `60`。
> - `MONITOR_TG_CHAT_ID`: 监控文件上传到的目标群组（不填则使用 `TELEGRAM_CHAT_ID`）。

### 3. 启动运行

#### 方式一：Docker 部署（推荐）

无需安装 Python 环境，只需安装 Docker 即可一键部署。

```bash
# 构建并启动（后台运行）
docker compose up -d --build

# 查看运行日志
docker compose logs -f

# 停止运行
docker compose down
```

> **提示**：
> - 数据库和日志文件会持久化到项目目录下的 `data/` 文件夹中
> - 使用 `--build` 参数会在代码更新后自动重新构建镜像
> - `restart: unless-stopped` 策略确保服务器重启后容器自动恢复运行

#### 方式二：直接运行 Python

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate       # Windows
source venv/bin/activate    # Linux / macOS

# 安装依赖
pip install -r requirements.txt

# 启动
python bot.py
```

启动成功后会看到类似输出：

```
[INFO] Discord → Telegram 转发机器人启动中...
[INFO] Discord 机器人已登录: MyBot (ID: 123456789)
[INFO] 监听频道 ID: 123456789012345678
[INFO] 已连接到频道: #general
```

## 📁 项目结构

```
dctebot/
├── bot.py               # 主入口 — Discord 客户端与监控任务管理
├── folder_monitor.py    # 监控逻辑 — 定期扫描本地文件夹与移动归档
├── forwarder.py         # 转发器 — Telegram 消息/文件发送逻辑
├── config.py            # 配置加载 — 环境变量读取与校验
├── db.py                # 数据库 — Discord 同步状态管理 (sync_data.db)
├── monitor_db.py        # 数据库 — 本地文件上传状态管理 (monitor_data.db)
├── Dockerfile           # Docker 镜像构建文件
├── docker-compose.yml   # Docker Compose 编排文件
├── .env.example         # 环境变量模板
├── requirements.txt     # Python 依赖
└── README.md            # 本文件
```

## ❓ 常见问题

### Q: 启动报错 "缺少必填环境变量"
确保已创建 `.env` 文件并正确填写了所有必填项。

### Q: Discord 消息内容为空
需要在 Discord 开发者后台开启 **MESSAGE CONTENT INTENT**。

### Q: Telegram 发送失败
1. 检查 `TELEGRAM_BOT_TOKEN` 是否正确
2. 确认机器人已被加入目标群组并设为管理员
3. 如果在国内，确认 `PROXY_URL` 配置正确

### Q: 补发消息过多导致 Telegram 限流
调大 `.env` 中的 `BACKFILL_DELAY` 值（默认 1 秒），例如设为 `2.0`。

## 📄 许可证

MIT License

# 更新日志 (Changelog)

## [v1.2.0] - 2026-04-20
### 新增 (Features)
- **Discord 转发功能开关**：新增 `ENABLE_DISCORD_FORWARDING` 环境变量（True/False）。设为 False 时程序不再启动 Discord 客户端，仅运行本地文件夹监控等后台任务，解耦了 Discord 转发与其他功能的强绑定关系。
- **转发失败自动重试系统**：新增 `failed_tasks` 数据库表，转发失败的消息会被自动记录。后台 `retry_loop` 任务每隔 `RETRY_INTERVAL`（默认 300 秒 / 5 分钟，可在 `.env` 中自定义）扫描一次失败记录并自动重试。成功后自动清除记录，累计失败超过 10 次的消息将放弃重试以防死循环。
- **独立运行模式**：当 Discord 转发关闭时，程序通过 `asyncio.run()` 独立运行后台任务（文件监控、故障重试），不再依赖 Discord 事件循环。

### 优化 (Enhancements)
- **附件下载超时调大**：`_download_attachment` 的超时时间从 60 秒提升至 120 秒，大幅降低 10-20MB 大图在网络波动时下载超时的概率。
- **归档失败自动补做**：本地文件上传成功但移动到 `uploaded/` 文件夹失败时（如文件被占用），下一轮扫描会自动重试移动操作而不再重复上传，彻底杜绝重复上传问题。
- **配置项解耦**：Discord Token 和频道 ID 改为条件必填（仅 `ENABLE_DISCORD_FORWARDING=True` 时必填），Telegram 配置始终必填。

## [v1.1.2] - 2026-04-17
### 修复 (Bug Fixes)
- **修复代理参数兼容性错误**：针对新版 `python-telegram-bot` 支持的 httpx 更新，修正了 `forwarder.py` 内部 `HTTPXRequest` 代理传参错误的问题，将 `proxy_url` 参数更改回 `proxy` 从而修复无法启动抛出 `TypeError: HTTPXRequest.__init__() got an unexpected keyword argument 'proxy_url'` 的异常报错。

## [v1.1.1] - 2026-04-17
### 优化 (Enhancements)
- **增加大文件长连接支持**：Telegram Bot HTTPX 请求的读写超时时间（`read_timeout` / `write_timeout`）从默认设置分别提高到了 120 秒，显著降低由于代理网络波动或上传大体积文件导致的 `httpx.ReadTimeout` 报错。
- **自动恢复重试机制**：为本地文件夹上传功能（`send_local_file`）新增了失败自动重试机制。当遇到网络断流或超时，不再直接跳过文件，而是进行最多 3 次递增延时（10秒、20秒）的自动重试操作，极大地提高了上传稳定性。

## [v1.1.0] - 2026-04-17
### 新增 (Features)
- **本地文件夹智能监控**：新增自动侦测指定本地目录文件变动功能。将文件拖入设定目录后，机器人会在后台自动扫描并推送至目标 TG 群组。
- **物理自动归档防误删**：被成功推送到 Telegram 的文件，会自动于本地路径下物理转移至隔离的 `uploaded/` 分类文件夹内，方便未来安心清空，绝不重复上传及防止误删正在排队的文件。
- **配置与数据双隔离**：为文件监控设定独立的新 SQLite 数据库（`monitor_data.db`）专门留存该状态，绝不干扰由 Discord 触发的核心转发任务逻辑；加入了 `MONITOR_FOLDER_PATH`、`MONITOR_INTERVAL` 与专属频道 `MONITOR_TG_CHAT_ID` 等可选变量。

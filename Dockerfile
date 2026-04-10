# 使用 Python 3.12 精简版镜像，体积更小
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置 Python 环境变量：
#   PYTHONDONTWRITEBYTECODE=1  不生成 .pyc 文件
#   PYTHONUNBUFFERED=1         日志实时输出，不缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_DIR=/app/data

# 先复制依赖文件，利用 Docker 缓存层加速构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码
COPY bot.py config.py db.py forwarder.py ./

# 创建数据目录（用于挂载持久化数据卷）
RUN mkdir -p /app/data

# 启动机器人
CMD ["python", "bot.py"]

"""
本地文件夹监控模块
定期扫描指定文件夹，自动上传新文件并将其移动到 uploaded 子文件夹。
"""

import os
import asyncio
import logging
import shutil

from config import MONITOR_FOLDER_PATH, MONITOR_INTERVAL, MONITOR_TG_CHAT_ID
from monitor_db import is_file_uploaded, mark_file_uploaded, init_monitor_db
from forwarder import send_local_file

logger = logging.getLogger(__name__)

async def monitor_loop():
    """
    后台任务协程：定期检查指定文件夹里的新文件。
    该任务是设计为永远运行的无阻塞循环。
    """
    if not MONITOR_FOLDER_PATH:
        logger.info("未配置 MONITOR_FOLDER_PATH，本地监控功能已禁用。")
        return
        
    if not os.path.exists(MONITOR_FOLDER_PATH):
        logger.warning("配置的监控文件夹不存在: %s，监控功能暂时挂起。", MONITOR_FOLDER_PATH)
        # 不退出循环，可能用户之后会创建这个文件夹
    
    # 确保监控专用数据库已经初始化
    init_monitor_db()
    
    # 构建 uploaded 文件夹的绝对路径
    uploaded_dir = os.path.join(MONITOR_FOLDER_PATH, "uploaded")
    
    logger.info("本地文件夹监控已启动:")
    logger.info(" - 监控路径: %s", MONITOR_FOLDER_PATH)
    logger.info(" - 归档路径 (上传后移动至此): %s", uploaded_dir)
    logger.info(" - 扫描间隔: %s 秒", MONITOR_INTERVAL)
    logger.info(" - 指定 TG 群组 ID: %s", MONITOR_TG_CHAT_ID)

    while True:
        try:
            # 再次检查文件夹在运行间隙是否被创建或删除
            if os.path.exists(MONITOR_FOLDER_PATH):
                # 确保每次运行都存在 uploaded 文件夹
                if not os.path.exists(uploaded_dir):
                    os.makedirs(uploaded_dir, exist_ok=True)
                    
                # 遍历当前目录的文件（浅层扫描，不深入子文件夹去避免逻辑复杂度，或者我们排除 uploaded 文件夹）
                for entry in os.listdir(MONITOR_FOLDER_PATH):
                    full_path = os.path.join(MONITOR_FOLDER_PATH, entry)
                    
                    # 忽略文件夹（包含我们的 uploaded 子目录自身）
                    if not os.path.isfile(full_path):
                        continue
                        
                    # 检查数据库是否标记过已上传
                    if is_file_uploaded(entry):
                        # 文件已上传过但仍在原位 → 说明上次移动（归档）失败了
                        # 仅重试移动操作，不再重复上传
                        target_path = os.path.join(uploaded_dir, entry)
                        try:
                            if os.path.exists(target_path):
                                os.remove(target_path)
                            shutil.move(full_path, target_path)
                            logger.info("补做归档成功（上次移动失败的遗留文件）: %s", entry)
                        except Exception as move_err:
                            logger.debug("补做归档仍失败 (%s)，文件可能仍被占用: %s", entry, move_err)
                        continue
                        
                    logger.info("发现新文件，准备上传: %s", entry)
                    
                    # 执行上传
                    success = await send_local_file(full_path, MONITOR_TG_CHAT_ID)
                    
                    if success:
                        # 在数据库中标示
                        mark_file_uploaded(entry)
                        
                        # 物理移动文件以防止意外删除或后续扫描干扰
                        target_path = os.path.join(uploaded_dir, entry)
                        try:
                            # 如果目标文件已存在（可能由于重名），尝试覆盖或重命名
                            if os.path.exists(target_path):
                                os.remove(target_path)
                            shutil.move(full_path, target_path)
                            logger.info("文件已成功归档到 uploaded 文件夹: %s", entry)
                        except Exception as move_err:
                            logger.error("文件移动失败 (%s)，下一轮扫描将自动重试归档: %s", entry, move_err)
                            
        except Exception as e:
            logger.error("监控扫描任务出现异常: %s", e, exc_info=True)
            
        # 等待下一轮扫描
        await asyncio.sleep(MONITOR_INTERVAL)

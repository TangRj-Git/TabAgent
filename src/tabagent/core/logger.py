import sys

from loguru import logger

from tabagent.core.config import log_config

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>PID:{process.id}</magenta> | "
    "<blue>{thread.name}</blue> | "
    "<cyan>{name}:{function}</cyan>:<yellow>{line}</yellow> | "
    "<level>{message}</level>"
)

# 移除默认输出，避免重复记录。
logger.remove()

# 设置日志等级对应的颜色。
# <level> 会根据当前日志等级使用对应颜色。
logger.level("TRACE", color="<cyan>")
logger.level("DEBUG", color="<blue>")
logger.level("INFO", color="<white>")
logger.level("SUCCESS", color="<bold><green>")
logger.level("WARNING", color="<bold><yellow>")
logger.level("ERROR", color="<bold><red>")
logger.level("CRITICAL", color="<bold><white><RED>")

# 获取控制台和文件配置。
console_config = log_config.console
file_config = log_config.file

# 控制台输出。
if console_config.enable:
    logger.add(
        sys.stderr,
        level=console_config.level,
        format=LOG_FORMAT,
        colorize=console_config.colorize,
        enqueue=console_config.enqueue,
        backtrace=console_config.backtrace,
        diagnose=console_config.diagnose,
    )

# 文件输出。
if file_config.enable:
    logger.add(
        file_config.path,
        level=file_config.level,
        format=LOG_FORMAT,
        colorize=file_config.colorize,
        encoding=file_config.encoding,
        rotation=file_config.rotation,
        retention=file_config.retention,
        enqueue=file_config.enqueue,
        backtrace=file_config.backtrace,
        diagnose=file_config.diagnose,
    )

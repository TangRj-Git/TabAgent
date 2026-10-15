from tabagent.core.logger import logger


def test_logger() -> None:
    # 默认配置下，只写入日志文件。
    logger.debug("Tool registered: {}.", "add")

    # 默认配置下，同时输出到控制台和文件。
    logger.info("Agent run started.")
    logger.success("Agent run completed.")
    logger.warning("The model call limit is approaching.")
    logger.error("Tool execution failed.")

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LogConfig:
    """统一管理日志输出配置。"""

    @dataclass
    class Console:
        """控制台日志配置。"""

        # 是否启用控制台输出。
        enable: bool = True

        # 最低输出等级。
        level: str = "INFO"

        # 是否启用彩色输出。
        colorize: bool = True

        # 使用队列，由后台线程处理日志写入。
        enqueue: bool = True

        # 是否扩展异常捕获点之前的调用栈。
        backtrace: bool = False

        # 是否在异常日志中展开局部变量值。
        diagnose: bool = False

    @dataclass
    class File:
        """文件日志配置。"""

        # 是否启用文件输出。
        enable: bool = True

        # 最低输出等级。
        level: str = "DEBUG"

        # 根据当前目录结构，保存到项目根目录下的 logs 文件夹。
        path: str = str(
            Path(__file__).resolve().parents[3]
            / "logs"
            / "tabagent.log"
        )

        # 单个日志文件的轮转阈值。
        rotation: str = "10 MB"

        # 旧日志文件的保留期限，在轮转时检查清理。
        retention: str = "7 days"

        # 文件编码。
        encoding: str = "utf-8"

        # 文件中不写入颜色控制字符。
        colorize: bool = False

        # 使用队列，由后台线程处理日志写入。
        enqueue: bool = True

        # 是否扩展异常捕获点之前的调用栈。
        backtrace: bool = False

        # 是否在异常日志中展开局部变量值。
        diagnose: bool = False

    # 每个 LogConfig 实例拥有独立的子配置。
    console: Console = field(default_factory=Console)
    file: File = field(default_factory=File)


# 统一的日志配置实例。
log_config = LogConfig()

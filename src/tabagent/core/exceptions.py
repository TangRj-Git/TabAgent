"""
TabAgent 的自定义异常。

异常类负责区分错误类型。
是否终止运行、回传给模型或进行其他处理，由捕获异常的代码决定。
"""


class TabAgentError(Exception):
    """TabAgent 自定义异常的基类。"""


# Agent 配置与运行限制。

class AgentConfigError(TabAgentError):
    """Agent 配置无效，例如模型名称为空、调用次数上限不合法。"""


class ModelCallLimitError(TabAgentError):
    """达到模型调用次数上限，但任务仍需要继续调用工具。"""


# 模型响应相关错误。

class ModelError(TabAgentError):
    """模型相关错误的基类。"""

    def __init__(self, message: str, *, details: object = None) -> None:
        super().__init__(message)
        # 保留服务端原始数据，避免将未受控语言的内容混入英文错误说明。
        self.details = details


class ModelResponseFailedError(ModelError):
    """模型返回 response.failed，表示本次响应失败。"""


class ModelResponseIncompleteError(ModelError):
    """模型返回 response.incomplete，表示本次响应未完整生成。"""


class ModelStreamError(ModelError):
    """流中出现错误，或流结束时没有收到预期的完成事件。"""


# 工具相关错误。

class ToolError(TabAgentError):
    """工具相关错误的基类。"""


class ToolRegistrationError(ToolError):
    """工具注册失败，例如名称重复或参数定义不受支持。"""


class ToolNotFoundError(ToolError):
    """请求的工具不存在，或不在本次运行提供的工具范围内。"""


class ToolArgumentsError(ToolError):
    """工具调用参数无效，例如 JSON 格式错误、缺少参数。"""


class ToolExecutionError(ToolError):
    """工具函数在执行过程中发生异常。"""


class ToolResultSerializationError(ToolError):
    """工具已经返回结果，但结果无法转换为约定的输出格式。"""

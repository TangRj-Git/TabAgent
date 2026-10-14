from typing import Any, TypeAlias, Union

from openai.types.responses import (
    ResponseReasoningItem,
    ResponseOutputMessage,
    ResponseFunctionToolCall,
)

# - ResponseReasoningItem：推理上下文。
# - ResponseOutputMessage：assistant 消息，包含文本或拒绝说明。
# - ResponseFunctionToolCall：模型发起的函数调用。
AssistantOutputItem: TypeAlias = Union[
    ResponseReasoningItem,
    ResponseOutputMessage,
    ResponseFunctionToolCall,
]


class Message(dict[str, Any]):
    """
    消息基类。

    消息本身就是字典，可以直接放入 Responses API 的 input 列表。
    不同消息的字段和内容结构不同，因此字典的值类型使用 Any。
    """


class SystemMessage(Message):
    """系统消息，用于设置模型的身份、回答方式和行为要求。"""

    def __init__(self, content: str) -> None:
        super().__init__(
            role="system",
            content=content,
        )


class UserMessage(Message):
    """用户消息，当前仅支持字符串形式的文本输入。"""

    def __init__(self, content: str) -> None:
        super().__init__(
            role="user",
            content=content,
        )


class AssistantMessage(Message):
    """
    包装 response.output 中的单个模型输出项。

    保留文本消息、函数调用或推理项的原始结构，
    以便在后续请求中作为历史上下文再次发送。

    一轮 response.output 可能包含多个输出项，
    应分别创建 AssistantMessage，并按原顺序加入历史。
    """

    def __init__(self, item: AssistantOutputItem) -> None:
        super().__init__(
            item.model_dump(
                # 转换成 JSON 兼容的 Python 数据，返回值仍是字典。
                mode="json",

                # 使用 API 字段名，例如将 Python 的 async_ 输出为 async。
                by_alias=True,

                # 省略未显式设置的字段，避免额外填入默认值。
                exclude_unset=True,
            )
        )


class ToolMessage(Message):
    """
    function 工具调用的执行结果。

    使用 Responses API 的 function_call_output 格式，
    通过 call_id 与模型发起的函数调用关联。
    """

    def __init__(
            self,
            *,
            call_id: str,
            output: str,
    ) -> None:
        """
        Args:
            call_id:
                模型返回的 ResponseFunctionToolCall.call_id，
                注意不是该输出项的 id。

            output:
                工具执行结果的字符串。
                如果结果是字典或列表，应先用 json.dumps() 序列化。
        """
        super().__init__(
            type="function_call_output",
            call_id=call_id,
            output=output,
        )

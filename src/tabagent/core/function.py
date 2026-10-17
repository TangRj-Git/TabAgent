from typing import Any, Optional

# 函数工具定义模板

TOOL_TEMPLATE = {
    # 工具种类，固定为 "function"
    "type": "function",

    # 工具名称，用于识别和调用对应函数
    "name": "search_items",

    # 工具说明：描述用途、适用场景和返回内容
    "description": "根据关键词搜索内容，返回匹配项及其数量。",

    # 输入参数的 JSON Schema
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用于搜索的关键词。",
            },
            "limit": {
                "type": "integer",
                "description": "最多返回的匹配项数量。",
                "minimum": 1,
            },
        },

        # 必须提供的参数
        "required": ["query", "limit"],

        # 不允许传入未声明的参数
        "additionalProperties": False,
    },

    # 是否严格约束模型生成的调用参数
    "strict": True,

    # 可选：描述工具结果字符串中编码的 JSON 数据结构
    "output_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "搜索得到的匹配项。",
                "items": {
                    "type": "string",
                },
            },
            "count": {
                "type": "integer",
                "description": "实际返回的匹配项数量。",
            },
        },
        "required": ["items", "count"],
        "additionalProperties": False,
    },
}


class Function(dict[str, Any]):
    """
    提供给模型的函数工具定义，可以直接放入 Responses API 的 tools。

    这里只描述工具名称、用途以及参数格式。
    工具对应的 Python 函数需要由 Agent 另外注册和执行。
    """

    def __init__(
            self,
            *,
            name: str,
            description: Optional[str] = None,
            parameters: Optional[dict[str, Any]] = None,
            strict: bool = True,
            output_schema: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Args:
            name:
                工具名称。模型发起 function_call 时通过 name 指定工具。

            description:
                工具用途说明，帮助模型判断何时调用以及如何使用。

            parameters:
                工具输入参数的 JSON Schema，不是调用时的实际参数值。

            strict:
                是否要求模型生成的调用参数符合指定的 JSON Schema。
                这个设置不会替你执行本地参数校验或调用 Python 函数。

            output_schema:
                工具结果字符串中 JSON 数据的结构说明。
                如果工具只返回普通文本，可以不提供。
        """
        super().__init__(
            type="function",
            name=name,
            description=description,
            parameters=parameters,
            strict=strict,
        )

        if output_schema is not None:
            self["output_schema"] = output_schema

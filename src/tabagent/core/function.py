from typing import Any


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
            description: str | None = None,
            parameters: dict[str, Any],
            strict: bool = True,
            output_schema: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            name:
                工具名称。模型发起 function_call 时通过 name 指定工具。

            parameters:
                工具输入参数的 JSON Schema，不是调用时的实际参数值。

            description:
                工具用途说明，帮助模型判断何时调用以及如何使用。

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
            parameters=parameters,
            strict=strict,
        )

        # 未提供的可选字段不写入请求字典。
        if description is not None:
            self["description"] = description

        if output_schema is not None:
            self["output_schema"] = output_schema

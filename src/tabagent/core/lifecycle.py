from openai.types.responses import Response, ResponseFunctionToolCall

from tabagent.core.message import Message


class AgentLifecycle:
    """
    Agent 执行过程中的生命周期钩子。

    所有钩子默认不执行任何操作。
    子类只需要重写自己关心的方法。

    这些方法需要由 Agent 在对应位置显式 await 调用，
    不会因为继承这个类而自动触发。
    """

    async def before_agent(
            self,
            messages: list[Message],
    ) -> None:
        """
        一次 Agent 执行开始时调用。

        此时 messages 已包含用户本次输入，
        还没有发起本次任务的第一次模型请求。
        """
        pass

    async def after_agent(
            self,
            messages: list[Message],
    ) -> None:
        """
        一次 Agent 执行正常完成后调用。

        此时最终模型输出已经加入 messages，
        并且没有待执行的工具调用。
        """
        pass

    async def before_model(
            self,
            messages: list[Message],
            *,
            round_number: int,
    ) -> None:
        """
        每次模型请求之前调用。

        messages 是即将发送给模型的历史消息。
        round_number 是本次 Agent 执行中的模型调用轮次，从 1 开始。
        """
        pass

    async def after_model(
            self,
            response: Response,
            *,
            round_number: int,
    ) -> None:
        """
        每次模型响应成功完成、流读取结束后调用。

        response 是完整响应，可以读取 output、usage 等信息。
        这里约定在模型输出写入历史之前调用。
        """
        pass

    async def before_tool(
            self,
            call: ResponseFunctionToolCall,
    ) -> None:
        """
        执行单个工具调用之前调用。

        call 包含工具名称、参数 JSON 字符串和 call_id。
        """
        pass

    async def after_tool(
            self,
            call: ResponseFunctionToolCall,
            output: str,
    ) -> None:
        """
        单个工具调用得到输出字符串后调用。

        output 是准备交给模型的工具结果。
        根据当前执行器的实现，它也可能是错误信息的 JSON 字符串。
        """
        pass

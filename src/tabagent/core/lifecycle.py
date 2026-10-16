class AgentLifecycle:
    """
    Agent 执行过程中的生命周期钩子。

    所有钩子默认不执行任何操作，子类可以按需重写。
    这些方法需要由 Agent 在对应位置显式 await 调用，
    不会因为继承这个类而自动触发。
    """

    async def before_agent(self) -> None:
        """
        一次 Agent 执行开始时调用。

        此时尚未发起本次任务的第一次模型请求。
        """
        pass

    async def after_agent(self) -> None:
        """
        一次 Agent 执行正常完成后调用。

        此时最终模型输出已经加入历史消息，
        并且没有待执行的工具调用。
        异常退出或取消执行时，不属于正常完成。
        """
        pass

    async def before_model(self) -> None:
        """
        每次模型请求发起之前调用。

        一次 Agent 执行可能包含多次模型请求，
        每次请求都会经过这个钩子。
        """
        pass

    async def after_model(self) -> None:
        """
        每次模型响应成功完成、流读取结束后调用。

        此时已经获得完整响应。
        约定在本轮模型输出写入历史消息之前调用。
        """
        pass

    async def before_tool(self) -> None:
        """
        执行单个工具调用之前调用。

        一轮模型响应可能包含多个工具调用，
        每个工具调用执行前都会经过这个钩子。
        """
        pass

    async def after_tool(self) -> None:
        """
        单个工具调用得到输出字符串后调用。

        输出可以是正常的工具执行结果，
        也可以是执行器捕获异常后生成的错误信息。
        """
        pass

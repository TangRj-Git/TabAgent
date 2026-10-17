from collections.abc import AsyncGenerator
from typing import cast

from openai import AsyncOpenAI, omit
from openai.types.responses import (
    ResponseInputParam,
    ResponseStreamEvent,
    ToolParam,
)

from tabagent.core.function import Function
from tabagent.core.message import Message
from tabagent.llm.base_llm import BaseLLM


class OpenAILLM(BaseLLM):
    """基于 OpenAI Responses API 的 LLM 实现。"""

    def __init__(
            self,
            *,
            base_url: str,
            api_key: str,
            timeout: float | None = 60.0,
            max_retries: int = 3,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    async def astream(
            self,
            model: str,
            instructions: str | None = None,
            messages: list[Message] | None = None,
            functions: list[Function] | None = None,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """
        调用模型，并逐个向外传递流式响应事件。

        本方法包含 yield，因此是异步生成器函数。
        调用后返回异步生成器对象，应使用 async for 获取事件，不能直接对该对象使用 await。

        本方法负责请求与流的关闭。
        事件判断、工具执行和历史消息维护由上层负责。

        注意：
            调用方如果提前停止迭代，应主动关闭返回的生成器，例如使用 contextlib.aclosing，确保及时释放响应流。
        """
        # 自定义 Message 是字典类型。
        # cast 只提供类型提示，不转换或校验实际数据。
        # messages 为 None 时，使用 omit 省略 input 参数。
        input_data = (
            cast(ResponseInputParam, messages)
            if messages is not None
            else omit
        )

        # 没有提供函数定义时，省略 tools 参数。
        tool_data = (
            cast(list[ToolParam], functions)
            if functions is not None
            else omit
        )

        # 使用 await 的直接原因，是 create() 是一个不含 yield 的 async def 方法，调用它会得到协程对象。
        #
        # 等待这个协程完成后，得到 AsyncStream[ResponseStreamEvent]。
        stream = await self._client.responses.create(
            model=model,
            instructions=instructions,
            input=input_data,
            tools=tool_data,
            stream=True,
        )

        # 正常读完、发生异常或生成器被关闭时，关闭底层响应流。
        async with stream:
            # 从响应流中逐个读取 ResponseStreamEvent。
            async for event in stream:
                # 将事件交给上层，并暂停当前生成器。
                # 上层继续读取时，从这里恢复执行。
                yield event

    async def aclose(self) -> None:
        """关闭 OpenAI 异步客户端。"""
        await self._client.close()

    async def amodel(self) -> list[str]:
        """获取当前服务通过 models 接口提供的模型名称。"""
        return [
            model.id
            async for model in self._client.models.list()
        ]

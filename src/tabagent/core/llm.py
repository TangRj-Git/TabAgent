from types import TracebackType
from typing import Optional, Self, AsyncGenerator

from openai import AsyncOpenAI
from openai.types.responses import ResponseStreamEvent

from tabagent.core.message import Message
from tabagent.core.function import Function


class TabAgentLLM:
    def __init__(
            self,
            *,
            base_url: str,
            api_key: str,
            timeout: Optional[float] = 60.0,
            max_retries: Optional[int] = 3,
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
            instructions: Optional[str] = None,
            messages: Optional[list[Message]] = None,
            functions: Optional[list[Function]] = None,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """
        调用模型，并逐个向外传递流式响应事件。

        本方法包含 yield，因此是异步生成器函数。
        调用后返回异步生成器对象，应使用 async for 获取事件，不能直接对该对象使用 await。

        注意：
            调用方如果提前停止迭代，应主动关闭返回的生成器，
            例如使用 contextlib.aclosing，确保及时释放响应流。
        """
        # 使用 await 的直接原因，是 create() 是一个不含 yield 的 async def 方法，调用它会得到协程对象。
        stream = await self._client.responses.create(
            model=model,
            instructions=instructions,
            input=messages,
            tools=functions,
            stream=True,
        )

        async with stream:
            async for response in stream:
                yield response

    async def amodel(self) -> list[str]:
        return [
            model.id
            async for model in self._client.models.list()
        ]

    async def aclose(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()

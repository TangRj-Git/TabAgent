from types import TracebackType
from typing import Optional, Self, AsyncIterator

from openai import AsyncOpenAI
from openai.types.responses import ResponseStreamEvent

from tabagent.core.message import Message
from tabagent.core.function import Function


class TabAgentLLM:
    def __init__(
            self,
            *,
            provider: Optional[str] = None,
            base_url: Optional[str] = None,
            api_key: Optional[str] = None,
            timeout: Optional[float] = 60.0,
            max_retries: Optional[int] = 3,
    ) -> None:
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = AsyncOpenAI(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    async def astream(
            self,
            model: Optional[str] = None,
            instructions: Optional[str] = None,
            messages: Optional[list[Message]] = None,
            tools: Optional[list[Function]] = None,
    ) -> AsyncIterator[ResponseStreamEvent]:
        stream = await self._client.responses.create(
            model=model,
            instructions=instructions,
            input=messages,
            tools=tools,
            stream=True,
        )

        async with stream:
            async for response in stream:
                yield response

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

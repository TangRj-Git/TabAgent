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
    ) -> AsyncIterator[ResponseStreamEvent]:
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

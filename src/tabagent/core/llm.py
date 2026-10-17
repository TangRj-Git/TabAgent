from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from tabagent.core.exceptions import AgentConfigError
from tabagent.core.function import Function
from tabagent.core.message import Message
from tabagent.llm.base_llm import BaseLLM
from tabagent.llm.llm_adapter import create_llm_adapter


class TabAgentLLM(BaseLLM):
    """
    Agent 使用的统一 LLM 入口。

    根据 provider，通过工厂函数创建对应的底层 LLM 实例，并将模型调用、模型列表查询和关闭操作转交给该实例。

    具体实现的选择逻辑由 llm_adapter 中的工厂函数负责。

    异步上下文管理方法继承自 BaseLLM。
    """

    def __init__(
            self,
            *,
            base_url: str,
            api_key: str,
            provider: str = "openai",
            timeout: float | None = 60.0,
            max_retries: int = 3,
    ) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise AgentConfigError(
                "provider must be a non-empty string."
            )

        self.provider = provider.strip().lower()
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

        # provider 已在当前入口完成校验与规范化。
        # 通过工厂函数选择并创建具体的 LLM 实例。
        # 创建 SDK 客户端所需的参数交给具体实现处理。
        self._backend: BaseLLM = create_llm_adapter(
            provider=self.provider,
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
    ) -> AsyncGenerator[Any, None]:
        """
        统一的模型流式调用入口。

        将模型名称、指令、消息和函数定义，传递给初始化时选定的底层 LLM 实现。

        底层产生的事件逐个交给上层 Agent 或模型中间件。
        具体的 API 请求、参数适配和响应解析由底层实现负责。
        """

        # 当前入口退出时，同时关闭下层生成器，使底层实现能够执行清理，释放本次请求占用的流资源。
        async with aclosing(
                self._backend.astream(
                    model=model,
                    instructions=instructions,
                    messages=messages,
                    functions=functions,
                )
        ) as stream:
            async for event in stream:
                yield event

    async def aclose(self) -> None:
        """关闭当前入口创建的底层 LLM 实例。"""
        await self._backend.aclose()

    async def amodel(self) -> list[str]:
        """通过底层实现获取可用模型列表。"""
        return await self._backend.amodel()

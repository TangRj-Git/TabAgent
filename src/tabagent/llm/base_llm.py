from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any, Self

from tabagent.core.exceptions import ModelError
from tabagent.core.function import Function
from tabagent.core.message import Message


class BaseLLM(ABC):
    """
    LLM 接口基类。

    输入沿用项目的 Message 和 Function 定义，输出事件的具体类型由实现类决定。

    子类负责具体的 API 请求、必要的数据转换，
    以及客户端资源管理。
    """

    @abstractmethod
    def astream(
            self,
            model: str,
            instructions: str | None = None,
            messages: list[Message] | None = None,
            functions: list[Function] | None = None,
    ) -> AsyncGenerator[Any, None]:
        """
        返回模型响应的异步生成器。

        具体事件类型由实现类决定。
        调用方使用 async for 读取事件，提前停止读取时，应主动关闭生成器。

        基类使用 def 声明返回异步生成器的接口；子类可以使用 async def 和 yield 实现。
        """
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """关闭当前实例管理的客户端资源。"""
        ...

    async def amodel(self) -> list[str]:
        """
        获取可用模型列表。

        支持该能力的子类应覆盖此方法。
        未实现时，明确报告当前实现不支持模型列表查询。
        """
        raise ModelError(
            "Listing models is not supported by this LLM implementation."
        )

    async def __aenter__(self) -> Self:
        """进入异步上下文，返回当前实例。"""
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        """
        退出异步上下文时关闭客户端资源。

        返回 None，不抑制上下文中发生的异常。
        """
        await self.aclose()

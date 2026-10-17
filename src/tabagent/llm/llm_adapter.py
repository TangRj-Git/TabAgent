from tabagent.core.exceptions import AgentConfigError
from tabagent.llm.base_llm import BaseLLM
from tabagent.llm.openai_llm import OpenAILLM


def create_llm_adapter(
        *,
        provider: str,
        base_url: str,
        api_key: str,
        timeout: float | None = 60.0,
        max_retries: int = 3,
) -> BaseLLM:
    """
    根据 provider 创建具体的 LLM 实例。

    接收统一入口传入的配置，
    将客户端的创建交给对应的实现类。

    当前支持：
        openai：使用 OpenAI Responses API。
    """
    # 根据 provider 选择具体实现。
    # 创建 SDK 客户端所需的参数交给具体实现处理。
    if provider == "openai":
        return OpenAILLM(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    raise AgentConfigError(
        f"Unsupported LLM provider: {provider!r}. "
        "Supported providers: openai."
    )

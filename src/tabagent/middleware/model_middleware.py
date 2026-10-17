from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
)

from tabagent.core.exceptions import AgentConfigError, ModelError
from tabagent.core.llm import TabAgentLLM
from tabagent.middleware.base_middleware import (
    AppInitHandler,
    AppInitRequest,
    BaseMiddleware,
)


class ModelMiddleware(BaseMiddleware):
    """
    在 App 初始化阶段检查模型服务配置。

    检查内容：
        1. base_url、api_key 和 model 是否为空。
        2. base_url 的基本格式是否正确。
        3. 能否使用当前配置查询模型列表。
        4. 配置的模型是否出现在返回的列表中。

    注意：
        模型列表查询成功，只能确认该接口可访问。
        部分兼容服务的模型列表接口可能不校验 API Key，
        因此不能仅凭查询成功保证生成接口也能正常使用。

        当前策略要求服务支持模型列表查询；
        查询失败或目标模型不在列表中时，会阻止初始化。
    """

    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        # 先检查必需的字符串配置，不发送网络请求。
        for name in ("base_url", "api_key", "model"):
            value = getattr(request, name)

            if not isinstance(value, str) or not value.strip():
                raise AgentConfigError(
                    f"{name} must be a non-empty string."
                )

        # 检查 URL 的基本结构。
        # 这一步不检查网络是否连通，实际连通性由后面的请求确认。
        try:
            parsed_url = urlsplit(request.base_url)
            hostname = parsed_url.hostname

            # 访问 port 属性时，会检查端口格式和范围。
            _ = parsed_url.port

        except ValueError as exc:
            raise AgentConfigError(
                "base_url contains an invalid host or port."
            ) from exc

        if (
                parsed_url.scheme not in {"http", "https"}
                or not hostname
                or any(char.isspace() for char in request.base_url)
        ):
            raise AgentConfigError(
                "base_url must be a valid HTTP or HTTPS URL "
                "without whitespace."
            )

        # 当前初始化请求还没有 LLM 实例，因此创建临时客户端进行检查。
        # provider 的校验与底层实现的选择仍交给 TabAgentLLM。
        # 退出 async with 时，无论查询成功还是失败，都会关闭临时客户端。
        try:
            async with TabAgentLLM(
                    base_url=request.base_url,
                    api_key=request.api_key,
                    provider=request.provider,
                    timeout=request.timeout,
                    max_retries=request.max_retries,
            ) as llm:
                available_models = await llm.amodel()

        # APITimeoutError 属于 APIConnectionError 的子类，
        # 因此需要先捕获超时，再捕获其他连接错误。
        except APITimeoutError as exc:
            raise ModelError(
                "The model list request timed out."
            ) from exc

        except APIConnectionError as exc:
            raise ModelError(
                "Could not connect to the model service. "
                "Check base_url, network access, proxy settings, "
                "and TLS configuration."
            ) from exc

        # 当前底层使用 OpenAI SDK，
        # 服务返回的 HTTP 错误会通过 APIStatusError 向上传递。
        except APIStatusError as exc:
            error_messages = {
                401: (
                    "Authentication failed while listing models. "
                    "Check api_key."
                ),
                403: (
                    "Access to the model list was denied. "
                    "Check account and API key permissions."
                ),
                404: (
                    "The model list endpoint was not found. "
                    "Check base_url and whether the service "
                    "supports listing models."
                ),
                429: (
                    "The model list request was rejected because "
                    "of a rate limit or quota restriction."
                ),
            }

            message = error_messages.get(
                exc.status_code,
                f"The model list request failed with HTTP "
                f"{exc.status_code}.",
            )

            raise ModelError(
                message,
                details={"status_code": exc.status_code},
            ) from exc

        except APIError as exc:
            raise ModelError(
                "An SDK error occurred while querying the model list."
            ) from exc

        # 使用服务返回的模型标识进行精确匹配。
        # 不自动切换模型，避免实际使用的模型与用户配置不一致。
        if request.model not in available_models:
            raise AgentConfigError(
                f"Model {request.model!r} was not found in the "
                "model list returned by this service."
            )

        # 检查通过后，才进入下一层初始化逻辑。
        # 将此调用放在上面的 try/except 之外，
        # 避免把后续初始化异常误报为模型列表查询失败。
        await call_next(request)

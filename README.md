# TabAgent

TabAgent 是一个逐步构建中的 Python Agent harness，通过异步流式模型调用、函数工具和对话历史管理，完成多轮任务执行。中间件已接入 App 初始化、Agent 运行、单次模型调用和单次工具执行，可以在对应过程前后检查参数、调整配置和处理结果。

## 当前功能

| 模块 | 已有能力 |
| --- | --- |
| `TabAgentApp` | 统一接收配置，经过初始化中间件创建 LLM 和 Agent，并管理客户端的关闭 |
| `TabAgentLLM` | 统一 LLM 入口，根据 `provider` 选择底层实现，转发流式调用、模型列表查询和关闭操作 |
| `BaseLLM` / `OpenAILLM` | 定义底层接口；当前由 `OpenAILLM` 调用 OpenAI Responses API |
| `TabAgent` | 输出文本增量，执行模型请求的函数工具，并继续请求模型直到得到最终回答 |
| `BaseMiddleware` / `MiddlewareManager` | 定义四类包装入口，按注册顺序组装中间件调用链 |
| `LoggingMiddleware` | 记录初始化、Agent、模型和工具执行的状态与耗时 |
| `Message` | 组织用户消息、系统消息、模型输出项和工具执行结果 |
| `ToolRegistry` | 注册、查询、删除 Python 函数，生成提供给模型的函数定义 |
| 工具执行器 | 执行同步或异步工具，处理参数解析和结果序列化 |
| 自定义异常 | 区分配置、模型响应、调用次数上限和工具相关错误 |
| 日志 | 使用 Loguru，统一配置控制台和文件输出 |

`AgentLifecycle` 保留了六个生命周期钩子的定义，当前尚未接入执行流程。`middleware/` 中的上下文、记忆、MCP、技能、模型和工具中间件文件仍是占位文件；已经实现并接入的是中间件基类、管理器和可选的日志中间件。

## 安装

需要 Python 3.12 或以上版本，以及 [uv](https://docs.astral.sh/uv/)。项目的 `.python-version` 当前指定 Python 3.12。

在项目根目录执行：

```bash
uv sync --locked
```

该命令根据 `uv.lock` 安装依赖和当前项目，并准备 `.venv` 环境。

## 模型连接配置

示例入口使用 `python-dotenv` 加载项目根目录的 `.env`。需要配置以下三个变量，将占位值替换为自己的服务配置：

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
```

服务需要支持 Responses API 的流式响应；使用工具时还需要支持 function calling。`TabAgentApp` 和 `TabAgentLLM` 通过构造参数接收配置，本身不会自动读取 `.env`。

`provider` 当前只支持 `"openai"`，也是默认值。它用于选择本地的 LLM 实现；仅修改 `base_url` 不会转换请求协议，目标服务仍需支持 Responses API。

## 运行交互示例

```bash
uv run pytest -s test/test_agent.py::test_agent
```

该示例注册了 `add` 和 `multiply` 两个工具，保留多轮对话历史，并逐段打印模型回答。可以依次输入：

```text
先用工具算 12 乘 3，再用工具给结果加 8。
再把刚才的结果乘 2。
exit
```

`exit` 用于结束交互。`-s` 关闭 pytest 的输入输出捕获，使终端能够读取输入并展示流式输出；在 PyCharm 中也需要将 `-s` 加入 pytest 的附加参数。

当前 `uv run tabagent` 对应的命令行入口仍只打印 `Hello from tabagent!`。交互运行请使用上面的示例入口。

## 最小代码示例

下面通过 `TabAgentApp` 统一创建和关闭内部资源，并启用日志中间件。代码可以保存为项目根目录下的 Python 脚本，通过 `uv run python <脚本文件名>.py` 运行：

```python
import asyncio
import os
from contextlib import aclosing

from dotenv import load_dotenv

from tabagent.core.app import TabAgentApp
from tabagent.core.message import Message, UserMessage
from tabagent.middleware.logging_middleware import LoggingMiddleware
from tabagent.tool.registry import ToolRegistry


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def main() -> None:
    load_dotenv()

    registry = ToolRegistry()
    registry.register_tool(multiply)
    messages: list[Message] = [UserMessage("请使用工具计算 12 乘 3。")]

    async with TabAgentApp(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        provider="openai",
        model=os.environ["OPENAI_MODEL"],
        instructions="涉及算术时使用提供的工具，并用中文回答。",
        tool_registry=registry,
        middlewares=(LoggingMiddleware(),),
    ) as app:
        async with aclosing(app.astream(messages=messages)) as stream:
            async for delta in stream:
                print(delta, end="", flush=True)
        print()


if __name__ == "__main__":
    asyncio.run(main())
```

`TabAgentApp.astream()` 转发 Agent 产生的文本片段。Agent 会向传入的 `messages` 列表追加模型输出和工具结果。继续对话时，在同一个 App 上下文中向该列表追加新的 `UserMessage`，再调用 `astream()` 即可，不需要重复保存模型输出。

`async with TabAgentApp(...)` 负责初始化和关闭客户端，`aclosing()` 负责在正常结束、异常或提前停止迭代时关闭本次响应生成器。`astream()` 应使用 `async for` 读取，不能直接 `await`。

一次 Agent 执行默认最多请求模型 10 次，可通过 `max_model_calls` 调整。达到上限且模型仍请求调用工具时，会抛出 `ModelCallLimitError`，最后一轮待调用的工具不会执行。客户端的 `timeout` 默认是 `60.0` 秒，`max_retries` 默认是 `3`。

也可以继续直接组合 `TabAgentLLM` 和 `TabAgent` 使用，参见 [test_agent.py](test/test_agent.py)。这种方式由调用方通过 `async with TabAgentLLM(...)` 管理客户端资源。

## 中间件

通过 `TabAgentApp(middlewares=...)` 注册中间件。自定义中间件继承 `BaseMiddleware`，按需重写下列方法，其余方法默认调用下一层，并原样向外传递结果。

| 方法 | 包围的过程 | 请求中可调整的内容 | 下一层的调用方式 |
| --- | --- | --- | --- |
| `wrap_init` | 创建 LLM 和 Agent | 服务地址、密钥、provider、模型、工具注册表、超时和重试等初始化配置 | `await call_next(request)` |
| `wrap_agent` | 一次完整 Agent 运行 | 消息、已初始化的 LLM、模型、指令、工具注册表和调用次数上限 | `async for` 读取文本片段 |
| `wrap_model` | 单次模型调用 | 本轮消息、模型、指令和函数定义 | `async for` 读取模型事件 |
| `wrap_tool` | 单次工具执行 | 工具名称和已解析的参数字典；`call_id` 应保持不变 | `await call_next(request)` 获取结果字符串 |

注册顺序为 `(A, B)` 时，调用链为 `A(B(实际执行函数))`。如果每层都调用下一层并正常完成，顺序是：A 前置处理 → B 前置处理 → 实际执行 → B 后置处理 → A 后置处理。

流式中间件中，循环内部的代码处理每个片段或事件，循环之后的代码在正常读完流后执行。需要在异常、取消或关闭时也执行的清理逻辑，应放在 `finally` 中，并使用 `aclosing(call_next(request))` 向下传递关闭操作。

Agent 中间件拿到本次运行的工具注册表副本，可以动态注册或删除工具。模型中间件拿到消息和函数定义的深拷贝，临时修改不会直接改动原始历史或注册表。模型中间件只调整发送给模型的函数定义；添加可执行工具应通过 Agent 请求中的工具注册表完成。

`LoggingMiddleware` 已实现上述四种包装，可像最小示例一样直接注册。App 默认的 `middlewares=()` 不启用任何中间件。

## LLM 分层

| 文件 | 职责 |
| --- | --- |
| `core/llm.py` | `TabAgentLLM` 对外提供稳定入口，校验 provider 并转发调用 |
| `llm/base_llm.py` | `BaseLLM` 定义 `astream()`、`aclose()` 和异步上下文管理；`amodel()` 默认报告不支持模型列表查询 |
| `llm/llm_adapter.py` | `create_llm_adapter()` 根据 provider 创建具体实现 |
| `llm/openai_llm.py` | `OpenAILLM` 管理 OpenAI 客户端、发送 Responses 请求并返回原始流式事件 |

新增底层实现时，需要实现 `BaseLLM` 的抽象接口，并在工厂中增加对应的 provider 选择逻辑。当前 Agent 和模型中间件仍按 Responses 事件结构处理输出；新的底层实现也需要适配这一约定。

`TabAgentLLM.astream()` 返回原始模型事件；`TabAgentApp.astream()` 和 `TabAgent.astream()` 返回供调用方展示的文本片段。Agent 在流正常读完并获得成功完成事件后保存完整的模型输出，再执行函数调用并把结果加入下一轮历史。模型失败、不完整响应和缺少完成事件会通过相应异常报告给调用方。

## 工具注册

工具注册方法是同步方法，注册异步函数时也不需要 `await`。`ToolRegistry` 保存 Python 函数及其 `Function` 定义，模型只接收函数定义，实际执行由 Agent 负责。

自动生成参数 Schema 目前采用简单类型映射。对于 `list`、`tuple`、`dict`、`list[int]`、联合类型或复杂嵌套结构，请通过 `register_tool(parameters=...)` 显式提供完整 Schema；当前自动映射不会补齐数组元素和嵌套对象的结构。默认 `strict=True` 时，自动生成的 Schema 会将全部参数列入 `required`，包括带 Python 默认值的参数。

已有的 [calculate_tool.py](src/tabagent/tool/tools/calulate/calculate_tool.py) 提供 `calculate(expression: str)`，支持四则运算、乘方和常见数学函数，可以直接注册使用。`web_search_tool.py` 当前尚未实现。

## 日志配置

配置位于 [config.py](src/tabagent/core/config.py)，由 `log_config.console` 和 `log_config.file` 管理：

| 配置 | 默认值 |
| --- | --- |
| 控制台输出 | 启用，`INFO` 及以上等级，彩色显示 |
| 文件输出 | 启用，`DEBUG` 及以上等级，UTF-8 纯文本 |
| 文件路径 | 源码运行时为项目根目录下的 `logs/tabagent.log` |
| 文件轮转阈值 | `10 MB` |
| 旧文件保留期限 | `7 days`，在轮转时检查清理 |
| 队列写入 | 控制台和文件均启用 |

其他模块直接导入使用：

```python
from tabagent.core.logger import logger

logger.debug("Tool registered: {}.", "multiply")
logger.info("Agent run started.")
```

配置在首次导入日志模块时应用，修改配置后重新启动程序即可生效。日志调用本身不需要 `await`。需要等待队列完成写入时，同步入口调用 `logger.complete()`，异步入口可以使用 `await logger.complete()`。

文件轮转会产生多个日志文件，目录总大小可以超过 10 MB。保留期限按旧文件清理，不是每条日志满七天就立即删除。

## 本地检查与模型调用示例

不调用模型的本地检查：

```bash
uv run pytest -s test/test_function.py test/test_logger.py
```

单独观察底层 LLM 的原始流式事件：

```bash
uv run pytest -s test/test_llm.py::test_llm
```

查询当前服务提供的模型列表：

```bash
uv run pytest -s test/test_llm.py::test_llm_model_list
```

观察 App 初始化、Agent、模型和工具中间件的执行顺序：

```bash
uv run pytest -s test/test_app.py::test_app_with_middleware
```

`test_llm.py`、`test_agent.py` 和 `test_app.py` 中的用例会向配置的模型服务发送真实请求，部分用例还会等待终端输入。当前测试目录以手动运行和输出观察为主，尚未形成完整的自动化回归测试；不指定用例运行整个测试目录时，也会包含这些模型调用和交互流程。日志示例会按配置写入日志文件。

## 目录结构

```text
src/tabagent/
├── core/
│   ├── app.py             # 统一入口与客户端资源管理
│   ├── agent.py           # Agent 执行循环
│   ├── llm.py             # 统一 LLM 入口
│   ├── middleware.py      # 中间件调用链组装
│   ├── message.py         # 消息结构
│   ├── function.py        # 函数工具定义
│   ├── response.py        # 流式事件类型常量
│   ├── exceptions.py      # 自定义异常
│   ├── lifecycle.py       # 生命周期钩子定义，尚未接入
│   ├── config.py          # 日志配置
│   └── logger.py          # 日志初始化
├── llm/
│   ├── base_llm.py        # 底层 LLM 接口
│   ├── llm_adapter.py     # 按 provider 创建具体实现
│   └── openai_llm.py      # OpenAI Responses 实现
├── middleware/
│   ├── base_middleware.py # 请求类型与中间件基类
│   ├── logging_middleware.py # 日志中间件
│   └── ...               # 上下文、记忆、模型、工具、MCP、技能中间件待实现
├── tool/
│   ├── registry.py        # 工具注册表
│   └── tools/
│       ├── calculate_tool.py # 数学计算工具
│       └── web_search_tool.py # 网页搜索工具占位文件
├── mcp/                  # MCP 扩展占位目录
└── skill/                # 技能扩展占位目录
test/                      # 本地检查和交互示例
```

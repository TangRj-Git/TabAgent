# TabAgent

TabAgent 是一个逐步构建中的 Python Agent harness，通过异步流式模型调用、函数工具和对话历史管理，完成多轮任务执行。后续将通过中间件扩展模型和工具调用前后的处理。

## 当前功能

| 模块 | 已有能力 |
| --- | --- |
| `TabAgentLLM` | 封装 `AsyncOpenAI` 的 Responses API，逐个返回流式事件 |
| `TabAgent` | 输出文本增量，执行模型请求的函数工具，并继续请求模型直到得到最终回答 |
| `Message` | 组织用户消息、系统消息、模型输出项和工具执行结果 |
| `ToolRegistry` | 注册、查询、删除 Python 函数，生成提供给模型的函数定义 |
| 工具执行器 | 执行同步或异步工具，处理参数解析和结果序列化 |
| 自定义异常 | 区分配置、模型响应、调用次数上限和工具相关错误 |
| 日志 | 使用 Loguru，统一配置控制台和文件输出 |

`AgentLifecycle` 已定义 Agent、模型和工具执行前后的六个钩子，但当前尚未接入 `TabAgent`。`middleware/` 中的文件目前是占位文件。

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

服务需要支持 Responses API 的流式响应；使用工具时还需要支持 function calling。`TabAgentLLM` 通过构造参数接收连接配置，本身不会自动读取 `.env`。

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

下面的代码可以保存为项目根目录下的 Python 脚本，通过 `uv run python <脚本文件名>.py` 运行：

```python
import asyncio
import os

from dotenv import load_dotenv

from tabagent.core.agent import TabAgent
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message, UserMessage
from tabagent.tool.registry import ToolRegistry


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def main() -> None:
    load_dotenv()

    registry = ToolRegistry()
    registry.register_tool(multiply)
    messages: list[Message] = [UserMessage("请使用工具计算 12 乘 3。")]

    async with TabAgentLLM(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
    ) as llm:
        agent = TabAgent(
            llm=llm,
            model=os.environ["OPENAI_MODEL"],
            instructions="涉及算术时使用提供的工具，并用中文回答。",
            tool_registry=registry,
        )

        async for delta in agent.astream(messages=messages):
            print(delta, end="", flush=True)
        print()


if __name__ == "__main__":
    asyncio.run(main())
```

`TabAgent.astream()` 返回文本片段，并直接向传入的 `messages` 列表追加模型输出和工具结果。继续对话时，向同一个列表追加新的 `UserMessage`，再调用 `astream()` 即可，不需要重复保存模型输出。

一次 Agent 执行默认最多请求模型 10 次，可通过 `max_model_calls` 调整。LLM 客户端由调用方通过 `async with` 管理和关闭。

工具注册方法是同步方法，注册异步函数时也不需要 `await`。自动生成参数 Schema 目前采用简单类型映射；对于 `list[int]`、联合类型或复杂嵌套结构，需要通过 `register_tool(parameters=...)` 显式提供 Schema。默认 `strict=True` 时，自动生成的 Schema 会将全部参数列入 `required`。

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

`test_llm.py` 和 `test_agent.py` 中的用例会向配置的模型服务发送真实请求，部分用例还会等待终端输入。当前测试目录同时包含本地检查和手动运行示例；不指定用例运行整个测试目录时，也会包含这些模型调用和交互流程。

## 目录结构

```text
src/tabagent/
├── core/
│   ├── agent.py           # Agent 执行循环
│   ├── llm.py             # 异步模型客户端
│   ├── message.py         # 消息结构
│   ├── function.py        # 函数工具定义
│   ├── response.py        # 流式事件类型常量
│   ├── exceptions.py      # 自定义异常
│   ├── lifecycle.py       # 生命周期钩子定义
│   ├── config.py          # 日志配置
│   └── logger.py          # 日志初始化
├── tool/
│   └── registry.py        # 工具注册表
└── middleware/            # 中间件占位文件
test/                      # 本地检查和交互示例
```

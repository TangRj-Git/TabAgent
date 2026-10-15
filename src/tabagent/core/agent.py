from copy import deepcopy
from typing import Optional, List

from openai.types.responses import Response

from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message
from tabagent.tool.registry import ToolRegistry


class TabAgent:
    def __init__(
            self,
            *,
            llm: TabAgentLLM,
            model: Optional[str] = None,
            instructions: Optional[str] = None,
            tool_registry: Optional[ToolRegistry] = None,
            max_model_calls: Optional[int] = 10,
    ):
        self._llm = llm
        self._model = model
        self._instructions = instructions
        self._tool_registry = tool_registry
        self._max_model_calls = max_model_calls

    async def astream(
            self,
            messages: List[Message],
    ):
        functions = deepcopy(self._tool_registry.get_functions())
        tools = {
            function["name"]: self._tool_registry.get_tool(function["name"])
            for function in functions
        }

        for round_number in range(1, self._max_model_calls + 1):
            response: Optional[Response] = None

            stream = self._llm.astream(
                model=self._model,
                instructions=self._instructions,
                messages=messages,
                functions=functions
            )

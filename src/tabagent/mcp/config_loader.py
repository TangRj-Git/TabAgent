import asyncio
import json
from pathlib import Path

from tabagent.mcp.transport import MCPClientConfig


class MCPConfigLoader:
    """读取 JSON 文件，并转换成经过校验的 MCP 配置对象。"""

    def __init__(
            self,
            config_path: str | Path
    ) -> None:
        self.config_path = Path(config_path)

    async def load(self) -> MCPClientConfig:
        content = await asyncio.to_thread(
            self.config_path.read_text,
            encoding="utf-8-sig",
            errors=None,
        )

        raw = json.loads(content)

        return MCPClientConfig.model_validate(raw)

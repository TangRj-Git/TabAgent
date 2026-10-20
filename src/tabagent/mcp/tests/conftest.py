"""测试生成的配置文件只放在 MCP 目录内，不使用项目日志或外部服务。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_path():
    with TemporaryDirectory(prefix=".tmp-", dir=Path(__file__).parent) as directory:
        yield Path(directory)

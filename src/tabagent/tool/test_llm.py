import asyncio
import os

from dotenv import load_dotenv

from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import UserMessage


def test_llm() -> None:
    load_dotenv()

    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    async def run_astream() -> None:
        async with TabAgentLLM(
            base_url=base_url,
            api_key=api_key,
        ) as llm:
            async for event in llm.astream(
                model=model,
                instructions="请用中文简短回答。",
                messages=[UserMessage("用一句话介绍 Python。")],
                tools=[],
            ):
                print(event)

    asyncio.run(run_astream())

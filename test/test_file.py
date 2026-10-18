import json

from tabagent.tool.tools.file import create_file_tools

base_file = "D:\实验室Logo设计"


def test_file() -> None:
    file_tools = create_file_tools(base_file)
    list_directory = file_tools["list_directory"]
    # 工具返回的 JSON 字符串，可以直接作为工具执行结果交给 AI。
    result_json = list_directory(
        limit=10,
        cursor="10"
    )

    # 测试时解析成字典，再以缩进格式展示。
    result_data = json.loads(result_json)

    print(json.dumps(
        result_data,
        ensure_ascii=False,
        indent=2,
    ))

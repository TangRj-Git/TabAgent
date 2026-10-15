"""
OpenAI Responses API 流式事件类型常量。

对应 ResponseStreamEvent，用于判断 event.type。
"""

from typing import Final

# ==================== 响应生命周期 ====================

# 响应已创建。
RESPONSE_CREATED: Final = "response.created"

# 响应正在排队等待处理。
RESPONSE_QUEUED: Final = "response.queued"

# 响应正在处理或生成。
RESPONSE_IN_PROGRESS: Final = "response.in_progress"

# 本轮响应成功完成，可从 event.response.output 获取完整输出。
RESPONSE_COMPLETED: Final = "response.completed"

# 本轮响应失败，可检查 event.response.error。
RESPONSE_FAILED: Final = "response.failed"

# 本轮响应结束，但未完整生成，可检查 event.response.incomplete_details。
RESPONSE_INCOMPLETE: Final = "response.incomplete"

# 流中报告错误。注意：实际类型是 error，不是 response.error。
ERROR: Final = "error"

# ==================== 输出项与内容块 ====================

# 新增一个输出项，例如文本消息、推理项、函数调用。
RESPONSE_OUTPUT_ITEM_ADDED: Final = "response.output_item.added"

# 一个输出项生成结束，不代表整轮响应完成。
RESPONSE_OUTPUT_ITEM_DONE: Final = "response.output_item.done"

# 在消息输出项中新增一个内容块。
RESPONSE_CONTENT_PART_ADDED: Final = "response.content_part.added"

# 一个内容块生成结束。
RESPONSE_CONTENT_PART_DONE: Final = "response.content_part.done"

# ==================== 文本输出 ====================

# 新增一段回答文本，增量文本在 event.delta 中。
RESPONSE_OUTPUT_TEXT_DELTA: Final = "response.output_text.delta"

# 一个文本内容块生成结束，完整文本在 event.text 中。
RESPONSE_OUTPUT_TEXT_DONE: Final = "response.output_text.done"

# 文本新增一条注释信息，例如引用来源。
RESPONSE_OUTPUT_TEXT_ANNOTATION_ADDED: Final = "response.output_text.annotation.added"

# ==================== 拒绝回答 ====================

# 新增一段拒绝回答的文本。
RESPONSE_REFUSAL_DELTA: Final = "response.refusal.delta"

# 拒绝回答的文本生成结束。
RESPONSE_REFUSAL_DONE: Final = "response.refusal.done"

# ==================== 推理与推理摘要 ====================

# 新增一段推理文本；是否提供取决于模型和服务端支持。
RESPONSE_REASONING_TEXT_DELTA: Final = "response.reasoning_text.delta"

# 一个推理文本内容块生成结束。
RESPONSE_REASONING_TEXT_DONE: Final = "response.reasoning_text.done"

# 新增一个推理摘要内容块。
RESPONSE_REASONING_SUMMARY_PART_ADDED: Final = "response.reasoning_summary_part.added"

# 一个推理摘要内容块生成结束。
RESPONSE_REASONING_SUMMARY_PART_DONE: Final = "response.reasoning_summary_part.done"

# 新增一段推理摘要文本。
RESPONSE_REASONING_SUMMARY_TEXT_DELTA: Final = "response.reasoning_summary_text.delta"

# 一个推理摘要文本内容块生成结束。
RESPONSE_REASONING_SUMMARY_TEXT_DONE: Final = "response.reasoning_summary_text.done"

# ==================== Function 函数调用 ====================

# 新增一段函数调用参数字符串；此时通常还不是完整 JSON。
RESPONSE_FUNCTION_CALL_ARGUMENTS_DELTA: Final = "response.function_call_arguments.delta"

# 函数调用参数生成结束；不表示本地 Python 函数已经执行。
RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE: Final = "response.function_call_arguments.done"

# ==================== Custom 自定义工具 ====================
# 对应 API 的 custom 工具类型，与你当前的 function 工具类型不同。

# 新增一段自定义工具输入。
RESPONSE_CUSTOM_TOOL_CALL_INPUT_DELTA: Final = "response.custom_tool_call_input.delta"

# 自定义工具输入生成结束。
RESPONSE_CUSTOM_TOOL_CALL_INPUT_DONE: Final = "response.custom_tool_call_input.done"

# ==================== 音频与转写 ====================

# 新增一段音频数据。
RESPONSE_AUDIO_DELTA: Final = "response.audio.delta"

# 音频生成结束。
RESPONSE_AUDIO_DONE: Final = "response.audio.done"

# 新增一段音频转写文本。
RESPONSE_AUDIO_TRANSCRIPT_DELTA: Final = "response.audio.transcript.delta"

# 音频转写文本生成结束。
RESPONSE_AUDIO_TRANSCRIPT_DONE: Final = "response.audio.transcript.done"

# ==================== 文件搜索 ====================

# 文件搜索调用正在处理。
RESPONSE_FILE_SEARCH_CALL_IN_PROGRESS: Final = "response.file_search_call.in_progress"

# 正在搜索文件。
RESPONSE_FILE_SEARCH_CALL_SEARCHING: Final = "response.file_search_call.searching"

# 文件搜索调用完成。
RESPONSE_FILE_SEARCH_CALL_COMPLETED: Final = "response.file_search_call.completed"

# ==================== 网页搜索 ====================

# 网页搜索调用正在处理。
RESPONSE_WEB_SEARCH_CALL_IN_PROGRESS: Final = "response.web_search_call.in_progress"

# 正在搜索网页。
RESPONSE_WEB_SEARCH_CALL_SEARCHING: Final = "response.web_search_call.searching"

# 网页搜索调用完成。
RESPONSE_WEB_SEARCH_CALL_COMPLETED: Final = "response.web_search_call.completed"

# ==================== 代码解释器 ====================

# 代码解释器调用正在处理。
RESPONSE_CODE_INTERPRETER_CALL_IN_PROGRESS: Final = "response.code_interpreter_call.in_progress"

# 代码解释器正在执行代码。
RESPONSE_CODE_INTERPRETER_CALL_INTERPRETING: Final = "response.code_interpreter_call.interpreting"

# 代码解释器调用完成。
RESPONSE_CODE_INTERPRETER_CALL_COMPLETED: Final = "response.code_interpreter_call.completed"

# 新增一段待执行的代码文本。
RESPONSE_CODE_INTERPRETER_CALL_CODE_DELTA: Final = "response.code_interpreter_call_code.delta"

# 待执行的代码文本生成结束。
RESPONSE_CODE_INTERPRETER_CALL_CODE_DONE: Final = "response.code_interpreter_call_code.done"

# ==================== 图片生成 ====================

# 图片生成调用正在处理。
RESPONSE_IMAGE_GENERATION_CALL_IN_PROGRESS: Final = "response.image_generation_call.in_progress"

# 正在生成图片。
RESPONSE_IMAGE_GENERATION_CALL_GENERATING: Final = "response.image_generation_call.generating"

# 返回生成过程中的部分图片。
RESPONSE_IMAGE_GENERATION_CALL_PARTIAL_IMAGE: Final = "response.image_generation_call.partial_image"

# 图片生成调用完成。
RESPONSE_IMAGE_GENERATION_CALL_COMPLETED: Final = "response.image_generation_call.completed"

# ==================== MCP 工具 ====================

# 正在获取 MCP 工具列表。
RESPONSE_MCP_LIST_TOOLS_IN_PROGRESS: Final = "response.mcp_list_tools.in_progress"

# 获取 MCP 工具列表完成。
RESPONSE_MCP_LIST_TOOLS_COMPLETED: Final = "response.mcp_list_tools.completed"

# 获取 MCP 工具列表失败。
RESPONSE_MCP_LIST_TOOLS_FAILED: Final = "response.mcp_list_tools.failed"

# MCP 工具调用正在处理。
RESPONSE_MCP_CALL_IN_PROGRESS: Final = "response.mcp_call.in_progress"

# 新增一段 MCP 工具调用参数。
RESPONSE_MCP_CALL_ARGUMENTS_DELTA: Final = "response.mcp_call_arguments.delta"

# MCP 工具调用参数生成结束。
RESPONSE_MCP_CALL_ARGUMENTS_DONE: Final = "response.mcp_call_arguments.done"

# MCP 工具调用完成。
RESPONSE_MCP_CALL_COMPLETED: Final = "response.mcp_call.completed"

# MCP 工具调用失败。
RESPONSE_MCP_CALL_FAILED: Final = "response.mcp_call.failed"

# ==================== Shell 工具 ====================

# Shell 调用中新增一条命令。
RESPONSE_SHELL_CALL_COMMAND_ADDED: Final = "response.shell_call_command.added"

# 新增一段 Shell 命令文本。
RESPONSE_SHELL_CALL_COMMAND_DELTA: Final = "response.shell_call_command.delta"

# 一条 Shell 命令文本生成结束，不代表命令执行完成。
RESPONSE_SHELL_CALL_COMMAND_DONE: Final = "response.shell_call_command.done"

# 新增一段 Shell 调用输出内容。
RESPONSE_SHELL_CALL_OUTPUT_CONTENT_DELTA: Final = "response.shell_call_output_content.delta"

# 一个 Shell 调用输出内容块结束。
RESPONSE_SHELL_CALL_OUTPUT_CONTENT_DONE: Final = "response.shell_call_output_content.done"

# ==================== 上下文压缩 ====================

# 正在进行上下文压缩。
RESPONSE_COMPACTION_COMPACTING: Final = "response.compaction.compacting"

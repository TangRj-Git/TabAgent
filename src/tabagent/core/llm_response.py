from typing import TypeAlias, Union

from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseQueuedEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)

LLMStreamEvent: TypeAlias = Union[
    # 响应生命周期和错误。
    ResponseCreatedEvent,
    ResponseQueuedEvent,
    ResponseInProgressEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseErrorEvent,
    # 输出项和内容块。
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    # 正文和拒绝说明。
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    # 推理文本、推理摘要：是否返回取决于模型、接口和请求配置。
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    # function call 参数生成。
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    # 按需关注：正文中的引用或其他注释。
    ResponseOutputTextAnnotationAddedEvent,
]


# 键是实际的 event.type；每项注释标明对应 SDK 类和主要可读字段。
STREAM_EVENT_DESCRIPTIONS: dict[str, str] = {
    # 响应生命周期和错误。
    # ResponseCreatedEvent -> event.response
    "response.created": "响应已创建；可以读取 response.id，此时结果尚未完整生成。",
    # ResponseQueuedEvent -> event.response
    "response.queued": "响应正在排队等待处理；按需关注，常见于后台响应。",
    # ResponseInProgressEvent -> event.response
    "response.in_progress": "模型正在生成响应；此时 response.output 可能仍为空或不完整。",
    # ResponseCompletedEvent -> event.response.output / event.response.usage
    "response.completed": "本轮模型请求成功完成；读取完整 output、usage，并保存历史。",
    # ResponseFailedEvent -> event.response.error
    "response.failed": "本轮响应失败；从 response.error 查看错误详情。",
    # ResponseIncompleteEvent -> event.response.incomplete_details
    "response.incomplete": "本轮响应未完整生成即结束；从 incomplete_details 查看原因。",
    # ResponseErrorEvent -> event.message / event.code / event.param
    "error": "收到错误通知；检查 message、code、param，不能视为成功响应。",

    # 输出项和内容块：这里的 done 都是局部结束。
    # ResponseOutputItemAddedEvent -> event.item / event.output_index
    "response.output_item.added": (
        "新增输出项；通过 item.type 区分 message、reasoning 或 function_call。"
        "此时字段可能尚未完整，不能直接作为最终历史。"
    ),
    # ResponseOutputItemDoneEvent -> event.item / event.output_index
    "response.output_item.done": (
        "单个输出项结束，可读取该项结果；整轮是否成功仍看响应终态。"
        "本项目统一在 response.completed 保存历史，避免重复追加。"
    ),
    # ResponseContentPartAddedEvent -> event.part / event.content_index
    "response.content_part.added": "消息内新增内容块，例如正文或拒绝说明；通过 part.type 区分。",
    # ResponseContentPartDoneEvent -> event.part / event.content_index
    "response.content_part.done": "消息内的一个内容块结束；其他内容块或输出项仍可能继续生成。",

    # 正文：delta 是新增片段，done 携带的是完整文本，不要把两者重复拼接。
    # ResponseTextDeltaEvent -> event.delta
    "response.output_text.delta": "新增正文片段；读取 delta，用于流式显示或按内容块拼接。",
    # ResponseTextDoneEvent -> event.text
    "response.output_text.done": "当前正文块结束；text 是该块完整文本，尚不代表整轮完成。",

    # 拒绝说明仍是模型输出内容，整轮响应可能正常进入 response.completed。
    # ResponseRefusalDeltaEvent -> event.delta
    "response.refusal.delta": "新增拒绝说明片段；读取 delta，不应漏掉这类纯文本输出。",
    # ResponseRefusalDoneEvent -> event.refusal
    "response.refusal.done": "当前拒绝说明结束；完整内容在 refusal 字段，不是 text 字段。",

    # 推理文本：有些模型或兼容服务会返回，不代表所有模型都会暴露推理文本。
    # ResponseReasoningTextDeltaEvent -> event.delta
    "response.reasoning_text.delta": "新增推理相关文本片段；读取 delta，与正式正文分开处理。",
    # ResponseReasoningTextDoneEvent -> event.text
    "response.reasoning_text.done": "当前推理文本块结束；读取 text，正式回答可能尚未开始。",

    # 推理摘要：是否发送这些事件取决于模型和推理摘要配置。
    # ResponseReasoningSummaryPartAddedEvent -> event.part / event.summary_index
    "response.reasoning_summary_part.added": "新增推理摘要块；part 保存摘要块，summary_index 标明位置。",
    # ResponseReasoningSummaryPartDoneEvent -> event.part / event.status
    "response.reasoning_summary_part.done": (
        "当前推理摘要块结束；part 保存结果。"
        "若 status 为 incomplete，表示该块生成被中断，不能仅凭 done 判断完整。"
    ),
    # ResponseReasoningSummaryTextDeltaEvent -> event.delta / event.summary_index
    "response.reasoning_summary_text.delta": "新增推理摘要文字；读取 delta，并按 summary_index 归属。",
    # ResponseReasoningSummaryTextDoneEvent -> event.text / event.summary_index
    "response.reasoning_summary_text.done": "当前推理摘要文本结束；完整摘要文本在 text 字段。",

    # 函数参数：只描述模型生成调用参数的过程，不表示 Python 函数已执行。
    # ResponseFunctionCallArgumentsDeltaEvent -> event.delta / event.item_id
    "response.function_call_arguments.delta": (
        "新增函数参数字符串片段；按 item_id 归属。"
        "片段通常不是完整 JSON，不要逐片段 json.loads 或立即执行函数。"
    ),
    # ResponseFunctionCallArgumentsDoneEvent -> event.arguments / event.item_id
    "response.function_call_arguments.done": (
        "当前函数参数生成结束；arguments 是参数字符串，解析与校验后才能使用。"
        "函数 name、call_id 从对应的 function_call 输出项读取；此事件不代表函数执行成功。"
    ),

    # 按需关注：纯文本也能携带引用；当前未使用搜索等工具，通常无需处理。
    # ResponseOutputTextAnnotationAddedEvent -> event.annotation / event.annotation_index
    "response.output_text.annotation.added": "正文新增引用或其他注释；读取 annotation，它不是正文增量。",
}


# 本轮响应的三个终态；终态表示本轮结束，只有 completed 表示成功完成。
# 不把 error 放进来，因为它是错误通知，不是携带 Response 的响应终态事件。
TERMINAL_RESPONSE_EVENT_TYPES: frozenset[str] = frozenset({
    "response.completed",
    "response.failed",
    "response.incomplete",
})

# 错误事件入口；incomplete 需要单独处理，不能因为不在此集合就判断为成功。
# 实际调用仍需要处理 SDK 抛出的异常，以及连接中断但未收到终态的情况。
ERROR_EVENT_TYPES: frozenset[str] = frozenset({
    "response.failed",
    "error",
})

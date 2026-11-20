"""NL2SQL 引擎：自然语言 → 结构化 Intent（经 LLM function calling）。"""
import json
import logging

from ..llm.adapter import LLMError, get_llm
from ..llm.sanitizer import replace_pii

logger = logging.getLogger(__name__)


INTENT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "build_intent",
        "description": "将用户的数据查询需求转换为结构化意图查询",
        "parameters": {
            "type": "object",
            "properties": {
                "models": {"type": "array", "items": {"type": "string"}, "description": "涉及的语义模型名"},
                "measures": {"type": "array", "items": {"type": "string"}, "description": "度量（指标）业务名"},
                "dimensions": {"type": "array", "items": {"type": "string"}, "description": "维度业务名"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "op": {"type": "string", "enum": ["=", "!=", ">", "<", ">=", "<=", "in", "like", "is_null", "is_not_null"]},
                            "value": {"type": "string"},
                        },
                        "required": ["field", "op", "value"],
                    },
                    "description": "过滤条件；为空/非空用 op=is_null/is_not_null",
                },
                "time_range": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "type": {"type": "string", "enum": ["last_month", "last_week", "this_year", "between"]},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
                "time_group": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "时间字段业务名"},
                        "granularity": {"type": "string", "enum": ["hour", "day", "week", "month", "quarter", "year"], "description": "时间分组粒度"},
                    },
                    "required": ["field", "granularity"],
                    "description": "按时间粒度分组统计（按天/按月/按小时等）",
                },
                "derived_measures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "派生度量业务名"},
                            "kind": {"type": "string", "enum": ["ratio", "yoy", "mom", "duration", "scale"], "description": "比值/同比/环比/时长/单位换算"},
                            "numerator": {"type": "object", "description": "比值分子：{measure, filter?}"},
                            "denominator": {"type": "object", "description": "比值分母：{measure, filter?}"},
                            "measure": {"type": "string", "description": "同比环比/单位换算的基础度量名"},
                            "time_field": {"type": "string", "description": "同比/环比的时间字段"},
                            "granularity": {"type": "string", "enum": ["month", "quarter", "year"], "description": "同比/环比周期粒度"},
                            "start_field": {"type": "string", "description": "时长计算起始时间字段"},
                            "end_field": {"type": "string", "description": "时长计算结束时间字段"},
                            "unit": {"type": "string", "enum": ["second", "minute", "hour"], "description": "时长单位"},
                            "factor": {"type": "number", "description": "单位换算系数（如万元=0.0001）"},
                        },
                        "required": ["name", "kind"],
                    },
                    "description": "派生度量（比值/占比、同比、环比、时长、单位换算）",
                },
                "order_by": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "description": "排序字段（度量名或维度名）"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                        "required": ["field"],
                    },
                    "description": "排序（如“最高的/前几名”）",
                },
                "limit": {"type": "integer", "description": "返回行数上限"},
                "temporary_measures": {"type": "array", "items": {"type": "object"}},
                "missing_slots": {"type": "array", "items": {"type": "string"}, "description": "缺失的关键槽位（时间/过滤等）"},
            },
            "required": ["measures"],
        },
    },
}


def _build_system_prompt(context: str) -> str:
    return (
        "你是数据分析助手，把用户的中文自然语言问题转换为结构化意图查询。\n"
        "只使用下方语义模型中定义的度量、维度、字段；未定义的不要编造。\n"
        "缺少关键信息（如时间范围、过滤条件）时，在 missing_slots 中列出。\n"
        "排序/前几名需求用 order_by 和 limit 表达；比值/占比用 derived_measures(kind=ratio)；"
        "同比/环比用 derived_measures(kind=yoy/mom)。\n"
        "时间分组（按天/按月/按小时统计）用 time_group 表达。\n"
        "字段值为空/非空用 filters 的 op=is_null/is_not_null。\n"
        "两个时间字段的差值（如行程时长）用 derived_measures(kind=duration, start_field, end_field, unit)。\n"
        "单位换算（如万元/亿元）用 derived_measures(kind=scale, measure, factor)。\n"
        "过滤时尽量用语义模型里枚举定义中的业务词作为 value。\n"
        "同一度量在多个模型中定义时，必须在 models 里明确列出用哪个模型；"
        "若问题涉及多个事实表的合并（如黄色+绿色出租车），优先使用合并模型（如 trips）。\n\n"
        f"语义模型定义：\n{context}"
    )


def generate_intent(question: str, context: str) -> dict:
    """生成 Intent。context 为语义模型摘要（业务名/描述）。"""
    llm = get_llm()
    messages = [
        {"role": "system", "content": _build_system_prompt(context)},
        # 用户输入先做 PII 替换再出域
        {"role": "user", "content": replace_pii(question)},
    ]
    message = llm.chat_with_tools(messages, tools=[INTENT_TOOL_SCHEMA])

    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        raise LLMError("LLM 未返回结构化意图（无 tool_calls）")

    args_str = tool_calls[0]["function"].get("arguments", "{}")
    try:
        intent = json.loads(args_str)
    except json.JSONDecodeError as e:
        raise LLMError(f"意图 JSON 解析失败: {args_str[:300]}") from e

    return intent

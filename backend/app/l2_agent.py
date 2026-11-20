"""L2 Agent：单轮取数内部 agent 化。

把确定性环节（编译/执行/只读校验）包成工具，交给 LLM 在循环里自选调用，
自主决定走编译还是降级、出错后重试还是追问。步数封顶，护栏焊死在工具内部。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .compiler.compiler import CompileError, compile_intent
from .executor.engine import ExecutionError, correct_and_execute, validate_readonly
from .llm.adapter import get_llm
from .models import Datasource, SemanticModel, User
from .semantic.model import parse_semantic_model

MAX_STEPS = 8

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": "获取当前数据源的语义模型摘要（可用的度量/维度/字段）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_intent",
            "description": "用语义模型确定性编译并执行结构化意图查询（优先用它）",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "object",
                        "description": "结构化意图：models/measures/dimensions/filters/time_range/time_group/order_by/limit/derived_measures",
                    }
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "直接执行 SQL（降级路径，仅做只读校验，不保证语义正确）",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户追问澄清信息",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "任务完成，返回最终结论",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "你是取数 agent。用给定工具完成用户的数据查询任务。\n"
    "规则：\n"
    "1. 先调 get_schema 了解语义模型（度量/维度）和物理表列类型。\n"
    "2. 优先用 run_intent（走语义模型确定性编译，结果可信）。"
    "intent 支持：measures/dimensions/filters/time_range/time_group/order_by/limit/derived_measures；"
    "过滤为空/非空用 op=is_null/is_not_null；按天/按月分组用 time_group。\n"
    "3. 编译失败或字段超出覆盖时才用 run_sql 降级；写 SQL 时务必对照物理表列类型，"
    "不要对数值列用字符串函数（如 trim）、不要对字符串列用数值比较。\n"
    "4. 执行报错时，尝试修正后重试；信息确实不足时用 ask_user 追问。\n"
    "5. run_intent/run_sql 返回 ok=True 即表示查询已成功执行，"
    "系统会自动把真实数据返回给用户；你只需基于返回的行数/列名概括即可，"
    "不要再反复调工具尝试获取具体数值。\n"
    "6. 完成后用 finish 给出结论。\n"
    "7. 不要编造数据，结果以工具返回为准。"
)


class AgentContext:
    def __init__(self, db: Session, ds: Datasource) -> None:
        self.db = db
        self.ds = ds
        self.models = (
            db.query(SemanticModel)
            .filter(SemanticModel.datasource_id == ds.id, SemanticModel.status == "active")
            .all()
        )
        self.model_defs = []
        for m in self.models:
            try:
                self.model_defs.append(parse_semantic_model(m.yaml_content))
            except Exception:  # noqa: BLE001
                continue
        self.model_context = "\n\n".join(_build_model_context(m) for m in self.models if _build_model_context(m))
        self.physical_schema = _build_physical_schema(db, ds.id)
        self.last_result = None  # 最后一次成功执行的完整结果（返回给用户）

    def schema(self) -> str:
        dialect_hint = {
            "mysql": "MySQL",
            "postgres": "PostgreSQL",
        }.get(self.ds.type, self.ds.type)
        lines = [
            f"数据库方言：{dialect_hint}",
            "",
            "语义模型（业务名 → 物理列）：",
            self.model_context,
            "",
            "物理表与列类型（降级写 SQL 时参考）：",
        ]
        for table, cols in self.physical_schema.items():
            col_str = ", ".join(f"{c['name']} {c['type']}" for c in cols)
            lines.append(f"  表 {table}: {col_str}")
        return "\n".join(lines)


def _build_physical_schema(db: Session, datasource_id: int) -> dict[str, list[dict]]:
    """物理 schema（表名 → 列清单，含类型），经敏感对象过滤。"""
    from .models import ColumnMeta, TableMeta

    schema: dict[str, list[dict]] = {}
    tables = db.query(TableMeta).filter(TableMeta.datasource_id == datasource_id).all()
    for t in tables:
        cols = (
            db.query(ColumnMeta)
            .filter(ColumnMeta.table_id == t.id, ColumnMeta.is_sensitive == False)  # noqa: E712
            .all()
        )
        schema[t.name] = [{"name": c.name, "type": c.type} for c in cols]
    return schema


def _build_model_context(sm: SemanticModel) -> str:
    try:
        m = parse_semantic_model(sm.yaml_content)
    except Exception:  # noqa: BLE001
        return ""
    lines = [f"模型 {m.name}（表 {m.table}）:"]
    for measure in m.measures:
        lines.append(f"  度量: {measure.business_name} = {measure.expression}")
    for dim in m.dimensions:
        lines.append(f"  维度: {dim.business_name} -> {dim.physical}")
    return "\n".join(lines)


def _load_columns(db: Session, datasource_id: int):
    from .models import ColumnMeta, TableMeta

    return (
        db.query(ColumnMeta)
        .join(TableMeta, ColumnMeta.table_id == TableMeta.id)
        .filter(TableMeta.datasource_id == datasource_id)
        .all()
    )


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _execute_tool(ctx: AgentContext, name: str, args: dict) -> dict:
    """执行一个工具，返回观察结果（形状摘要，不含绝对聚合数值给 LLM）。"""
    db, ds = ctx.db, ctx.ds
    if name == "get_schema":
        return {"ok": True, "schema": ctx.schema()}

    if name == "run_intent":
        intent = args.get("intent", {})
        if not isinstance(intent, dict) or not intent.get("measures"):
            return {"ok": False, "error": "intent 缺少 measures"}
        try:
            compiled = compile_intent(intent, ctx.model_defs, ds.type)
        except CompileError as e:
            return {"ok": False, "error": f"编译失败: {e}"}
        return _execute_sql(ctx, compiled.sql, source="compile")

    if name == "run_sql":
        sql = args.get("sql", "")
        if not sql:
            return {"ok": False, "error": "sql 为空"}
        try:
            validate_readonly(sql, ds.type)
        except ExecutionError as e:
            return {"ok": False, "error": f"只读校验失败: {e}"}
        return _execute_sql(ctx, sql, source="degrade")

    if name == "ask_user":
        return {"ok": True, "clarify": args.get("question", "")}

    if name == "finish":
        return {"ok": True, "answer": args.get("answer", "")}

    return {"ok": False, "error": f"未知工具 {name}"}


def _execute_sql(ctx: AgentContext, sql: str, source: str) -> dict:
    try:
        result = correct_and_execute(ctx.ds, sql, _load_columns(ctx.db, ctx.ds.id))
    except ExecutionError as e:
        return {"ok": False, "error": str(e)}
    # 优先保留 compile 结果（degrade 不覆盖 compile）
    if ctx.last_result is None or (ctx.last_result.get("source") != "compile"):
        ctx.last_result = {
            "sql": result["sql"],
            "source": source,
            "columns": result["columns"],
            "rows": [[_jsonable(c) for c in row] for row in result["rows"]],
            "row_count": result["row_count"],
        }
    # 观察只给形状（行数/列名），不给行数据，守住"绝对数值不出域"
    return {
        "ok": True,
        "source": source,
        "row_count": result["row_count"],
        "columns": result["columns"],
    }


def run_agent(db: Session, user: User, ds: Datasource, question: str) -> dict:
    """运行 L2 agent 完成一次取数任务，返回结果 + 轨迹。"""
    ctx = AgentContext(db, ds)
    llm = get_llm()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    trajectory = []
    answer = ""
    for step in range(MAX_STEPS):
        resp = llm.chat(messages, tools=TOOLS, temperature=0.0)
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # 无工具调用 → 视为直接给出结论
            answer = msg.get("content") or answer
            break
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            observation = _execute_tool(ctx, name, args)
            trajectory.append({"step": step + 1, "tool": name, "args": args, "observation": observation})
            messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(observation, ensure_ascii=False)}
            )
            if name == "finish":
                answer = observation.get("answer", "")
                break
        if name == "finish":
            break

    if not answer:
        # 没显式 finish，用最后一条 content 作为结论
        answer = "（agent 未显式结束）"

    return {
        "question": question,
        "answer": answer,
        "steps": len(trajectory),
        "trajectory": trajectory,
        "result": ctx.last_result,
    }

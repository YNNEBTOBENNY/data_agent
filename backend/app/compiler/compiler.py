"""意图编译器：Intent → 方言 SQL（确定性，纯代码，无 LLM）。

同一 Intent + 同一语义模型 = 永远相同的 SQL。
支持：度量聚合 + 维度分组 + 过滤 + 时间范围 + 排序/限量 + 比值占比 + 同比环比(窗口) +
多表 join + 会话级临时口径 override。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlglot
from sqlglot import exp

from ..semantic.model import Dimension, Measure, SemanticModelDef


class CompileError(Exception):
    pass


@dataclass
class CompiledResult:
    sql: str
    join_path: str
    caliber_source: str  # model | temporary | degrade


def _quote(ident: str, dialect: str) -> str:
    if dialect == "mysql":
        return "`" + ident.replace("`", "``") + "`"
    return '"' + ident.replace('"', '""') + '"'


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _qualified(alias: str, column: str, dialect: str) -> str:
    return f"{_quote(alias, dialect)}.{_quote(column, dialect)}"


def _qualify_expr(expression: str, alias: str, dialect: str) -> str:
    """把度量表达式里未限定的列名加上表别名前缀。"""
    tree = sqlglot.parse_one(expression, read=dialect)
    for col in tree.find_all(exp.Column):
        if not col.args.get("table"):
            col.set("table", sqlglot.to_identifier(alias))
    return tree.sql(dialect=dialect)


# ---------- 时间 ----------

def _resolve_time_range(time_range: dict | None, field: str) -> str | None:
    """把相对/绝对时间范围转成 WHERE 片段。相对时间按 Python 本地日期计算。"""
    if not time_range or not field:
        return None
    t = time_range.get("type")
    today = datetime.now().date()
    if t == "last_month":
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_first = today.replace(day=1)
        return f"{field} >= {_lit(str(first))} AND {field} < {_lit(str(next_first))}"
    if t == "last_week":
        monday = today - timedelta(days=today.weekday())
        prev_monday = monday - timedelta(days=7)
        return f"{field} >= {_lit(str(prev_monday))} AND {field} < {_lit(str(monday))}"
    if t == "this_year":
        return f"{field} >= {_lit(str(today.replace(month=1, day=1)))}"
    if t == "between":
        start = time_range.get("start")
        end = time_range.get("end")
        if start and end:
            # end 为纯日期时（如 2018-01-31）视为"该日全天"，补到 23:59:59，避免漏掉当天
            end = str(end).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", end):
                end = end + " 23:59:59"
            return f"{field} >= {_lit(str(start))} AND {field} <= {_lit(end)}"
    return None


def _period_expr(field_sql: str, granularity: str, dialect: str) -> str:
    """周期截断：把时间列截断到 小时/天/周/月/季/年。"""
    if dialect == "mysql":
        if granularity == "hour":
            return f"DATE_FORMAT({field_sql}, '%Y-%m-%d %H:00')"
        if granularity == "day":
            return f"DATE_FORMAT({field_sql}, '%Y-%m-%d')"
        if granularity == "week":
            return f"DATE_FORMAT({field_sql}, '%x-W%v')"
        if granularity == "month":
            return f"DATE_FORMAT({field_sql}, '%Y-%m')"
        if granularity == "quarter":
            return f"CONCAT(YEAR({field_sql}), '-Q', QUARTER({field_sql}))"
        return f"YEAR({field_sql})"
    # postgres
    if granularity == "hour":
        return f"to_char({field_sql}, 'YYYY-MM-DD HH24:00')"
    if granularity == "day":
        return f"to_char({field_sql}, 'YYYY-MM-DD')"
    if granularity == "week":
        return f"to_char({field_sql}, 'IYYY-IW')"
    if granularity == "month":
        return f"to_char({field_sql}, 'YYYY-MM')"
    if granularity == "quarter":
        return f"to_char({field_sql}, 'YYYY\"-Q\"Q')"
    return f"to_char({field_sql}, 'YYYY')"


def _duration_expr(start_sql: str, end_sql: str, unit: str, dialect: str) -> str:
    """时间差表达式（second/minute/hour）。"""
    if dialect == "mysql":
        sql_unit = {"second": "SECOND", "minute": "MINUTE", "hour": "HOUR"}.get(unit, "MINUTE")
        return f"TIMESTAMPDIFF({sql_unit}, {start_sql}, {end_sql})"
    factor = {"second": 1, "minute": 60, "hour": 3600}.get(unit, 60)
    return f"EXTRACT(EPOCH FROM ({end_sql} - {start_sql})) / {factor}"


# ---------- 模型/字段解析 ----------

def _find_measure(models: list[SemanticModelDef], name: str):
    for m in models:
        for measure in m.measures:
            if measure.business_name == name:
                return m, measure
    return None, None


def _find_measures(models: list[SemanticModelDef], name: str):
    return [(m, ms) for m in models for ms in m.measures if ms.business_name == name]


def _resolve_measure(intent: dict, models: list[SemanticModelDef], name: str):
    """解析度量：优先按 intent.models 消歧；歧义时抛错（走降级），绝不静默取第一个。"""
    matches = _find_measures(models, name)
    if not matches:
        return None, None
    if intent.get("models"):
        limited = [(m, ms) for m, ms in matches if m.name in intent["models"]]
        if limited:
            matches = limited
    if len(matches) > 1:
        names = [m.name for m, _ in matches]
        raise CompileError(f"度量「{name}」在多个语义模型中定义（{', '.join(names)}），语义歧义")
    return matches[0]


def _find_dimension(models: list[SemanticModelDef], name: str):
    for m in models:
        for d in m.dimensions:
            if d.business_name == name:
                return m, d.physical
    for m in models:
        for c in m.columns:
            if c.business_name == name:
                return m, c.physical
    return None, None


def _find_dimensions(models: list[SemanticModelDef], name: str):
    """收集所有匹配（维度 + 列），按 (模型名, 物理列) 去重。"""
    result: list = []
    seen: set = set()
    for m in models:
        for d in m.dimensions:
            if d.business_name == name and (m.name, d.physical) not in seen:
                seen.add((m.name, d.physical))
                result.append((m, d.physical))
    for m in models:
        for c in m.columns:
            if c.business_name == name and (m.name, c.physical) not in seen:
                seen.add((m.name, c.physical))
                result.append((m, c.physical))
    return result


def _resolve_dimension(intent: dict, models: list[SemanticModelDef], name: str):
    """解析维度/字段：优先按 intent.models 消歧；歧义时抛错（走降级）。"""
    matches = _find_dimensions(models, name)
    if not matches:
        return None, None
    if intent.get("models"):
        limited = [(m, p) for m, p in matches if m.name in intent["models"]]
        if limited:
            matches = limited
    if len(matches) > 1:
        names = [m.name for m, _ in matches]
        raise CompileError(f"维度「{name}」在多个语义模型中定义（{', '.join(names)}），语义歧义")
    return matches[0]


def _find_field_enum(models: list[SemanticModelDef], name: str) -> dict:
    """查找字段的枚举映射（业务词 → 物理值）。"""
    for m in models:
        for d in m.dimensions:
            if d.business_name == name and d.enum:
                return d.enum
    for m in models:
        for c in m.columns:
            if c.business_name == name and c.enum:
                return c.enum
    return {}


def _translate_enum_value(models: list[SemanticModelDef], field: str, value: str):
    """把业务词翻译成物理值（如 现金→2、是→Yes）。命中枚举则返回物理值，否则原样返回。"""
    enum = _find_field_enum(models, field)
    if enum and value in enum:
        return enum[value]
    return value


def _lit_value(v) -> str:
    """值转 SQL 字面量：数值不加引号，字符串加引号。"""
    if isinstance(v, (int, float)):
        return str(v)
    return _lit(str(v))


def _resolve_field_physical(model: SemanticModelDef, business_name: str) -> str | None:
    for d in model.dimensions:
        if d.business_name == business_name:
            return d.physical
    for c in model.columns:
        if c.business_name == business_name:
            return c.physical
    return None


def _base_model(intent: dict, models: list[SemanticModelDef], model_map: dict) -> SemanticModelDef:
    if intent.get("models"):
        m = model_map.get(intent["models"][0])
        if m:
            return m
    for name in intent.get("measures", []) or []:
        m, _ = _find_measure(models, name)
        if m:
            return m
    for name in intent.get("dimensions", []) or []:
        m, _ = _find_dimension(models, name)
        if m:
            return m
    return models[0]


def _build_join_graph(models: list[SemanticModelDef]) -> dict:
    """构建有向 join 邻接表：{模型名: [(目标模型名, key, foreign_key, direction), ...]}"""
    graph: dict = {}
    for m in models:
        edges = [(j.model, j.key, j.foreign_key or j.key, j.direction) for j in m.joins]
        graph[m.name] = edges
    return graph


def _find_join_path(graph: dict, base: str, target: str, max_hops: int = 3) -> list | None:
    """BFS 找 base 到 target 的最短路径，返回边列表 [(from, to, key, foreign_key, direction), ...]。
    超过 max_hops 或无路径返回 None。"""
    from collections import deque

    queue = deque([(base, [])])
    visited = {base}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        for edge in graph.get(node, []):
            to_name = edge[0]
            if to_name == target:
                return path + [(node, *edge)]
            if to_name not in visited:
                visited.add(to_name)
                queue.append((to_name, path + [(node, *edge)]))
    return None


def _build_from_and_joins(
    base: SemanticModelDef, model_map: dict, dialect: str, referenced: set[str] | None = None
) -> tuple[str, list[str], list[str]]:
    """返回 (from 子句, join 子句列表, 参与的表别名列表)。支持多跳 join（最短路径，≤3 跳）。"""
    from_clause = f"{_quote(base.table, dialect)} AS {_quote(base.name, dialect)}"
    joins: list[str] = []
    aliases = [base.name]

    if not referenced:
        return from_clause, joins, aliases

    graph = _build_join_graph(list(model_map.values()))

    for target_name in referenced:
        if target_name == base.name or target_name in aliases or target_name not in model_map:
            continue
        path = _find_join_path(graph, base.name, target_name, max_hops=3)
        if path is None:
            continue  # 无路径（>3 跳或无连接），让后续字段解析报错走降级
        for from_name, to_name, key, foreign_key, direction in path:
            if to_name in aliases:
                continue
            to_model = model_map[to_name]
            dir_sql = {"LEFT": "LEFT JOIN", "RIGHT": "RIGHT JOIN", "INNER": "INNER JOIN"}.get(
                direction.upper(), "LEFT JOIN"
            )
            joins.append(
                f"{dir_sql} {_quote(to_model.table, dialect)} AS {_quote(to_name, dialect)} "
                f"ON {_qualified(from_name, key, dialect)} = {_qualified(to_name, foreign_key, dialect)}"
            )
            aliases.append(to_name)

    # 引用了但 join 不到（>3 跳或无连接）的模型 → 报错走降级，而非生成残缺 SQL
    for name in referenced:
        if name != base.name and name in model_map and name not in aliases:
            raise CompileError(f"模型「{name}」无法从「{base.name}」在 3 跳内 join 到")

    return from_clause, joins, aliases


def _referenced_models(intent: dict, models: list[SemanticModelDef]) -> set[str]:
    """收集 Intent 里实际引用的模型名（与编译时的消歧逻辑一致，尊重 intent.models）。"""
    names: set[str] = set()

    def _add_measure(name):
        try:
            m, _ = _resolve_measure(intent, models, name)
        except CompileError:
            m, _ = _find_measure(models, name)
        if m:
            names.add(m.name)

    def _add_dimension(name):
        if not name:
            return
        try:
            m, _ = _resolve_dimension(intent, models, name)
        except CompileError:
            m, _ = _find_dimension(models, name)
        if m:
            names.add(m.name)

    for name in intent.get("measures", []) or []:
        _add_measure(name)
    for name in intent.get("dimensions", []) or []:
        _add_dimension(name)
    for f in intent.get("filters", []) or []:
        _add_dimension(f.get("field"))
    tr = intent.get("time_range")
    if tr and tr.get("field"):
        _add_dimension(tr["field"])
    tg = intent.get("time_group")
    if tg and tg.get("field"):
        _add_dimension(tg["field"])
    for d in intent.get("derived_measures", []) or []:
        for ref in (d.get("numerator"), d.get("denominator"), d):
            if isinstance(ref, dict) and ref.get("measure"):
                _add_measure(ref["measure"])
        if d.get("time_field"):
            _add_dimension(d["time_field"])
        if d.get("start_field"):
            _add_dimension(d["start_field"])
        if d.get("end_field"):
            _add_dimension(d["end_field"])
    return names


# ---------- 度量表达式 ----------

def _conditional_aggregate(
    expression: str, filter_dict: dict, model: SemanticModelDef,
    models: list[SemanticModelDef], dialect: str,
) -> str:
    """把聚合度量包进 CASE WHEN 实现条件聚合，如 SUM(order_amount) + region=华东 →
    SUM(CASE WHEN region='华东' THEN order_amount ELSE 0 END)。"""
    tree = sqlglot.parse_one(expression, read=dialect)
    agg = next(tree.find_all(exp.AggFunc), None)
    if agg is None:
        raise CompileError(f"度量表达式不是聚合函数: {expression}")
    func = agg.sql_name().upper()
    inner = agg.this

    field = filter_dict.get("field")
    op = filter_dict.get("op", "=")
    value = filter_dict.get("value", "")
    physical = _resolve_field_physical(model, field)
    if physical is None:
        raise CompileError(f"条件聚合字段「{field}」未在语义模型中定义")
    translated = _translate_enum_value(models, field, value)
    cond = f"{_qualified(model.name, physical, dialect)} {op} {_lit_value(translated)}"

    if isinstance(inner, exp.Star):
        return f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END)"

    inner_sql = _qualify_expr(inner.sql(dialect=dialect), model.name, dialect)
    neutral = "0" if func == "SUM" else "NULL"
    return f"{func}(CASE WHEN {cond} THEN {inner_sql} ELSE {neutral} END)"


def _measure_ref_expr(
    intent: dict, ref: dict, models: list[SemanticModelDef], dialect: str
) -> str:
    """度量引用 → SQL 表达式（含条件聚合）。ref = {measure, filter?}"""
    name = ref.get("measure")
    m, measure = _resolve_measure(intent, models, name)
    if measure is None:
        raise CompileError(f"度量「{name}」未在语义模型中定义")
    filter_dict = ref.get("filter")
    if filter_dict:
        return _conditional_aggregate(measure.expression, filter_dict, m, models, dialect)
    return _qualify_expr(measure.expression, m.name, dialect)


# ---------- 主编译 ----------

def compile_intent(
    intent: dict, models: list[SemanticModelDef], dialect: str = "mysql"
) -> CompiledResult:
    """将 Intent 编译为方言 SQL。"""
    if dialect not in ("mysql", "postgres"):
        raise CompileError(f"不支持的方言: {dialect}")
    if not models:
        raise CompileError("无语义模型")

    model_map = {m.name: m for m in models}
    derived = intent.get("derived_measures", []) or []
    window_derived = [d for d in derived if d.get("kind") in ("yoy", "mom")]
    if window_derived:
        return _compile_with_window(intent, models, model_map, dialect, window_derived)

    base = _base_model(intent, models, model_map)
    referenced = _referenced_models(intent, models)
    from_clause, joins, _aliases = _build_from_and_joins(base, model_map, dialect, referenced)

    # 临时口径 override
    temp_by_name = {
        m.get("name"): m.get("expression")
        for m in intent.get("temporary_measures", []) or []
    }

    select_parts: list[str] = []
    caliber_source = "model"
    measure_names = intent.get("measures", []) or []
    if not measure_names and not derived:
        raise CompileError("Intent 缺少度量")

    # 度量
    for name in measure_names:
        if name in temp_by_name:
            select_parts.append(
                f"{_qualify_expr(temp_by_name[name], base.name, dialect)} AS {_quote(name, dialect)}"
            )
            caliber_source = "temporary"
            continue
        m, measure = _resolve_measure(intent, models, name)
        if measure is None:
            raise CompileError(f"度量「{name}」未在语义模型中定义")
        select_parts.append(
            f"{_qualify_expr(measure.expression, m.name, dialect)} AS {_quote(name, dialect)}"
        )

    # 维度 + GROUP BY
    group_parts: list[str] = []
    dimension_names = intent.get("dimensions", []) or []
    for name in dimension_names:
        m, physical = _resolve_dimension(intent, models, name)
        if physical is None:
            raise CompileError(f"维度「{name}」未在语义模型中定义")
        qualified = _qualified(m.name, physical, dialect)
        select_parts.append(f"{qualified} AS {_quote(name, dialect)}")
        group_parts.append(qualified)

    # 时间粒度分组（按天/月/小时等）
    time_group = intent.get("time_group")
    if time_group and time_group.get("field"):
        tg_field = time_group.get("field")
        tg_gran = time_group.get("granularity", "day")
        m, physical = _resolve_dimension(intent, models, tg_field)
        if physical is None:
            raise CompileError(f"时间字段「{tg_field}」未在语义模型中定义")
        qualified = _qualified(m.name, physical, dialect)
        truncated = _period_expr(qualified, tg_gran, dialect)
        alias = f"{tg_field}(按{tg_gran})"
        select_parts.append(f"{truncated} AS {_quote(alias, dialect)}")
        group_parts.append(truncated)

    # 派生度量（非窗口）：比值/占比、时长、单位换算
    for d in derived:
        kind = d.get("kind")
        if kind == "ratio":
            num = _measure_ref_expr(intent, d.get("numerator", {}), models, dialect)
            den = _measure_ref_expr(intent, d.get("denominator", {}), models, dialect)
            select_parts.append(f"({num}) / ({den}) AS {_quote(d.get('name', ''), dialect)}")
        elif kind == "duration":
            start_m, start_p = _resolve_dimension(intent, models, d.get("start_field", ""))
            end_m, end_p = _resolve_dimension(intent, models, d.get("end_field", ""))
            if not start_p or not end_p:
                raise CompileError(f"时长派生度量缺少 start_field/end_field")
            start_q = _qualified(start_m.name, start_p, dialect)
            end_q = _qualified(end_m.name, end_p, dialect)
            dur = _duration_expr(start_q, end_q, d.get("unit", "minute"), dialect)
            select_parts.append(f"AVG({dur}) AS {_quote(d.get('name', ''), dialect)}")
        elif kind == "scale":
            m, measure = _resolve_measure(intent, models, d.get("measure", ""))
            if measure is None:
                raise CompileError(f"单位换算的基础度量「{d.get('measure')}」未定义")
            expr = _qualify_expr(measure.expression, m.name, dialect)
            factor = d.get("factor", 1)
            select_parts.append(f"({expr}) * {factor} AS {_quote(d.get('name', ''), dialect)}")

    # 过滤 + 时间范围
    where_parts: list[str] = []
    for f in intent.get("filters", []) or []:
        field = f.get("field")
        op = f.get("op", "=")
        value = f.get("value", "")
        m, physical = _resolve_dimension(intent, models, field)
        if physical is None:
            raise CompileError(f"过滤字段「{field}」未在语义模型中定义")
        qualified = _qualified(m.name, physical, dialect)
        if op == "is_null":
            where_parts.append(f"{qualified} IS NULL")
        elif op == "is_not_null":
            where_parts.append(f"{qualified} IS NOT NULL")
        elif op == "in":
            where_parts.append(f"{qualified} IN ({value})")
        elif op == "like":
            if any(w in value for w in ("%", "_")):
                where_parts.append(f"{qualified} LIKE {_lit(value)}")
            else:
                where_parts.append(f"{qualified} = {_lit(value)}")
        else:
            translated = _translate_enum_value(models, field, value)
            where_parts.append(f"{qualified} {op} {_lit_value(translated)}")

    time_range = intent.get("time_range")
    if time_range and time_range.get("field"):
        m, physical = _resolve_dimension(intent, models, time_range["field"])
        if physical:
            time_sql = _resolve_time_range(time_range, _qualified(m.name, physical, dialect))
            if time_sql:
                where_parts.append(time_sql)

    sql = "SELECT " + ", ".join(select_parts) + f" FROM {from_clause}"
    for j in joins:
        sql += " " + j
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)

    # 排序 + 限量
    sql += _build_order_limit(intent, models, dialect, select_parts, group_parts)

    join_path = " -> ".join([base.name] + _aliases[1:]) if len(_aliases) > 1 else base.name
    return CompiledResult(sql=sql, join_path=join_path, caliber_source=caliber_source)


def _build_order_limit(
    intent: dict, models: list[SemanticModelDef], dialect: str,
    select_parts: list[str], group_parts: list[str],
) -> str:
    order_by = intent.get("order_by", []) or []
    limit = intent.get("limit")
    parts = ""
    if order_by:
        orders = []
        for ob in order_by:
            field = ob.get("field")
            direction = "ASC" if ob.get("direction", "asc").lower() != "desc" else "DESC"
            # 优先按度量别名/派生别名排序（select 中已存在），否则按维度物理列
            m, physical = _find_dimension(models, field)
            m2, measure = _find_measure(models, field)
            if physical is None and measure is None:
                raise CompileError(f"排序字段「{field}」未定义")
            # 度量或维度都在 select 里有别名，直接按别名排
            orders.append(f"{_quote(field, dialect)} {direction}")
        parts += " ORDER BY " + ", ".join(orders)
    if limit is not None:
        parts += f" LIMIT {int(limit)}"
    return parts


def _compile_with_window(
    intent: dict, models: list[SemanticModelDef], model_map: dict,
    dialect: str, window_derived: list[dict],
) -> CompiledResult:
    """同比/环比：内层按周期聚合，外层用 LAG 窗口函数计算。"""
    base = _base_model(intent, models, model_map)
    referenced = _referenced_models(intent, models)
    from_clause, joins, _ = _build_from_and_joins(base, model_map, dialect, referenced)

    measure_names = intent.get("measures", []) or []
    if not measure_names:
        raise CompileError("窗口派生度量需要一个基础度量")
    m, measure = _resolve_measure(intent, models, measure_names[0])
    if measure is None:
        raise CompileError(f"度量「{measure_names[0]}」未在语义模型中定义")
    measure_expr = _qualify_expr(measure.expression, m.name, dialect)

    d = window_derived[0]
    time_field = d.get("time_field")
    granularity = d.get("granularity", "month")
    tm, time_physical = _find_dimension(models, time_field)
    if time_physical is None:
        raise CompileError(f"时间字段「{time_field}」未在语义模型中定义")
    time_qualified = _qualified(tm.name, time_physical, dialect)
    period = _period_expr(time_qualified, granularity, dialect)

    offset = {"yoy": {"month": 12, "quarter": 4, "year": 1}, "mom": {"month": 1, "quarter": 1, "year": 1}}[
        d.get("kind")
    ].get(granularity, 12)

    # 过滤（可选）
    where_parts = []
    for f in intent.get("filters", []) or []:
        field = f.get("field"); op = f.get("op", "="); value = f.get("value", "")
        fm, physical = _find_dimension(models, field)
        if physical:
            where_parts.append(f"{_qualified(fm.name, physical, dialect)} {op} {_lit(value)}")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    inner = (
        f"SELECT {period} AS {_quote('period', dialect)}, "
        f"{measure_expr} AS {_quote(measure.business_name, dialect)} "
        f"FROM {from_clause}"
    )
    for j in joins:
        inner += " " + j
    inner += where_sql + f" GROUP BY {period}"

    mn = measure.business_name
    qn = _quote(mn, dialect)
    lag = f"LAG({qn}, {offset}) OVER (ORDER BY {_quote('period', dialect)})"
    ratio = f"({qn} - {lag}) / NULLIF({lag}, 0)"

    outer = (
        f"SELECT {_quote('period', dialect)}, {qn}, {ratio} AS {_quote(d.get('name', ''), dialect)} "
        f"FROM ({inner}) AS t"
    )

    return CompiledResult(sql=outer, join_path=base.name, caliber_source="model")

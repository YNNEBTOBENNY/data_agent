"""SQL 执行引擎：只读校验（sqlglot）、执行、分层自动纠错。"""
from __future__ import annotations

import logging

import sqlglot
from sqlalchemy import create_engine, text

from ..metadata.collector import _build_datasource_url
from ..models import ColumnMeta, Datasource

logger = logging.getLogger(__name__)

MAX_CORRECTION_ATTEMPTS = 3


class ExecutionError(Exception):
    pass


def validate_readonly(sql: str, dialect: str) -> None:
    """基于 sqlglot 静态校验：仅 SELECT（含 UNION/子查询）、拦截写路径。"""
    try:
        parsed = sqlglot.parse(sql, read=dialect)
    except Exception as e:  # noqa: BLE001
        raise ExecutionError(f"SQL 解析失败: {e}") from e

    if not parsed:
        raise ExecutionError("空 SQL")

    for stmt in parsed:
        _check_readonly(stmt)


def _check_readonly(stmt) -> None:
    """递归校验：SELECT / UNION / INTERSECT / EXCEPT 均视为只读，其余拦截。"""
    if isinstance(stmt, sqlglot.exp.Select):
        if stmt.args.get("into") is not None:
            raise ExecutionError("禁止 SELECT INTO")
        return
    if isinstance(stmt, (sqlglot.exp.Union, sqlglot.exp.Intersect, sqlglot.exp.Except)):
        for side in (stmt.this, stmt.expression):
            if side is not None:
                _check_readonly(side)
        return
    raise ExecutionError(f"仅允许 SELECT 语句，检测到: {stmt.key}")


def execute(ds: Datasource, sql: str, max_rows: int = 100_000, timeout: int = 120) -> dict:
    """在只读数据源上执行 SQL，返回列名与前 N 行、行数、耗时。"""
    validate_readonly(sql, ds.type)

    engine = create_engine(_build_datasource_url(ds), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            if ds.type == "mysql":
                conn.execute(text(f"SET SESSION max_execution_time={timeout * 1000}"))
            elif ds.type == "postgres":
                conn.execute(text(f"SET statement_timeout={timeout * 1000}"))

            if max_rows:
                result = conn.execution_options(stream_results=False).execute(text(sql))
                rows = result.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
                columns = list(result.keys())
                row_count = len(rows)
            else:
                result = conn.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())
                row_count = len(rows)
                truncated = False

            return {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "row_count": row_count,
                "truncated": truncated,
            }
    except Exception as e:  # noqa: BLE001
        raise ExecutionError(str(e)) from e
    finally:
        engine.dispose()


def _fuzzy_fix(sql: str, error: str, columns: list[ColumnMeta]) -> str | None:
    """本地纠错：用元数据做列名模糊匹配（编辑距离/子串），命中则替换。"""
    import difflib

    known = {c.name for c in columns}
    fixed = sql

    # 从报错中提取疑似列名（简单启发式：反引号/引号内标识符）
    import re

    candidates = set(re.findall(r"['\"`]([A-Za-z_][A-Za-z0-9_]*)['\"`]", error))
    for cand in candidates:
        if cand in known:
            continue
        match = difflib.get_close_matches(cand, known, n=1, cutoff=0.8)
        if match:
            fixed = re.sub(rf"\b{re.escape(cand)}\b", match[0], fixed)
    return fixed if fixed != sql else None


def correct_and_execute(
    ds: Datasource,
    sql: str,
    columns: list[ColumnMeta],
    llm_fix_fn=None,
) -> dict:
    """执行并自动纠错（上限 3 次）。llm_fix_fn(sql, error) 由调用方注入（降级/LLM 纠错）。"""
    last_sql = sql
    for attempt in range(MAX_CORRECTION_ATTEMPTS):
        try:
            result = execute(ds, last_sql)
            result["sql"] = last_sql
            result["corrected"] = attempt > 0
            result["correction_count"] = attempt
            return result
        except ExecutionError as e:
            error = str(e)
            logger.warning("执行失败(第%d次): %s", attempt + 1, error)
            fixed = _fuzzy_fix(last_sql, error, columns)
            if fixed is None and llm_fix_fn is not None:
                try:
                    fixed = llm_fix_fn(last_sql, error)
                except Exception:  # noqa: BLE001
                    fixed = None
            if fixed is None or fixed == last_sql:
                raise ExecutionError(
                    f"执行失败，已尝试 {attempt + 1} 次: {error} | 最后 SQL: {last_sql}"
                ) from e
            last_sql = fixed
    raise ExecutionError(f"自动纠错已达上限 {MAX_CORRECTION_ATTEMPTS} 次")

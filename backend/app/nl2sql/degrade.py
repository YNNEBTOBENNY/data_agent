"""降级路径：Intent 超出语义模型覆盖时，由 LLM 直接生成 SQL。

生成 SQL 仅做 sqlglot 语法校验 + 字段存在性比对，不承诺语义正确。
结果需标注"未经语义模型校验"。
"""
from __future__ import annotations

import re

from ..llm.adapter import get_llm
from ..llm.sanitizer import replace_pii


def _build_schema_context(tables: dict[str, list[dict]]) -> str:
    """构建物理 schema 摘要（表名 + 列名 + 类型），供 LLM 写 SQL 参考。"""
    lines = []
    for table, columns in tables.items():
        cols = ", ".join(f"{c['name']} {c['type']}" for c in columns)
        lines.append(f"表 {table}({cols})")
    return "\n".join(lines)


def generate_sql(question: str, tables: dict[str, list[dict]], dialect: str) -> str:
    """LLM 直接生成 SQL。tables: {表名: [{name, type}]}（经敏感过滤后）。"""
    llm = get_llm()
    schema = _build_schema_context(tables)
    dialect_hint = {"mysql": "MySQL", "postgres": "PostgreSQL"}.get(dialect, dialect)
    prompt = (
        f"你是 SQL 专家。数据库方言：{dialect_hint}。\n"
        "根据下面的表结构，把用户问题写成一条只读 SELECT 查询。\n"
        "只输出 SQL 本身，不要解释，不要用代码块包裹。\n\n"
        f"表结构：\n{schema}\n\n"
        f"用户问题：{replace_pii(question)}"
    )
    sql = llm.chat_text(
        [{"role": "system", "content": "你只输出 SQL 语句，不做任何解释。"},
         {"role": "user", "content": prompt}],
        temperature=0.0,
    ).strip()
    sql = _extract_sql(sql)
    if not sql:
        raise ValueError("LLM 未生成 SQL")
    return sql


def _extract_sql(text: str) -> str:
    """从 LLM 输出中提取 SQL（去掉可能的代码块包裹）。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # 找到第一个 SELECT
    m = re.search(r"(?is)(select\b.*)", text)
    return m.group(1).strip() if m else text

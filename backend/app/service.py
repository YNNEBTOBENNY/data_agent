"""查询编排服务：自然语言 → Intent → 编译 → 执行 → 结果记录。

编译失败或超出语义模型覆盖时，走降级路径（LLM 直接生成 SQL，标注未校验）。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .compiler.compiler import CompileError, compile_intent
from .executor.engine import ExecutionError, correct_and_execute, validate_readonly
from .models import (
    CaliberDraft,
    ColumnMeta,
    Datasource,
    QueryRecord,
    SemanticModel,
    TableMeta,
    User,
)
from .nl2sql.degrade import generate_sql
from .nl2sql.engine import generate_intent
from .semantic.model import SemanticModelDef, SemanticModelError, parse_semantic_model


def _build_model_context(sm: SemanticModel) -> str:
    """构建语义模型摘要（业务名/描述）作为 LLM 注入上下文。"""
    try:
        m = parse_semantic_model(sm.yaml_content)
    except SemanticModelError:
        return ""
    lines = [f"模型 {m.name}（表 {m.table}）:"]
    for measure in m.measures:
        lines.append(f"  度量: {measure.business_name} = {measure.expression} ({measure.description})")
    for dim in m.dimensions:
        line = f"  维度: {dim.business_name} -> {dim.physical}"
        if dim.enum:
            enum_str = ", ".join(f"{k}={v}" for k, v in dim.enum.items())
            line += f" [取值: {enum_str}]"
        lines.append(line)
    for col in m.columns:
        line = f"  列: {col.business_name} -> {col.physical}"
        if col.enum:
            enum_str = ", ".join(f"{k}={v}" for k, v in col.enum.items())
            line += f" [取值: {enum_str}]"
        lines.append(line)
    for j in m.joins:
        lines.append(f"  关联: -> {j.model} (key={j.key}, {j.direction})")
    return "\n".join(lines)


def _load_columns(db: Session, datasource_id: int) -> list[ColumnMeta]:
    return (
        db.query(ColumnMeta)
        .join(TableMeta, ColumnMeta.table_id == TableMeta.id)
        .filter(TableMeta.datasource_id == datasource_id)
        .all()
    )


def _build_physical_schema(db: Session, datasource_id: int) -> dict[str, list[dict]]:
    """构建物理 schema（表名 → 列清单），经敏感对象黑名单过滤（is_sensitive 为 False）。"""
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


def _do_degrade(db: Session, user: User, ds: Datasource, question: str) -> dict:
    """降级路径：LLM 直接生成 SQL，仅校验语法与字段存在性，标注未验证。"""
    schema = _build_physical_schema(db, ds.id)
    if not schema:
        raise ExecutionError("该数据源尚无元数据，无法降级生成 SQL")
    sql = generate_sql(question, schema, ds.type)
    validate_readonly(sql, ds.type)
    columns = _load_columns(db, ds.id)
    result = correct_and_execute(ds, sql, columns)

    # 降级成功且行数>0 → 同步提交口径草稿
    if result["row_count"] > 0:
        db.add(
            CaliberDraft(
                measure_name="",  # 由管理员裁决时补全
                expression=sql,
                source="degrade",
                source_question=question,
                degrade_sql=sql,
                datasource_id=ds.id,
                status="pending",
            )
        )
        db.commit()

    record = QueryRecord(
        user_id=user.id,
        question=question,
        intent_json="",
        sql=result["sql"],
        source="degrade",
        semantic_model_name="",
        semantic_model_version=None,
        join_path="",
        caliber_source="degrade",
        status="corrected" if result["corrected"] else "success",
        correction_count=result["correction_count"],
        row_count=result["row_count"],
    )
    db.add(record)
    db.commit()

    return {
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "source": "degrade",
        "caliber_source": "degrade",
        "semantic_model_name": "",
        "semantic_model_version": None,
        "join_path": "",
        "corrected": result["corrected"],
        "correction_count": result["correction_count"],
    }


def run_query(db: Session, user: User, ds: Datasource, question: str) -> dict:
    # 1. 取该数据源已生效的语义模型
    models = db.query(SemanticModel).filter(
        SemanticModel.datasource_id == ds.id,
        SemanticModel.status == "active",
    ).all()

    if not models:
        return _do_degrade(db, user, ds, question)

    model_defs: list[SemanticModelDef] = []
    context_parts: list[str] = []
    for sm in models:
        try:
            model_defs.append(parse_semantic_model(sm.yaml_content))
        except SemanticModelError:
            continue
        ctx = _build_model_context(sm)
        if ctx:
            context_parts.append(ctx)
    context = "\n\n".join(context_parts)

    # 2. LLM 生成 Intent
    intent = generate_intent(question, context)

    # 3. 编译（尝试覆盖内）
    try:
        compiled = compile_intent(intent, model_defs, dialect=ds.type)
    except CompileError:
        # 4. 编译失败 → 降级
        return _do_degrade(db, user, ds, question)

    # 5. 执行（含纠错）
    columns = _load_columns(db, ds.id)
    result = correct_and_execute(ds, compiled.sql, columns)

    # 6. 记录（覆盖内）
    sm = next((m for m in models if m.name == intent.get("models", [None])[0]), models[0])
    record = QueryRecord(
        user_id=user.id,
        question=question,
        intent_json=json.dumps(intent, ensure_ascii=False),
        sql=result["sql"],
        source="compile",
        semantic_model_name=sm.name,
        semantic_model_version=sm.version,
        join_path=compiled.join_path,
        caliber_source=compiled.caliber_source,
        status="corrected" if result["corrected"] else "success",
        correction_count=result["correction_count"],
        row_count=result["row_count"],
    )
    db.add(record)
    db.commit()

    return {
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
        "source": "compile",
        "caliber_source": compiled.caliber_source,
        "semantic_model_name": sm.name,
        "semantic_model_version": sm.version,
        "join_path": compiled.join_path,
        "corrected": result["corrected"],
        "correction_count": result["correction_count"],
    }

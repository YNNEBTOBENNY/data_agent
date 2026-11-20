"""报表与看板服务：空态配置（LIMIT 1 探测）、持久看板（Intent + 版本引用重编译）。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .compiler.compiler import CompileError, compile_intent
from .executor.engine import correct_and_execute, execute
from .models import Chart, Datasource, SemanticModel
from .semantic.model import parse_semantic_model


def _load_models(db: Session, chart) -> tuple[SemanticModel, list]:
    """加载数据源下所有 active 语义模型，主模型为 chart 引用的模型。"""
    sm = db.query(SemanticModel).filter(
        SemanticModel.name == chart.semantic_model_name,
        SemanticModel.status == "active",
    ).first()
    others = db.query(SemanticModel).filter(
        SemanticModel.datasource_id == chart.datasource_id,
        SemanticModel.status == "active",
    ).all()
    model_defs = []
    for m in others:
        try:
            model_defs.append(parse_semantic_model(m.yaml_content))
        except Exception:  # noqa: BLE001
            continue
    return sm, model_defs


def _compile_chart(chart: Chart, model_defs: list, dialect: str):
    intent = json.loads(chart.intent_json or "{}")
    # 主模型消歧：确保 chart 引用的模型在 intent.models 里
    if chart.semantic_model_name and chart.semantic_model_name not in intent.get("models", []):
        intent["models"] = [chart.semantic_model_name] + intent.get("models", [])
    return compile_intent(intent, model_defs, dialect)


def preview_chart(db: Session, ds: Datasource, chart_config: dict) -> dict:
    """空态配置：校验意图可编译性 + LIMIT 1 探测（仅验证字段存在与聚合合法，不展示业务数据）。"""
    chart = Chart(
        name=chart_config.get("name", ""),
        chart_type=chart_config.get("chart_type", "bar"),
        datasource_id=ds.id,
        intent_json=json.dumps(chart_config.get("intent", {}), ensure_ascii=False),
        semantic_model_name=chart_config["semantic_model_name"],
        semantic_model_version=0,
        user_id=0,
    )
    sm, model_defs = _load_models(db, chart)
    if sm is None:
        raise ValueError(f"语义模型「{chart_config['semantic_model_name']}」不存在")

    compiled = _compile_chart(chart, model_defs, ds.type)

    # LIMIT 1 探测：验证字段引用 + 聚合可执行
    result = execute(ds, compiled.sql, max_rows=1)

    return {
        "valid": True,
        "sql": compiled.sql,
        "columns": result["columns"],
        "sample_rows": result["rows"],
        "semantic_model_name": sm.name,
        "semantic_model_version": sm.version,
    }


def render_chart(db: Session, chart: Chart) -> dict:
    """打开看板：按图表引用的语义模型重编译并执行，返回图表数据。"""
    ds = db.get(Datasource, chart.datasource_id)
    if ds is None:
        return {"id": chart.id, "name": chart.name, "status": "invalid", "error": "数据源不存在"}

    sm, model_defs = _load_models(db, chart)
    if sm is None or not model_defs:
        return {"id": chart.id, "name": chart.name, "status": "invalid", "error": "语义模型不存在"}

    try:
        compiled = _compile_chart(chart, model_defs, ds.type)
    except CompileError as e:
        return {"id": chart.id, "name": chart.name, "status": "invalid", "error": f"编译失败: {e}"}

    try:
        result = correct_and_execute(ds, compiled.sql, _load_columns(db, ds.id))
    except Exception as e:  # noqa: BLE001
        return {"id": chart.id, "name": chart.name, "status": "invalid", "error": f"执行失败: {e}"}

    return {
        "id": chart.id,
        "name": chart.name,
        "chart_type": chart.chart_type,
        "status": "active",
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": [[_jsonable(c) for c in row] for row in result["rows"]],
        "row_count": result["row_count"],
        "semantic_model_name": sm.name,
        "semantic_model_version": chart.semantic_model_version,
    }


def _find_next_dimension(model_defs: list, dimension: str) -> str | None:
    """在语义模型里查找维度的层级，返回下一级维度名。"""
    for m in model_defs:
        for d in m.dimensions:
            if d.business_name == dimension and d.hierarchy:
                try:
                    idx = d.hierarchy.index(dimension)
                except ValueError:
                    continue
                if idx + 1 < len(d.hierarchy):
                    return d.hierarchy[idx + 1]
    return None


def drill_chart(db: Session, chart: Chart, dimension: str, value: str, base_filters: list | None = None) -> dict:
    """维度下钻：以元素值作过滤，切到层级下一级维度，重编译执行。"""
    ds = db.get(Datasource, chart.datasource_id)
    if ds is None:
        raise ValueError("数据源不存在")
    sm, model_defs = _load_models(db, chart)

    intent = json.loads(chart.intent_json or "{}")
    if chart.semantic_model_name and chart.semantic_model_name not in intent.get("models", []):
        intent["models"] = [chart.semantic_model_name] + intent.get("models", [])

    next_dimension = _find_next_dimension(model_defs, dimension)

    filters = list(base_filters or [])
    filters.append({"field": dimension, "op": "=", "value": value})
    intent["filters"] = filters

    if next_dimension:
        dims = intent.get("dimensions", []) or []
        intent["dimensions"] = [next_dimension if d == dimension else d for d in dims] or [next_dimension]

    compiled = compile_intent(intent, model_defs, ds.type)
    result = correct_and_execute(ds, compiled.sql, _load_columns(db, ds.id))

    return {
        "dimension": next_dimension or dimension,
        "filters": filters,
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": [[_jsonable(c) for c in row] for row in result["rows"]],
        "row_count": result["row_count"],
    }


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

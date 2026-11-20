"""语义模型：YAML 解析、校验、结构化访问。

字段最低标准：字段含义、单位或枚举值、表间关联（join key）。
"""
from dataclasses import dataclass, field

import yaml


@dataclass
class Column:
    business_name: str
    physical: str
    type: str = ""
    unit: str = ""
    enum: dict = field(default_factory=dict)


@dataclass
class Measure:
    business_name: str
    expression: str
    description: str = ""


@dataclass
class Dimension:
    business_name: str
    physical: str
    hierarchy: list[str] = field(default_factory=list)
    enum: dict = field(default_factory=dict)


@dataclass
class Join:
    model: str
    key: str
    direction: str = "left"
    foreign_key: str = ""


@dataclass
class SemanticModelDef:
    name: str
    table: str
    columns: list[Column] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)


class SemanticModelError(Exception):
    pass


def parse_semantic_model(yaml_content: str) -> SemanticModelDef:
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise SemanticModelError(f"YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise SemanticModelError("语义模型必须是 YAML 映射")

    model = data.get("model")
    table = data.get("table")
    if not model or not table:
        raise SemanticModelError("语义模型缺少 model 或 table 字段")

    columns = [_parse_column(c) for c in data.get("columns", [])]
    measures = [_parse_measure(m) for m in data.get("measures", [])]
    dimensions = [_parse_dimension(d) for d in data.get("dimensions", [])]
    joins = [_parse_join(j) for j in data.get("joins", [])]

    # 同名度量冲突检测（仅同名显性冲突）
    seen: dict[str, str] = {}
    for m in measures:
        if m.business_name in seen and seen[m.business_name] != m.expression:
            raise SemanticModelError(
                f"口径冲突: 度量「{m.business_name}」对应多个不同表达式: "
                f"{seen[m.business_name]} vs {m.expression}"
            )
        seen[m.business_name] = m.expression

    return SemanticModelDef(
        name=model,
        table=table,
        columns=columns,
        measures=measures,
        dimensions=dimensions,
        joins=joins,
    )


def _parse_column(c: dict) -> Column:
    return Column(
        business_name=c.get("business_name", ""),
        physical=c.get("physical", ""),
        type=str(c.get("type", "")),
        unit=c.get("unit", ""),
        enum=c.get("enum") or {},
    )


def _parse_measure(m: dict) -> Measure:
    return Measure(
        business_name=m.get("business_name", ""),
        expression=m.get("expression", ""),
        description=m.get("description", ""),
    )


def _parse_dimension(d: dict) -> Dimension:
    return Dimension(
        business_name=d.get("business_name", ""),
        physical=d.get("physical", ""),
        hierarchy=list(d.get("hierarchy", [])),
        enum=d.get("enum") or {},
    )


def _parse_join(j: dict) -> Join:
    return Join(
        model=j.get("model", ""),
        key=j.get("key", ""),
        direction=j.get("direction", "left"),
        foreign_key=j.get("foreign_key", ""),
    )

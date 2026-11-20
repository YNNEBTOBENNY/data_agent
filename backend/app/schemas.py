from pydantic import BaseModel, Field


class DatasourceCreate(BaseModel):
    name: str
    type: str = Field(pattern="^(mysql|postgres)$")
    host: str = ""
    port: int = 0
    db_name: str = ""
    readonly_user: str = ""
    readonly_password: str = ""
    timezone: str = "UTC"


class DatasourceOut(BaseModel):
    id: int
    name: str
    type: str
    host: str
    port: int
    db_name: str
    timezone: str
    status: str

    class Config:
        from_attributes = True


class SemanticModelCreate(BaseModel):
    name: str
    datasource_id: int
    table_name: str
    yaml_content: str


class QueryRequest(BaseModel):
    question: str
    datasource_id: int
    dialect: str = "mysql"


class QueryResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    source: str  # compile | degrade
    caliber_source: str
    semantic_model_name: str
    semantic_model_version: int | None = None
    join_path: str
    corrected: bool = False
    correction_count: int = 0


class ChartCreate(BaseModel):
    """空态配置：选度量/维度/图表类型，校验可编译性 + LIMIT 1 探测。"""
    name: str
    chart_type: str = Field(pattern="^(bar|line|pie|table)$")
    datasource_id: int
    intent: dict  # measures/dimensions/time_group/filters/derived_measures 等
    semantic_model_name: str


class DashboardCreate(BaseModel):
    name: str
    charts: list[ChartCreate]


class DrillRequest(BaseModel):
    dimension: str
    value: str
    base_filters: list[dict] = []

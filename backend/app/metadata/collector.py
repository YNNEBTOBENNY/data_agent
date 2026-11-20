"""元数据采集：连接数据源，抓取表名/字段名/类型/注释，经敏感对象黑名单过滤后入库。"""
from sqlalchemy import create_engine, inspect, text

from ..config import get_settings
from ..models import ColumnMeta, Datasource, TableMeta
from ..llm.sanitizer import is_sensitive_name


def _build_datasource_url(ds: Datasource) -> str:
    if ds.type == "mysql":
        return (
            f"mysql+pymysql://{ds.readonly_user}:{ds.readonly_password}"
            f"@{ds.host}:{ds.port}/{ds.db_name}?charset=utf8mb4"
        )
    if ds.type == "postgres":
        return (
            f"postgresql+psycopg://{ds.readonly_user}:{ds.readonly_password}"
            f"@{ds.host}:{ds.port}/{ds.db_name}"
        )
    raise ValueError(f"不支持的数据源类型: {ds.type}")


def test_connection(ds: Datasource) -> bool:
    engine = create_engine(_build_datasource_url(ds), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    finally:
        engine.dispose()


def _collect_columns(engine, table_name: str, ds_type: str) -> list[dict]:
    inspector = inspect(engine)
    cols = inspector.get_columns(table_name)
    comments = {}
    try:
        if ds_type == "mysql":
            comments = _mysql_column_comments(engine, table_name)
        elif ds_type == "postgres":
            comments = _pg_column_comments(engine, table_name)
    except Exception:  # noqa: BLE001 - 注释获取失败不影响采集
        comments = {}
    return [
        {
            "name": c["name"],
            "type": str(c.get("type", "")),
            "comment": comments.get(c["name"], "") or (c.get("comment") or ""),
        }
        for c in cols
    ]


def _mysql_column_comments(engine, table_name: str) -> dict[str, str]:
    schema = engine.url.database
    sql = text(
        "SELECT COLUMN_NAME, COLUMN_COMMENT FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"s": schema, "t": table_name}).fetchall()
    return {r[0]: r[1] or "" for r in rows}


def _pg_column_comments(engine, table_name: str) -> dict[str, str]:
    schema = "public"
    sql = text(
        "SELECT a.attname, COALESCE(d.description, '') FROM pg_attribute a "
        "LEFT JOIN pg_description d ON d.objoid=a.attrelid AND d.objsubid=a.attnum "
        "JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=:s AND c.relname=:t AND a.attnum>0 AND NOT a.attisdropped"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"s": schema, "t": table_name}).fetchall()
    return {r[0]: r[1] or "" for r in rows}


def collect(ds: Datasource, db) -> int:
    """采集数据源元数据，返回采集到的表数量。"""
    settings = get_settings()

    engine = create_engine(_build_datasource_url(ds), pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        for tname in table_names:
            if is_sensitive_name(tname, settings.sensitive_keyword_list):
                continue
            table = TableMeta(datasource_id=ds.id, name=tname)
            db.add(table)
            db.flush()
            for col in _collect_columns(engine, tname, ds.type):
                sensitive = is_sensitive_name(col["name"], settings.sensitive_keyword_list) or is_sensitive_name(
                    col["comment"], settings.sensitive_keyword_list
                )
                db.add(
                    ColumnMeta(
                        table_id=table.id,
                        name=col["name"],
                        type=col["type"],
                        comment=col["comment"],
                        is_sensitive=sensitive,
                    )
                )
        db.commit()
        return len(table_names)
    finally:
        engine.dispose()

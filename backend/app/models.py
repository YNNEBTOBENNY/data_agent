import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Role(str, enum.Enum):
    admin = "admin"
    member = "member"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    password_version: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.member)
    timezone: Mapped[str] = mapped_column(String(32), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Datasource(Base):
    __tablename__ = "datasources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16))  # mysql | postgres
    host: Mapped[str] = mapped_column(String(128))
    port: Mapped[int] = mapped_column(Integer)
    db_name: Mapped[str] = mapped_column(String(64))
    readonly_user: Mapped[str] = mapped_column(String(64))
    readonly_password: Mapped[str] = mapped_column(String(256))
    timezone: Mapped[str] = mapped_column(String(32), default="UTC")
    timezone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TableMeta(Base):
    __tablename__ = "table_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    comment: Mapped[str] = mapped_column(Text, default="")


class ColumnMeta(Base):
    __tablename__ = "column_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("table_meta.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(Text, default="")
    # 敏感对象黑名单标记（出域过滤用），非业务列级黑名单
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)


class SemanticModel(Base):
    __tablename__ = "semantic_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id"), index=True)
    table_name: Mapped[str] = mapped_column(String(128))
    yaml_content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | pending_review
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QueryRecord(Base):
    __tablename__ = "query_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    intent_json: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="compile")  # compile | degrade
    semantic_model_name: Mapped[str] = mapped_column(String(64), default="")
    semantic_model_version: Mapped[int] = mapped_column(Integer, nullable=True)
    join_path: Mapped[str] = mapped_column(Text, default="")
    caliber_source: Mapped[str] = mapped_column(String(32), default="")  # model | temporary | degrade
    status: Mapped[str] = mapped_column(String(16), default="success")  # success | failed | corrected
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CaliberDraft(Base):
    """口径固化请求草稿（降级自动提炼 / 临时口径 / 手动提交）。"""

    __tablename__ = "caliber_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    measure_name: Mapped[str] = mapped_column(String(64))
    expression: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="degrade")  # degrade | temporary | manual
    source_question: Mapped[str] = mapped_column(Text, default="")
    degrade_sql: Mapped[str] = mapped_column(Text, default="")
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | adopted | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Chart(Base):
    """看板图表：保存查询意图 + 语义模型版本引用（非 SQL 快照）。"""

    __tablename__ = "charts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(ForeignKey("dashboards.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    chart_type: Mapped[str] = mapped_column(String(16))  # bar | line | pie | table
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id"), index=True)
    intent_json: Mapped[str] = mapped_column(Text)
    semantic_model_name: Mapped[str] = mapped_column(String(64))
    semantic_model_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending(待数据) | active | invalid
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchSession(Base):
    """研究会话：围绕一个主题的多轮分析。"""

    __tablename__ = "research_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(Text)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasources.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | converged | ended
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResearchRound(Base):
    """研究轮次：问题、建议、SQL、结果摘要、小结、验证状态。"""

    __tablename__ = "research_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("research_sessions.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(16), default="execute")  # execute | confirm | modify
    sql: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="")  # compile | degrade
    result_summary: Mapped[str] = mapped_column(Text, default="")  # 相对分档事实 JSON
    summary_text: Mapped[str] = mapped_column(Text, default="")  # 一句话小结
    validation_status: Mapped[str] = mapped_column(String(32), default="")  # 编译/降级/纠错/临时口径
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_settings

settings = get_settings()

# SQLite 相对路径统一解析到 backend 目录下，避免因 cwd 不同产生多份 meta.db
meta_db_url = settings.meta_db_url
if meta_db_url.startswith("sqlite"):
    raw_path = meta_db_url.split("///")[-1]
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (Path(__file__).resolve().parents[1] / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    meta_db_url = f"sqlite:///{db_path}"

engine = create_engine(
    meta_db_url,
    connect_args={"check_same_thread": False} if meta_db_url.startswith("sqlite") else {},
    future=True,
)

# SQLite 开启 WAL 模式，解决 API 进程与 worker 进程并发写锁冲突
if meta_db_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

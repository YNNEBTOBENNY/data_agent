from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..executor.engine import ExecutionError
from ..models import Datasource, User
from ..service import run_query
from .deps import get_current_user

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=schemas.QueryResult)
def query(
    body: schemas.QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ds = db.get(Datasource, body.datasource_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        return run_query(db, user, ds, body.question)
    except ExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"查询失败: {e}") from e

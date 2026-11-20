from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import l2_agent
from ..db import get_db
from ..models import Datasource, User
from .deps import get_current_user

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/query")
def agent_query(
    question: str,
    datasource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ds = db.get(Datasource, datasource_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        return l2_agent.run_agent(db, user, ds, question)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"agent 执行失败: {e}") from e

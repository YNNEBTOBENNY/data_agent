from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..metadata import collector
from ..models import ColumnMeta, Datasource, TableMeta, User
from .deps import require_admin

router = APIRouter(prefix="/datasources", tags=["datasources"])


@router.post("", response_model=schemas.DatasourceOut)
def create_datasource(
    body: schemas.DatasourceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    ds = Datasource(**body.model_dump())
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


@router.get("")
def list_datasources(db: Session = Depends(get_db)):
    return db.query(Datasource).all()


@router.get("/{ds_id}")
def get_datasource(ds_id: int, db: Session = Depends(get_db)):
    ds = db.get(Datasource, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return ds


@router.post("/{ds_id}/collect")
def collect_metadata(ds_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    ds = db.get(Datasource, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if not collector.test_connection(ds):
        raise HTTPException(status_code=400, detail="数据源连接失败，请检查只读账号配置")
    # 清理旧元数据后重采集
    tables = db.query(TableMeta).filter(TableMeta.datasource_id == ds_id).all()
    for t in tables:
        db.delete(t)
    db.commit()
    count = collector.collect(ds, db)
    return {"collected_tables": count}


@router.post("/{ds_id}/verify-timezone")
def verify_timezone(ds_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """接入时人工确认时区（V1：管理员确认后标记可信）。"""
    ds = db.get(Datasource, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    ds.timezone_verified = True
    db.commit()
    return {"timezone": ds.timezone, "verified": True}


@router.delete("/{ds_id}")
def delete_datasource(ds_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """删除数据源及其元数据。"""
    ds = db.get(Datasource, ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    # 删关联的元数据（表/列）
    tables = db.query(TableMeta).filter(TableMeta.datasource_id == ds_id).all()
    for t in tables:
        db.query(ColumnMeta).filter(ColumnMeta.table_id == t.id).delete()
        db.delete(t)
    db.delete(ds)
    db.commit()
    return {"deleted": ds_id}

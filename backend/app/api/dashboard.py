import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import dashboard_service, schemas
from ..db import get_db
from ..models import Chart, Dashboard, Datasource, SemanticModel, User
from .deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.post("/chart/preview")
def preview_chart(
    body: schemas.ChartCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ds = db.get(Datasource, body.datasource_id)
    if not ds:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        return dashboard_service.preview_chart(db, ds, body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"图表配置校验失败: {e}") from e


@router.post("")
def create_dashboard(
    body: schemas.DashboardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dashboard = Dashboard(name=body.name, user_id=user.id)
    db.add(dashboard)
    db.flush()

    for c in body.charts:
        ds = db.get(Datasource, c.datasource_id)
        if not ds:
            raise HTTPException(status_code=404, detail=f"数据源 {c.datasource_id} 不存在")
        sm = db.query(SemanticModel).filter(SemanticModel.name == c.semantic_model_name).first()
        if not sm:
            raise HTTPException(status_code=404, detail=f"语义模型 {c.semantic_model_name} 不存在")

        chart = Chart(
            dashboard_id=dashboard.id,
            name=c.name,
            chart_type=c.chart_type,
            datasource_id=c.datasource_id,
            intent_json=json.dumps(c.intent, ensure_ascii=False),
            semantic_model_name=c.semantic_model_name,
            semantic_model_version=sm.version,  # 保存时锁定当前版本号
            status="pending",  # 待数据图表
            user_id=user.id,
        )
        db.add(chart)

    db.commit()
    return {"id": dashboard.id, "name": dashboard.name}


@router.get("")
def list_dashboards(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Dashboard).filter(Dashboard.user_id == user.id).all()


@router.get("/{dashboard_id}")
def open_dashboard(
    dashboard_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dashboard = db.get(Dashboard, dashboard_id)
    if not dashboard or dashboard.user_id != user.id:
        raise HTTPException(status_code=404, detail="看板不存在")

    charts = (
        db.query(Chart)
        .filter(Chart.dashboard_id == dashboard_id)
        .order_by(Chart.id)
        .all()
    )
    rendered = [dashboard_service.render_chart(db, c) for c in charts]
    return {"id": dashboard.id, "name": dashboard.name, "charts": rendered}


@router.post("/chart/{chart_id}/drill")
def drill_chart(
    chart_id: int,
    body: schemas.DrillRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chart = db.get(Chart, chart_id)
    if not chart or chart.user_id != user.id:
        raise HTTPException(status_code=404, detail="图表不存在")
    try:
        return dashboard_service.drill_chart(db, chart, body.dimension, body.value, body.base_filters)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"下钻失败: {e}") from e

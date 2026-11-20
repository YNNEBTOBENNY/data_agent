from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import CaliberDraft, SemanticModel, User
from ..semantic.model import SemanticModelError, parse_semantic_model
from .deps import require_admin

router = APIRouter(prefix="/semantic", tags=["semantic"])


@router.post("")
def create_semantic_model(
    body: schemas.SemanticModelCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        parsed = parse_semantic_model(body.yaml_content)
    except SemanticModelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if parsed.name != body.name:
        raise HTTPException(status_code=400, detail=f"模型名不一致: YAML 中为 {parsed.name}")

    existing = db.query(SemanticModel).filter(SemanticModel.name == body.name).first()
    if existing:
        existing.yaml_content = body.yaml_content
        existing.version += 1
        existing.status = "active"
        existing.table_name = body.table_name
        db.commit()
        return {"id": existing.id, "name": existing.name, "version": existing.version}

    sm = SemanticModel(**body.model_dump(), status="active", version=1)
    db.add(sm)
    db.commit()
    db.refresh(sm)
    return {"id": sm.id, "name": sm.name, "version": sm.version}


@router.get("")
def list_semantic_models(db: Session = Depends(get_db)):
    return db.query(SemanticModel).all()


@router.get("/{sm_id}/validate")
def validate_semantic_model(sm_id: int, db: Session = Depends(get_db)):
    sm = db.get(SemanticModel, sm_id)
    if not sm:
        raise HTTPException(status_code=404, detail="语义模型不存在")
    try:
        parsed = parse_semantic_model(sm.yaml_content)
    except SemanticModelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "name": parsed.name,
        "table": parsed.table,
        "measures": len(parsed.measures),
        "dimensions": len(parsed.dimensions),
        "columns": len(parsed.columns),
        "joins": len(parsed.joins),
    }


@router.get("/fields")
def get_model_fields(name: str, db: Session = Depends(get_db)):
    sm = db.query(SemanticModel).filter(SemanticModel.name == name).first()
    if not sm:
        raise HTTPException(status_code=404, detail="语义模型不存在")
    try:
        parsed = parse_semantic_model(sm.yaml_content)
    except SemanticModelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "measures": [m.business_name for m in parsed.measures],
        "dimensions": [d.business_name for d in parsed.dimensions],
    }


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """口径固化草稿列表（降级自动提炼 / 临时口径 / 手动提交）。"""
    return db.query(CaliberDraft).order_by(CaliberDraft.id.desc()).all()


@router.post("/drafts/{draft_id}/resolve")
def resolve_draft(
    draft_id: int,
    decision: str,  # adopted | rejected
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    draft = db.get(CaliberDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if decision not in ("adopted", "rejected"):
        raise HTTPException(status_code=400, detail="decision 只能是 adopted 或 rejected")
    draft.status = decision
    db.commit()
    return {"id": draft.id, "status": draft.status}

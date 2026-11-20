from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import research_service, schemas
from ..db import get_db
from ..models import ResearchRound, ResearchSession, User
from .deps import get_current_user

router = APIRouter(prefix="/research", tags=["research"])


@router.post("")
def create_session(
    topic: str,
    datasource_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        s = research_service.create_session(db, user, topic, datasource_id)
        return {"id": s.id, "topic": s.topic, "status": s.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{session_id}/round")
def run_round(
    session_id: int,
    question: str,
    action: str = "execute",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(ResearchSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        return research_service.run_round(db, user, session, question, action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"本轮执行失败: {e}") from e


@router.post("/{session_id}/converge")
def converge(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(ResearchSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return research_service.converge(db, session)


@router.get("/{session_id}")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(ResearchSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    rounds = (
        db.query(ResearchRound)
        .filter(ResearchRound.session_id == session_id)
        .order_by(ResearchRound.round_number)
        .all()
    )
    return {
        "id": session.id,
        "topic": session.topic,
        "status": session.status,
        "datasource_id": session.datasource_id,
        "rounds": [
            {
                "round_number": r.round_number,
                "question": r.question,
                "suggestion": r.suggestion,
                "sql": r.sql,
                "source": r.source,
                "row_count": r.row_count,
                "validation_status": r.validation_status,
            }
            for r in rounds
        ],
    }


@router.get("/{session_id}/export")
def export_report(
    session_id: int,
    format: str = "markdown",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(ResearchSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if format == "word":
        data = research_service.export_word(db, session)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="research_{session_id}.docx"'},
        )
    md = research_service.export_markdown(db, session)
    return Response(content=md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="research_{session_id}.md"'})


@router.get("")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ResearchSession).filter(ResearchSession.user_id == user.id).all()

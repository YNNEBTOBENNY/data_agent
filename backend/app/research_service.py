"""研究编排服务：多轮分析的执行、建议、收敛与摘要。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .llm.adapter import get_llm
from .llm.sanitizer import replace_pii
from .models import Datasource, ResearchRound, ResearchSession, User
from .service import run_query

MAX_ROUNDS = 10


def create_session(db: Session, user: User, topic: str, datasource_id: int) -> ResearchSession:
    ds = db.get(Datasource, datasource_id)
    if ds is None:
        raise ValueError("数据源不存在")
    session = ResearchSession(user_id=user.id, topic=topic, datasource_id=datasource_id, status="active")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _result_shape(result: dict) -> dict:
    """把查询结果压缩成「形状」摘要（不含绝对聚合数值，只含行数/列名/数值列分布档位）。"""
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    row_count = result.get("row_count", 0)
    # 数值列分布档位：只描述「是否全 0 / 是否含空 / 大小量级」，不给出绝对数值
    numeric_info = []
    for i, c in enumerate(columns):
        vals = [r[i] for r in rows if i < len(r)]
        numeric_vals = []
        for v in vals:
            try:
                numeric_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        if numeric_vals:
            n = len(numeric_vals)
            zeros = sum(1 for v in numeric_vals if v == 0)
            nulls = row_count - n
            avg = sum(numeric_vals) / n if n else 0
            mag = "大" if abs(avg) > 100000 else ("中" if abs(avg) > 100 else "小")
            numeric_info.append(f"{c}(数量级:{mag}, 全0占比:{zeros}/{n}, 空值:{nulls})")
    return {"row_count": row_count, "columns": columns, "numeric_info": numeric_info}


def _build_suggestion_prompt(topic: str, rounds: list[dict]) -> str:
    lines = [f"研究主题：{topic}", "", "已完成的分析轮次："]
    for r in rounds:
        lines.append(
            f"- 第{r['round_number']}轮「{r['question']}」→ {r['row_count']} 行, 列 {r['columns']}"
        )
        for ni in r.get("numeric_info", []):
            lines.append(f"    {ni}")
    lines.append("")
    lines.append("请基于以上已完成的分析，提出一个**下一步最值得查的数据问题**（自然语言，一句即可）。")
    lines.append("只输出问题本身，不要解释。")
    return "\n".join(lines)


def run_round(db: Session, user: User, session: ResearchSession, question: str, action: str = "execute") -> dict:
    """执行一轮研究：查数 + 生成下一步建议 + 落库。"""
    if session.status != "active":
        raise ValueError("会话已结束，不能继续")

    round_number = (
        db.query(ResearchRound).filter(ResearchRound.session_id == session.id).count() + 1
    )
    if round_number > MAX_ROUNDS:
        raise ValueError(f"已达 {MAX_ROUNDS} 轮上限，请收敛")

    ds = db.get(Datasource, session.datasource_id)
    result = run_query(db, user, ds, question)

    shape = _result_shape(result)
    round_record = ResearchRound(
        session_id=session.id,
        round_number=round_number,
        question=question,
        action=action,
        sql=result["sql"],
        source=result["source"],
        result_summary=json.dumps(shape, ensure_ascii=False),
        summary_text="",
        validation_status=result["source"],
        row_count=result["row_count"],
    )
    db.add(round_record)
    db.commit()
    db.refresh(round_record)

    # 生成下一步建议
    suggestion = _generate_suggestion(db, session)

    return {
        "round_number": round_number,
        "question": question,
        "sql": result["sql"],
        "source": result["source"],
        "columns": result["columns"],
        "rows": [[_jsonable(c) for c in row] for row in result["rows"][:20]],
        "row_count": result["row_count"],
        "suggestion": suggestion,
    }


def _generate_suggestion(db: Session, session: ResearchSession) -> str:
    """基于历史轮次（问题 + 结果形状）生成下一步建议。"""
    rounds = (
        db.query(ResearchRound)
        .filter(ResearchRound.session_id == session.id)
        .order_by(ResearchRound.round_number)
        .all()
    )
    history = []
    for r in rounds:
        shape = {}
        try:
            shape = json.loads(r.result_summary or "{}")
        except json.JSONDecodeError:
            pass
        history.append(
            {
                "round_number": r.round_number,
                "question": r.question,
                "row_count": shape.get("row_count", r.row_count),
                "columns": shape.get("columns", []),
                "numeric_info": shape.get("numeric_info", []),
            }
        )
    prompt = _build_suggestion_prompt(session.topic, history)
    try:
        suggestion = get_llm().chat_text(
            [{"role": "system", "content": "你是数据分析助手，帮助用户做探索式分析。"},
             {"role": "user", "content": replace_pii(prompt)}],
            temperature=0.3,
        ).strip()
    except Exception:
        suggestion = "（建议生成失败，可自行输入下一个问题）"
    return suggestion


def _judge_sufficiency(rounds: list[ResearchRound]) -> dict:
    """数据充分性规则判定：有效轮<2 或非空占比<1/3 → 数据不足。"""
    non_empty = [r for r in rounds if r.row_count > 0]
    total = len(rounds)
    non_empty_count = len(non_empty)
    ratio = non_empty_count / total if total else 0
    insufficient = non_empty_count < 2 or (total > 0 and ratio < 1 / 3)
    return {
        "total_rounds": total,
        "non_empty_rounds": non_empty_count,
        "ratio": ratio,
        "insufficient": insufficient,
    }


def converge(db: Session, session: ResearchSession) -> dict:
    """收敛：数据充分性判定 + 生成摘要。"""
    rounds = (
        db.query(ResearchRound)
        .filter(ResearchRound.session_id == session.id)
        .order_by(ResearchRound.round_number)
        .all()
    )
    suff = _judge_sufficiency(rounds)

    # 本地计算结论事实（行数、非空轮数等）
    conclusions = _generate_conclusions(session, rounds, suff)

    session.status = "converged"
    db.commit()

    return {
        "topic": session.topic,
        "total_rounds": suff["total_rounds"],
        "non_empty_rounds": suff["non_empty_rounds"],
        "insufficient": suff["insufficient"],
        "conclusions": conclusions,
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


def _generate_conclusions(session: ResearchSession, rounds: list[ResearchRound], suff: dict) -> list[str]:
    """结论区：LLM 只写句式（带轮次占位），本地回填真实数值（行数）。"""
    if suff["insufficient"]:
        prefix = "数据不足，以下为初步判断："
    else:
        prefix = ""

    # 本地可确定的事实
    facts = [
        f"共执行 {suff['total_rounds']} 轮分析，其中 {suff['non_empty_rounds']} 轮返回了非空结果。"
    ]
    for r in rounds:
        facts.append(f"第 {r.round_number} 轮「{r.question}」返回 {r.row_count} 行。")

    # LLM 措辞：基于问题 + 形状生成一句总结
    prompt_lines = [f"研究主题：{session.topic}", "各轮问题与结果行数："]
    for r in rounds:
        prompt_lines.append(f"- 第{r.round_number}轮「{r.question}」：{r.row_count} 行")
    prompt_lines.append("")
    prompt_lines.append("请用 1-3 句话总结这次研究的发现（不要编造具体数值，只概括结论）。")
    try:
        llm_summary = get_llm().chat_text(
            [{"role": "system", "content": "你是数据分析总结助手。"},
             {"role": "user", "content": replace_pii("\n".join(prompt_lines))}],
            temperature=0.3,
        ).strip()
    except Exception:
        llm_summary = "（总结生成失败）"

    conclusions = [prefix + llm_summary] if prefix else [llm_summary]
    conclusions.extend(facts)
    return conclusions


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _build_report(db: Session, session: ResearchSession) -> dict:
    """构建报告结构（结论 + 过程 + 统计），供摘要/导出复用。"""
    rounds = (
        db.query(ResearchRound)
        .filter(ResearchRound.session_id == session.id)
        .order_by(ResearchRound.round_number)
        .all()
    )
    suff = _judge_sufficiency(rounds)
    conclusions = _generate_conclusions(session, rounds, suff)
    return {
        "topic": session.topic,
        "insufficient": suff["insufficient"],
        "conclusions": conclusions,
        "total_rounds": suff["total_rounds"],
        "non_empty_rounds": suff["non_empty_rounds"],
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


def export_markdown(db: Session, session: ResearchSession) -> str:
    """导出 Markdown 报告。"""
    rep = _build_report(db, session)
    lines = [f"# 数据分析研究：{rep['topic']}", ""]
    if rep["insufficient"]:
        lines.append("> 数据不足，以下为初步判断。")
        lines.append("")
    lines.append("## 结论")
    for c in rep["conclusions"]:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("## 过程")
    for r in rep["rounds"]:
        lines.append(f"### 第 {r['round_number']} 轮")
        lines.append(f"- 问题：{r['question']}")
        if r["suggestion"]:
            lines.append(f"- 建议：{r['suggestion']}")
        lines.append(f"- 验证状态：{r['validation_status']}（来源 {r['source']}）")
        lines.append(f"- 结果行数：{r['row_count']}")
        lines.append("")
        lines.append("```sql")
        lines.append(r["sql"])
        lines.append("```")
        lines.append("")
    lines.append("## 统计")
    lines.append(f"- 分析主题：{rep['topic']}")
    lines.append(f"- 总轮次：{rep['total_rounds']}")
    lines.append(f"- 非空轮次：{rep['non_empty_rounds']}")
    return "\n".join(lines)


def export_word(db: Session, session: ResearchSession) -> bytes:
    """导出 Word 报告（.docx 字节）。"""
    import io

    from docx import Document

    rep = _build_report(db, session)
    doc = Document()
    doc.add_heading(f"数据分析研究：{rep['topic']}", level=1)
    if rep["insufficient"]:
        doc.add_paragraph("数据不足，以下为初步判断。")

    doc.add_heading("结论", level=2)
    for c in rep["conclusions"]:
        doc.add_paragraph(c, style="List Bullet")

    doc.add_heading("过程", level=2)
    for r in rep["rounds"]:
        doc.add_heading(f"第 {r['round_number']} 轮", level=3)
        doc.add_paragraph(f"问题：{r['question']}")
        if r["suggestion"]:
            doc.add_paragraph(f"建议：{r['suggestion']}")
        doc.add_paragraph(f"验证状态：{r['validation_status']}（来源 {r['source']}）｜结果行数：{r['row_count']}")
        doc.add_paragraph("SQL：")
        doc.add_paragraph(r["sql"], style="No Spacing")

    doc.add_heading("统计", level=2)
    doc.add_paragraph(f"分析主题：{rep['topic']}")
    doc.add_paragraph(f"总轮次：{rep['total_rounds']}")
    doc.add_paragraph(f"非空轮次：{rep['non_empty_rounds']}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

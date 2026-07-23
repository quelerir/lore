"""Top-level agent arbitration + final answer.

Receives the assembled evidence (context groups, table SQL outcomes) and chooses
what grounds the answer, then makes the single final model call. Guardrails: the
first non-empty SQL result is not automatically correct; results from different
tables are attributed separately, never summed/unioned/joined; conflicting
successes stay explicit; when nothing grounds the question, no answer is invented.
"""
from lore_retrieval.contracts import AgentDecision, ContextGroup, SQLResult, SQLStatus
from lore_retrieval.interfaces import ChatModel


def _section_label(group: ContextGroup) -> str:
    """Heading path as inline provenance, e.g. ``(Компенсации › Премия) ``."""
    path = " › ".join(group.section_path)
    return f"({path}) " if path else ""


def _build_prompt(
    question: str, groups: list[ContextGroup], successes: list[SQLResult], note: str | None
) -> str:
    parts = [
        "Ты — ассистент базы знаний datacraft. Отвечай СТРОГО на основе свидетельств "
        "ниже. Если в них нет ответа — прямо скажи, что в базе знаний нет ответа; не "
        "добавляй фактов извне.",
        "",
        f"Вопрос: {question}",
        "",
    ]
    if groups:
        parts.append(
            "Текстовые свидетельства (самые релевантные — первыми; ссылайся номером [n]):"
        )
        parts.extend(f"[{i}] {_section_label(g)}{g.text}" for i, g in enumerate(groups, 1))
    if successes:
        base = len(groups)
        parts.append("Результаты SQL (каждый отдельно, НЕ объединять; ссылайся номером [n]):")
        parts.extend(
            f"[{base + k}] payload {r.payload_id}: {r.answer_summary}"
            for k, r in enumerate(successes, 1)
        )
    if note == "conflicting_sql_results":
        parts.append("ВНИМАНИЕ: результаты SQL расходятся — представь их раздельно.")
    if groups or successes:
        parts.extend(
            [
                "",
                "Правила ответа:",
                "- Используй только сведения из свидетельств выше.",
                "- К каждому утверждению ставь маркер [n] источника.",
                "- Если сведений недостаточно — скажи об этом, не догадывайся.",
            ]
        )
    return "\n".join(parts)


async def arbitrate_and_answer(
    model: ChatModel,
    question: str,
    groups: list[ContextGroup],
    sql_results: list[SQLResult],
) -> AgentDecision:
    successes = [r for r in sql_results if r.status is SQLStatus.success]

    # Judge conflict on real content: use the summary when present, else the rows,
    # so two successes with distinct rows but no summary aren't collapsed to {None}.
    signatures = {
        r.answer_summary if r.answer_summary is not None else repr(r.rows) for r in successes
    }
    note: str | None = None
    if len(successes) > 1 and len(signatures) > 1:
        note = "conflicting_sql_results"  # keep explicit; never merge across tables

    # Nothing grounds the question: do not invent facts, do not call the model.
    if not groups and not successes:
        return AgentDecision(
            answer="",
            used_evidence_chunk_ids=[],
            used_sql_payload_ids=[],
            citations=[],
            note="no_grounded_evidence",
        )

    used_evidence = [cid for g in groups for cid in g.chunk_ids]
    citations = [cid for g in groups for cid in g.citations]
    used_sql = [r.payload_id for r in successes]
    # index [n] shown to the model -> that group's contributing chunk_ids
    evidence_map = {i: list(g.citations) for i, g in enumerate(groups, 1)}
    # SQL successes continue the [n] sequence after the text groups -> anchor chunk_id
    base = len(groups)
    sql_evidence_map = {base + k: r.chunk_id for k, r in enumerate(successes, 1)}

    answer = await model.generate(_build_prompt(question, groups, successes, note))
    return AgentDecision(
        answer=answer,
        used_evidence_chunk_ids=used_evidence,
        used_sql_payload_ids=used_sql,
        citations=citations,
        note=note,
        evidence_map=evidence_map,
        sql_evidence_map=sql_evidence_map,
    )

"""Top-level agent arbitration + final answer.

Receives the assembled evidence (context groups, table SQL outcomes) and chooses
what grounds the answer, then makes the single final model call. Guardrails: the
first non-empty SQL result is not automatically correct; results from different
tables are attributed separately, never summed/unioned/joined; conflicting
successes stay explicit; when nothing grounds the question, no answer is invented.
"""
from lore_retrieval.contracts import AgentDecision, ContextGroup, SQLResult, SQLStatus
from lore_retrieval.interfaces import ChatModel


def _build_prompt(
    question: str, groups: list[ContextGroup], successes: list[SQLResult], note: str | None
) -> str:
    parts = [f"Вопрос: {question}", ""]
    if groups:
        parts.append("Текстовые свидетельства:")
        parts.extend(f"- [{g.section_id}] {g.text}" for g in groups)
    if successes:
        parts.append("Результаты SQL (каждый отдельно, не объединять):")
        parts.extend(f"- payload {r.payload_id}: {r.answer_summary}" for r in successes)
    if note == "conflicting_sql_results":
        parts.append("ВНИМАНИЕ: результаты SQL расходятся — представь их раздельно.")
    return "\n".join(parts)


async def arbitrate_and_answer(
    model: ChatModel,
    question: str,
    groups: list[ContextGroup],
    sql_results: list[SQLResult],
) -> AgentDecision:
    successes = [r for r in sql_results if r.status is SQLStatus.success]

    note: str | None = None
    if len(successes) > 1 and len({r.answer_summary for r in successes}) > 1:
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

    answer = await model.generate(_build_prompt(question, groups, successes, note))
    return AgentDecision(
        answer=answer,
        used_evidence_chunk_ids=used_evidence,
        used_sql_payload_ids=used_sql,
        citations=citations,
        note=note,
    )

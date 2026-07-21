from lore_retrieval.contracts import QueryRequirements, TableProfile
from lore_retrieval.pipeline.feasibility import assess_feasibility, feasibility_predicate
from lore_retrieval.pipeline.table_lane import select_table_candidates

PROFILE = TableProfile(
    payload_id="pay1",
    columns=["оклад", "отдел", "дата приёма"],
    sample_values={"отдел": ["IT", "HR"]},
)


def test_feasible_when_measures_map_to_columns():
    ok, reason = assess_feasibility(PROFILE, QueryRequirements(measures=["оклад"]))
    assert ok and reason is None


def test_infeasible_when_no_column_for_requirement():
    ok, reason = assess_feasibility(PROFILE, QueryRequirements(filters=["город"]))
    assert not ok and "город" in reason


def test_value_absent_from_samples_does_not_reject():
    # 'Продажи' is not in the отдел samples, but the отдел column exists -> feasible.
    ok, _ = assess_feasibility(PROFILE, QueryRequirements(filters=["отдел = Продажи"]))
    assert ok


def test_no_requirements_is_recall_first_feasible():
    ok, _ = assess_feasibility(PROFILE, QueryRequirements())
    assert ok


def test_predicate_drops_infeasible_table_in_selection():
    profiles = {"pay1": PROFILE}
    payload_by_chunk = {"t1": "pay1"}
    feasible = feasibility_predicate(profiles, payload_by_chunk, QueryRequirements(filters=["город"]))
    picked = select_table_candidates([("t1", 2.0)], payload_by_chunk, feasible=feasible)
    assert picked == []                       # infeasible schema not selected

    feasible_ok = feasibility_predicate(profiles, payload_by_chunk, QueryRequirements(measures=["оклад"]))
    picked_ok = select_table_candidates([("t1", 2.0)], payload_by_chunk, feasible=feasible_ok)
    assert [c.payload_id for c in picked_ok] == ["pay1"]

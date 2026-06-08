from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from culvia.recommendation import numeric_column

ACCEPTANCE_SCORE_COLUMNS = {
    "model": "recommendation_0_10",
    "llm": "llm_review_overall_0_10",
}


@dataclass(frozen=True)
class AcceptancePolicy:
    pick_threshold: float = 7.0
    reject_threshold: float = 5.5
    star_scale: float = 2.0
    min_rating: int = 1
    max_rating: int = 5


@dataclass(frozen=True)
class AcceptancePlan:
    marks: list[dict[str, object]]
    skipped: int
    source: str


DEFAULT_ACCEPTANCE_POLICY = AcceptancePolicy()


def normalize_acceptance_basis(value: object) -> str:
    return "llm" if value == "llm" else "model"


def manual_rating_from_score(value: float | None, policy: AcceptancePolicy = DEFAULT_ACCEPTANCE_POLICY) -> int:
    if value is None:
        return 0
    scale = policy.star_scale if policy.star_scale > 0 else DEFAULT_ACCEPTANCE_POLICY.star_scale
    return max(policy.min_rating, min(int(round(value / scale)), policy.max_rating))


def pick_status_from_score(value: float | None, policy: AcceptancePolicy = DEFAULT_ACCEPTANCE_POLICY) -> str:
    if value is None:
        return ""
    if value >= policy.pick_threshold:
        return "pick"
    if value < policy.reject_threshold:
        return "reject"
    return ""


def acceptance_score(row: pd.Series, basis: str) -> float | None:
    normalized_basis = normalize_acceptance_basis(basis)
    return numeric_column(row, ACCEPTANCE_SCORE_COLUMNS[normalized_basis])


def acceptance_source(basis: str, scope: str) -> str:
    normalized_basis = normalize_acceptance_basis(basis)
    if scope in {"filtered", "selected"}:
        return "llm_batch" if normalized_basis == "llm" else "model_batch"
    return "llm" if normalized_basis == "llm" else "model"


def acceptance_mark_plan(
    rows: pd.DataFrame,
    basis: str,
    scope: str,
    policy: AcceptancePolicy = DEFAULT_ACCEPTANCE_POLICY,
) -> AcceptancePlan:
    normalized_basis = normalize_acceptance_basis(basis)
    source = acceptance_source(normalized_basis, scope)
    marks: list[dict[str, object]] = []
    skipped = 0
    for _, row in rows.iterrows():
        score = acceptance_score(row, normalized_basis)
        if score is None:
            skipped += 1
            continue
        marks.append(
            {
                "file_id": str(row.get("file_id") or ""),
                "rating": manual_rating_from_score(score, policy),
                "status": pick_status_from_score(score, policy),
                "source": source,
                "accepted_score": score,
            }
        )
    return AcceptancePlan(marks=marks, skipped=skipped, source=source)

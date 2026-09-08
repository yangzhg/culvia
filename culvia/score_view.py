from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.cache_schema import SQLITE_CACHE_EXTENSIONS
from culvia.curation_targets import frame_file_ids
from culvia.insight_store import AnalysisInsightMatch
from culvia.llm_provenance import resolve_llm_score_dataframe
from culvia.local_score_provenance import resolve_local_score_dataframe
from culvia.schema import LLM_REVIEW_FIELDS, LLM_REVIEW_GENERATION_COLUMN, MODEL_LLM_REVIEW


@dataclass(frozen=True)
class CurrentScoreViewDependencies:
    normalize_dataframe: Callable[[Any], pd.DataFrame]
    load_matching_results: Callable[..., Mapping[str, AnalysisInsightMatch]]
    llm_review_provider: Callable[[], str]
    llm_review_model_name: Callable[[], str]
    llm_review_prompt_version: Callable[[], str]
    llm_review_result_prompt_version: Callable[..., str]
    llm_review_input_mode: Callable[[], str]


@dataclass(frozen=True)
class _CurrentLlmInsightContext:
    cache_path: str
    provider: str
    model: str
    prompt_version: str
    prompt_versions_by_file_id: Mapping[str, str] | None
    matching_results: Mapping[str, AnalysisInsightMatch]

    def expected_prompt_version(self, file_id: str) -> str:
        if self.prompt_versions_by_file_id is None:
            return self.prompt_version
        return self.prompt_versions_by_file_id.get(file_id, self.prompt_version)

    def matches(self, insight: Any) -> bool:
        file_id = str(insight.file_id)
        match = self.matching_results.get(file_id)
        return bool(
            insight.analyzer_key == MODEL_LLM_REVIEW
            and insight.provider == self.provider
            and insight.model == self.model
            and insight.model_version == self.model
            and insight.prompt_version == self.expected_prompt_version(file_id)
            and match is not None
            and float(insight.created_at) == match.generation
        )


@dataclass(frozen=True)
class CurrentScoreView:
    dataframe: pd.DataFrame
    local_summary: dict[str, dict[str, int]]
    current_llm_file_ids: frozenset[str]
    _insight_context: _CurrentLlmInsightContext | None = field(default=None, repr=False)

    def load_current_insights(
        self,
        file_ids: Iterable[str],
        loader: Callable[..., Iterable[Any]],
    ) -> dict[str, Any]:
        context = self._insight_context
        requested_ids = [
            file_id
            for file_id in dict.fromkeys(str(file_id) for file_id in file_ids if str(file_id))
            if file_id in self.current_llm_file_ids
        ]
        if context is None or not requested_ids:
            return {}

        current: dict[str, Any] = {}
        for insight in loader(context.cache_path, file_ids=requested_ids):
            if not context.matches(insight):
                continue
            previous = current.get(insight.file_id)
            if previous is None or insight.created_at >= previous.created_at:
                current[insight.file_id] = insight
        return current


def load_current_score_view(
    source_df: Any,
    cache_path: str | Path,
    dependencies: CurrentScoreViewDependencies,
    *,
    allow_persistent_cache: bool = True,
) -> CurrentScoreView:
    """Return the score rows that are valid for the current model and LLM identities."""
    normalized = dependencies.normalize_dataframe(source_df)
    local_resolution = resolve_local_score_dataframe(normalized)
    resolved_source = local_resolution.dataframe
    cache_text = str(cache_path)
    cache_is_sqlite = bool(
        allow_persistent_cache
        and cache_text
        and Path(cache_text).expanduser().suffix.lower() in SQLITE_CACHE_EXTENSIONS
    )

    matching_results: dict[str, AnalysisInsightMatch] = {}
    insight_context = None
    if cache_is_sqlite:
        candidate_df = _llm_candidate_dataframe(resolved_source)
        provider = dependencies.llm_review_provider()
        model = dependencies.llm_review_model_name()
        prompt_version = dependencies.llm_review_prompt_version()
        input_mode = dependencies.llm_review_input_mode()
        prompt_versions_by_file_id = _prompt_versions_by_file_id(
            candidate_df,
            input_mode=input_mode,
            prompt_version=prompt_version,
            build_prompt_version=dependencies.llm_review_result_prompt_version,
        )
        matching_results = dict(
            dependencies.load_matching_results(
                cache_text,
                file_ids=frame_file_ids(candidate_df),
                analyzer_key=MODEL_LLM_REVIEW,
                provider=provider,
                model=model,
                model_version=model,
                prompt_version=prompt_version,
                prompt_versions_by_file_id=prompt_versions_by_file_id,
            )
        )
        insight_context = _CurrentLlmInsightContext(
            cache_path=cache_text,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            prompt_versions_by_file_id=prompt_versions_by_file_id,
            matching_results=matching_results,
        )

    llm_resolution = resolve_llm_score_dataframe(
        resolved_source,
        matching_results,
        generation_column=LLM_REVIEW_GENERATION_COLUMN,
        score_columns=tuple(f"{field}_0_10" for field in LLM_REVIEW_FIELDS),
    )
    return CurrentScoreView(
        dataframe=llm_resolution.dataframe,
        local_summary=local_resolution.summary,
        current_llm_file_ids=llm_resolution.current_file_ids,
        _insight_context=insight_context,
    )


def _llm_candidate_dataframe(source_df: pd.DataFrame) -> pd.DataFrame:
    generation = source_df.get(
        LLM_REVIEW_GENERATION_COLUMN,
        pd.Series(pd.NA, index=source_df.index, dtype="object"),
    )
    return source_df[pd.to_numeric(generation, errors="coerce").notna()]


def _prompt_versions_by_file_id(
    candidate_df: pd.DataFrame,
    *,
    input_mode: str,
    prompt_version: str,
    build_prompt_version: Callable[..., str],
) -> dict[str, str] | None:
    if input_mode != "text":
        return None
    return {
        str(record.get("file_id") or ""): build_prompt_version(
            record,
            prompt_version=prompt_version,
            input_mode=input_mode,
        )
        for record in candidate_df.to_dict(orient="records")
        if str(record.get("file_id") or "")
    }

"""Prompt construction, repeated judging, and conservative consensus."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from statistics import median
from typing import Mapping, Sequence

from benchmarks.config import JudgeConfig
from benchmarks.evaluators.judge_client import LLMJudgeClient, is_valid_judge_result


_SCORES = ("category_score", "location_score", "evidence_score", "severity_score", "recommendation_score")


@dataclass(frozen=True, slots=True)
class JudgeConsensus:
    verdict: str | None
    matched_issue_id: str | None
    category_score: float | None
    location_score: float | None
    evidence_score: float | None
    severity_score: float | None
    recommendation_score: float | None
    confidence: float | None
    requires_human_review: bool


@dataclass(frozen=True, slots=True)
class FindingJudgement:
    envelopes: tuple[Mapping[str, object], ...]
    consensus: JudgeConsensus


async def evaluate_finding(
    *, finding_index: int, finding: Mapping[str, object], candidate_expected_cards: Sequence[Mapping[str, object]],
    relevant_evidence: Mapping[str, object], system_prompt: str, config: JudgeConfig, client: LLMJudgeClient,
) -> FindingJudgement:
    """Evaluate one finding sequentially, passing only explicitly relevant material."""
    user_payload = {
        "finding": dict(finding), "candidate_expected_cards": [dict(card) for card in candidate_expected_cards],
        "relevant_evidence": dict(relevant_evidence),
    }
    messages = (
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    )
    envelopes: list[Mapping[str, object]] = []
    for repeat in range(1, config.evaluations_per_finding + 1):
        result = await client.evaluate(messages)
        envelopes.append({"finding_index": finding_index, "evaluation_repeat": repeat, **result.as_dict()})
    return FindingJudgement(tuple(envelopes), consensus(envelopes, config.confidence_threshold, config.evaluations_per_finding))


def consensus(envelopes: Sequence[Mapping[str, object]], confidence_threshold: float, expected_count: int) -> JudgeConsensus:
    completed_candidates = [item.get("result") for item in envelopes if item.get("status") == "completed"]
    if any(
        not is_valid_judge_result(item)
        or not isinstance(item, Mapping)
        or not _has_finite_numbers(item)
        for item in completed_candidates
    ):
        return JudgeConsensus(None, None, None, None, None, None, None, None, True)
    completed = completed_candidates  # Every item is a schema-validated mapping at this point.
    counts: dict[str, int] = {}
    for item in completed:
        verdict = item["verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
    majority = expected_count // 2 + 1
    winners = [verdict for verdict, count in counts.items() if count >= majority]
    if len(winners) != 1:
        return JudgeConsensus(None, None, None, None, None, None, None, None, True)
    winner = winners[0]
    decisions = [item for item in completed if item["verdict"] == winner]
    ids = {item["matched_issue_id"] for item in decisions}
    matched_id = next(iter(ids)) if len(ids) == 1 else None
    values = {name: float(median(item[name] for item in completed)) for name in _SCORES}
    confidence = float(median(item["confidence"] for item in completed))
    review = (
        len(completed) != expected_count or len(envelopes) != expected_count or winner in ("novel", "abstain")
        or confidence < confidence_threshold or len(ids) != 1
    )
    return JudgeConsensus(winner, matched_id, *(values[name] for name in _SCORES), confidence, review)


def _has_finite_numbers(decision: Mapping[str, object]) -> bool:
    """Reject malformed direct inputs as conservatively as schema validation does."""
    return all(
        type(decision.get(name)) in (int, float) and math.isfinite(decision[name])  # type: ignore[arg-type]
        for name in (*_SCORES, "confidence")
    )

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import ceil
from typing import Iterable

from .models import (
    ContributionLevel,
    CredibilityBand,
    RepoContributionSummary,
    RepoStarSummary,
    Repository,
    RuleResult,
    StargazerRecord,
    SubjectContribution,
)


CONTRIBUTION_LEVEL_WEIGHTS: dict[str, int] = {
    ContributionLevel.TOP.value: 25,
    ContributionLevel.MAJOR.value: 18,
    ContributionLevel.MID.value: 10,
    ContributionLevel.MINOR.value: 3,
    ContributionLevel.UNCLEAR.value: 0,
}


def _days_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return max((end - start).days, 0)


def classify_contribution(rank: int | None, share: float | None, total_actions: int, active_days: int | None) -> ContributionLevel:
    if rank is None or share is None:
        return ContributionLevel.UNCLEAR
    if rank == 1 and share >= 0.35 and total_actions >= 5:
        return ContributionLevel.TOP
    if rank <= 3 and share >= 0.2 and total_actions >= 5:
        return ContributionLevel.MAJOR
    if rank <= 10 and share >= 0.05 and total_actions >= 2:
        return ContributionLevel.MID
    if total_actions >= 1:
        return ContributionLevel.MINOR
    return ContributionLevel.UNCLEAR


def build_repo_contribution_summary(
    repo: Repository,
    contribution: SubjectContribution,
    contributors: list[tuple[str, int]],
    subject_login: str | None = None,
    warnings: list[str] | None = None,
) -> RepoContributionSummary:
    sorted_contributors = sorted(contributors, key=lambda item: item[1], reverse=True)
    contributor_count = len(sorted_contributors)
    contributor_rank = None
    top_actions = sorted_contributors[0][1] if sorted_contributors else None
    contribution_share = None
    subject_marker = next((login for login, _ in sorted_contributors if login.startswith("__subject__:")), None)
    stripped = None
    if subject_marker:
        stripped = subject_marker.replace("__subject__:", "", 1)
        sorted_contributors = [(stripped if login == subject_marker else login, count) for login, count in sorted_contributors]
    target_login = stripped or subject_login
    for index, (login, count) in enumerate(sorted_contributors, start=1):
        if target_login and login.lower() == target_login.lower():
            contributor_rank = index
            contribution_share = count / top_actions if top_actions else None
            break
    active_days = _days_between(contribution.first_contribution_at, contribution.last_contribution_at)
    delay = _days_between(repo.created_at, contribution.first_contribution_at)
    classification = classify_contribution(contributor_rank, contribution_share, contribution.total_actions, active_days)
    return RepoContributionSummary(
        repository=repo,
        subject=contribution,
        contributor_rank=contributor_rank,
        contributor_count=contributor_count,
        top_contributor_actions=top_actions,
        contribution_share=contribution_share,
        active_days=active_days,
        days_from_repo_creation_to_first_contribution=delay,
        classification=classification,
        collection_warnings=warnings or [],
    )


def build_rank_input(subject_login: str, subject_actions: int, contributors: list[tuple[str, int]]) -> list[tuple[str, int]]:
    normalized = [(login, count) for login, count in contributors]
    matching = [count for login, count in normalized if login.lower() == subject_login.lower()]
    if matching:
        normalized = [(login, max(count, subject_actions) if login.lower() == subject_login.lower() else count) for login, count in normalized]
    else:
        normalized.append((f"__subject__:{subject_login}", subject_actions))
    return normalized


def bucket_stargazers(records: list[StargazerRecord]) -> tuple[dict[str, int], float | None, float | None, float | None]:
    if not records:
        return {}, None, None, None
    now = datetime.now(timezone.utc)
    buckets = Counter({"0_30_days": 0, "31_180_days": 0, "181_365_days": 0, "366_plus_days": 0, "unknown": 0})
    suspicious = 0
    young = 0
    recent = 0
    analyzed = 0
    for record in records:
        created = record.account_created_at
        starred_at = record.starred_at or now
        if not created:
            buckets["unknown"] += 1
            continue
        analyzed += 1
        age_days = max((starred_at - created).days, 0)
        if age_days <= 30:
            buckets["0_30_days"] += 1
            suspicious += 1
            recent += 1
            young += 1
        elif age_days <= 180:
            buckets["31_180_days"] += 1
            suspicious += 1
            young += 1
        elif age_days <= 365:
            buckets["181_365_days"] += 1
        else:
            buckets["366_plus_days"] += 1
    recent_ratio = (recent / analyzed) if analyzed else None
    young_ratio = (young / analyzed) if analyzed else None
    suspicious_ratio = (suspicious / analyzed) if analyzed else None
    return dict(buckets), recent_ratio, young_ratio, suspicious_ratio


def classify_star_credibility(recent_ratio: float | None, suspicious_ratio: float | None, total_stars: int, forks: int) -> CredibilityBand:
    if total_stars == 0:
        return CredibilityBand.INCONCLUSIVE
    if suspicious_ratio is not None and suspicious_ratio >= 0.45:
        return CredibilityBand.SUSPICIOUS
    if recent_ratio is not None and recent_ratio >= 0.35:
        return CredibilityBand.SUSPICIOUS
    if total_stars >= 30 and forks <= 2:
        return CredibilityBand.MIXED
    return CredibilityBand.ORGANIC


def build_star_summary(repo: Repository, records: list[StargazerRecord], warnings: list[str] | None = None) -> RepoStarSummary:
    buckets, recent_ratio, young_ratio, suspicious_ratio = bucket_stargazers(records)
    classification = classify_star_credibility(recent_ratio, suspicious_ratio, repo.stargazers_count, repo.forks_count)
    analyzed = sum(count for key, count in buckets.items() if key != "unknown")
    return RepoStarSummary(
        repository=repo,
        total_stars=repo.stargazers_count,
        analyzed_stargazers=analyzed,
        bucket_counts=buckets,
        recent_account_ratio=recent_ratio,
        young_account_ratio=young_ratio,
        suspicious_ratio=suspicious_ratio,
        classification=classification,
        collection_warnings=warnings or [],
    )


def summarize_profile(repo_contributions: list[RepoContributionSummary], repo_stars: list[RepoStarSummary]):
    top = sum(1 for item in repo_contributions if item.classification == ContributionLevel.TOP)
    major = sum(1 for item in repo_contributions if item.classification == ContributionLevel.MAJOR)
    minor = sum(1 for item in repo_contributions if item.classification == ContributionLevel.MINOR)
    suspicious_star = sum(1 for item in repo_stars if item.classification == CredibilityBand.SUSPICIOUS)
    pinned = sum(1 for item in repo_contributions if item.repository.is_pinned)
    owned = sum(1 for item in repo_contributions if item.repository.ownership.value in {"owned", "owned_and_contributed"})
    contributed = sum(1 for item in repo_contributions if item.repository.ownership.value in {"contributed", "owned_and_contributed"})
    if top >= 2 or (top >= 1 and major >= 2):
        contribution_band = CredibilityBand.STRONG
    elif top == 0 and minor >= max(3, ceil(len(repo_contributions) * 0.5)) and repo_contributions:
        contribution_band = CredibilityBand.WEAK
    else:
        contribution_band = CredibilityBand.MIXED
    if suspicious_star == 0:
        star_band = CredibilityBand.ORGANIC
    elif suspicious_star == len(repo_stars) and repo_stars:
        star_band = CredibilityBand.SUSPICIOUS
    else:
        star_band = CredibilityBand.INCONCLUSIVE
    from .models import AuditSummary

    return AuditSummary(
        contribution_credibility=contribution_band,
        star_credibility=star_band,
        pinned_repo_count=pinned,
        top_repo_count=top,
        major_repo_count=major,
        minor_repo_count=minor,
        suspicious_star_repo_count=suspicious_star,
        owned_repo_count=owned,
        contributed_repo_count=contributed,
    )


def per_repo_velocity(item: RepoContributionSummary) -> float | None:
    """Average measured actions per active day. None when active_days is unknown or zero."""
    if not item.active_days or item.active_days <= 0:
        return None
    return item.subject.total_actions / item.active_days


def days_since_last_contribution(
    item: RepoContributionSummary, now: datetime | None = None
) -> int | None:
    if not item.subject.last_contribution_at:
        return None
    reference = now or datetime.now(timezone.utc)
    return max((reference - item.subject.last_contribution_at).days, 0)


def severity_breakdown(rules: Iterable[RuleResult]) -> dict[str, int]:
    counts = Counter({"high": 0, "medium": 0, "low": 0})
    for rule in rules:
        if rule.triggered:
            counts[rule.severity] += 1
    return dict(counts)


def compute_trust_scores(
    repo_contributions: list[RepoContributionSummary],
    repo_stars: list[RepoStarSummary],
    rules: list[RuleResult],
) -> dict[str, int | float]:
    """Composite trust score (0–100) with contribution, authenticity and engagement subscores.

    The score is a weighted combination of three deterministic signals minus a
    risk penalty; every input is publicly observable so the score is reproducible
    from the persisted normalized data.
    """

    contribution_points = 0.0
    for item in repo_contributions:
        contribution_points += CONTRIBUTION_LEVEL_WEIGHTS.get(item.classification.value, 0)
    contribution_points = min(contribution_points, 80.0)
    deep_repos = [
        item
        for item in repo_contributions
        if item.classification.value
        in (ContributionLevel.TOP.value, ContributionLevel.MAJOR.value)
        and item.active_days is not None
        and item.active_days >= 30
    ]
    contribution_points += min(20.0, 10.0 * len(deep_repos))
    contribution_score = max(0.0, min(100.0, contribution_points))

    measurable_stars = [
        s for s in repo_stars if s.suspicious_ratio is not None and s.analyzed_stargazers > 0
    ]
    if not measurable_stars:
        star_score = 50.0
    else:
        weight_total = 0.0
        weighted_susp = 0.0
        for s in measurable_stars:
            weight = max(s.analyzed_stargazers, 1)
            weighted_susp += (s.suspicious_ratio or 0.0) * weight
            weight_total += weight
        avg_susp = weighted_susp / weight_total if weight_total else 0.0
        star_score = max(0.0, min(100.0, (1.0 - avg_susp) * 100.0))

    owned_repos = [
        item.repository
        for item in repo_contributions
        if item.repository.ownership.value in ("owned", "owned_and_contributed")
    ]
    if owned_repos:
        engagement_total = 0.0
        for repo in owned_repos:
            engagement_total += (
                min(20, repo.stargazers_count)
                + min(10, repo.forks_count)
                + min(5, repo.watchers_count)
            )
        engagement_score = min(100.0, engagement_total * (100.0 / (len(owned_repos) * 35.0)))
    else:
        engagement_score = 50.0

    triggered_high = sum(1 for r in rules if r.triggered and r.severity == "high")
    triggered_med = sum(1 for r in rules if r.triggered and r.severity == "medium")
    triggered_low = sum(1 for r in rules if r.triggered and r.severity == "low")
    risk_penalty = min(30.0, triggered_high * 6.0 + triggered_med * 3.0 + triggered_low * 1.0)

    composite = round(
        0.55 * contribution_score + 0.30 * star_score + 0.15 * engagement_score - risk_penalty
    )
    composite = max(0, min(100, int(composite)))

    return {
        "composite": composite,
        "contribution": int(round(contribution_score)),
        "stars": int(round(star_score)),
        "engagement": int(round(engagement_score)),
        "risk_penalty": int(round(risk_penalty)),
        "triggered_high": triggered_high,
        "triggered_medium": triggered_med,
        "triggered_low": triggered_low,
        "weights": {"contribution": 0.55, "stars": 0.30, "engagement": 0.15},
    }

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import ceil

from .models import (
    ContributionLevel,
    CredibilityBand,
    RepoContributionSummary,
    RepoStarSummary,
    Repository,
    StargazerRecord,
    SubjectContribution,
)


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
    warnings: list[str] | None = None,
) -> RepoContributionSummary:
    sorted_contributors = sorted(contributors, key=lambda item: item[1], reverse=True)
    contributor_count = len(sorted_contributors)
    contributor_rank = None
    top_actions = sorted_contributors[0][1] if sorted_contributors else None
    contribution_share = None
    subject_login = next((login for login, _ in sorted_contributors if login.startswith("__subject__:")), None)
    stripped = None
    if subject_login:
        stripped = subject_login.replace("__subject__:", "", 1)
        sorted_contributors = [(stripped if login == subject_login else login, count) for login, count in sorted_contributors]
    target_login = stripped if subject_login else None
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

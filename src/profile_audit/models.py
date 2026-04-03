from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RepoOwnership(str, Enum):
    OWNED = "owned"
    CONTRIBUTED = "contributed"
    BOTH = "owned_and_contributed"


class ContributionLevel(str, Enum):
    TOP = "top_contributor"
    MAJOR = "major_contributor"
    MID = "mid_contributor"
    MINOR = "minor_contributor"
    UNCLEAR = "unclear_due_to_data_limits"


class CredibilityBand(str, Enum):
    STRONG = "strong"
    MIXED = "mixed"
    WEAK = "weak"
    SUSPICIOUS = "suspicious_pattern_requiring_caution"
    ORGANIC = "organic-looking"
    INCONCLUSIVE = "mixed / inconclusive"


class SubjectProfile(BaseModel):
    login: str
    html_url: str
    created_at: datetime
    name: str | None = None
    bio: str | None = None
    public_repos: int = 0
    followers: int = 0
    following: int = 0


class Repository(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    owner_login: str
    created_at: datetime
    pushed_at: datetime | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    watchers_count: int = 0
    archived: bool = False
    fork: bool = False
    language: str | None = None
    default_branch: str = "main"
    ownership: RepoOwnership
    is_pinned: bool = False


class ContributorStat(BaseModel):
    login: str
    contributions: int


class SubjectContribution(BaseModel):
    commit_count: int = 0
    pr_opened_count: int = 0
    pr_merged_count: int = 0
    issue_opened_count: int = 0
    review_count: int = 0
    first_contribution_at: datetime | None = None
    last_contribution_at: datetime | None = None
    total_actions: int = 0
    contribution_types: dict[str, int] = Field(default_factory=dict)


class RepoContributionSummary(BaseModel):
    repository: Repository
    subject: SubjectContribution
    contributor_rank: int | None = None
    contributor_count: int = 0
    top_contributor_actions: int | None = None
    contribution_share: float | None = None
    active_days: int | None = None
    days_from_repo_creation_to_first_contribution: int | None = None
    classification: ContributionLevel = ContributionLevel.UNCLEAR
    collection_warnings: list[str] = Field(default_factory=list)


class StargazerRecord(BaseModel):
    login: str
    starred_at: datetime | None = None
    account_created_at: datetime | None = None


class RepoStarSummary(BaseModel):
    repository: Repository
    total_stars: int = 0
    analyzed_stargazers: int = 0
    bucket_counts: dict[str, int] = Field(default_factory=dict)
    recent_account_ratio: float | None = None
    young_account_ratio: float | None = None
    suspicious_ratio: float | None = None
    classification: CredibilityBand = CredibilityBand.INCONCLUSIVE
    collection_warnings: list[str] = Field(default_factory=list)


class RuleResult(BaseModel):
    rule_id: str
    category: str
    target: str
    triggered: bool
    severity: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class AuditSummary(BaseModel):
    contribution_credibility: CredibilityBand
    star_credibility: CredibilityBand
    pinned_repo_count: int
    top_repo_count: int
    major_repo_count: int
    minor_repo_count: int
    suspicious_star_repo_count: int
    owned_repo_count: int
    contributed_repo_count: int


class AuditArtifacts(BaseModel):
    subject: SubjectProfile
    repositories: list[Repository]
    repo_contributions: list[RepoContributionSummary]
    repo_stars: list[RepoStarSummary]
    rules: list[RuleResult]
    summary: AuditSummary
    collection_warnings: list[str] = Field(default_factory=list)


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Counter):
        return dict(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")

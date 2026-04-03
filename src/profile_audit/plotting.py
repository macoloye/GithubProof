from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    matplotlib = None
    plt = None

from .models import RepoContributionSummary, RepoStarSummary, RuleResult


def _save(fig, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def plot_contribution_rank(repo_contributions: list[RepoContributionSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    items = [item for item in repo_contributions if item.contributor_rank is not None]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [item.repository.full_name for item in items]
    values = [item.contributor_rank for item in items]
    ax.barh(labels, values, color="#205375")
    ax.invert_yaxis()
    ax.set_title("Contribution Rank Across Repositories")
    ax.set_xlabel("Rank (lower is better)")
    return _save(fig, output_dir / "contribution_rank.png")


def plot_first_contribution_delay(repo_contributions: list[RepoContributionSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    items = [item for item in repo_contributions if item.days_from_repo_creation_to_first_contribution is not None]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [item.repository.full_name for item in items]
    values = [item.days_from_repo_creation_to_first_contribution for item in items]
    ax.bar(range(len(labels)), values, color="#4f772d")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("Days From Repo Creation To First Contribution")
    ax.set_ylabel("Days")
    return _save(fig, output_dir / "first_contribution_delay.png")


def plot_active_duration(repo_contributions: list[RepoContributionSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    items = [item for item in repo_contributions if item.active_days is not None]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [item.repository.full_name for item in items]
    values = [item.active_days for item in items]
    ax.bar(range(len(labels)), values, color="#8a5a44")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("Active Duration By Repository")
    ax.set_ylabel("Days")
    return _save(fig, output_dir / "active_duration.png")


def plot_contribution_type_mix(repo_contributions: list[RepoContributionSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    if not repo_contributions:
        return None
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = [item.repository.full_name for item in repo_contributions]
    commit_values = [item.subject.commit_count for item in repo_contributions]
    pr_values = [item.subject.pr_opened_count for item in repo_contributions]
    issue_values = [item.subject.issue_opened_count for item in repo_contributions]
    review_values = [item.subject.review_count for item in repo_contributions]
    positions = range(len(labels))
    ax.bar(positions, commit_values, label="Commits", color="#205375")
    ax.bar(positions, pr_values, bottom=commit_values, label="PRs", color="#d97706")
    issue_bottom = [commits + prs for commits, prs in zip(commit_values, pr_values)]
    ax.bar(positions, issue_values, bottom=issue_bottom, label="Issues", color="#4f772d")
    review_bottom = [value + issue for value, issue in zip(issue_bottom, issue_values)]
    ax.bar(positions, review_values, bottom=review_bottom, label="Reviews", color="#9a031e")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("Contribution Type Mix By Repository")
    ax.legend()
    return _save(fig, output_dir / "contribution_type_mix.png")


def plot_stargazer_account_age(repo_stars: list[RepoStarSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    items = [item for item in repo_stars if item.bucket_counts]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = [item.repository.full_name for item in items]
    buckets = ["0_30_days", "31_180_days", "181_365_days", "366_plus_days"]
    bottoms = [0] * len(labels)
    colors = ["#9a031e", "#fb8b24", "#e9d8a6", "#0f4c5c"]
    positions = range(len(labels))
    for bucket, color in zip(buckets, colors):
        values = [item.bucket_counts.get(bucket, 0) for item in items]
        ax.bar(positions, values, bottom=bottoms, label=bucket, color=color)
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("Owned-Repo Stargazer Account Age Distribution")
    ax.legend()
    return _save(fig, output_dir / "stargazer_account_age.png")


def plot_suspicious_star_ratio(repo_stars: list[RepoStarSummary], output_dir: Path) -> str | None:
    if plt is None:
        return None
    items = [item for item in repo_stars if item.suspicious_ratio is not None]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [item.repository.full_name for item in items]
    values = [round((item.suspicious_ratio or 0.0) * 100, 1) for item in items]
    ax.bar(range(len(labels)), values, color="#9a031e")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("Suspicious Stargazer Ratio By Repository")
    ax.set_ylabel("Percent")
    return _save(fig, output_dir / "suspicious_star_ratio.png")


def plot_rule_summary(rules: list[RuleResult], output_dir: Path) -> str | None:
    if plt is None:
        return None
    triggered = [rule for rule in rules if rule.triggered]
    if not triggered:
        return None
    severities = {"low": 0, "medium": 0, "high": 0}
    for rule in triggered:
        severities[rule.severity] = severities.get(rule.severity, 0) + 1
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(severities.keys(), severities.values(), color=["#4f772d", "#fb8b24", "#9a031e"])
    ax.set_title("Triggered Risk Flags")
    ax.set_ylabel("Count")
    return _save(fig, output_dir / "risk_flags.png")

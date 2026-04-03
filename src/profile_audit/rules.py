from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from .models import RepoContributionSummary, RepoStarSummary, RuleResult


def _root() -> Path:
    return Path(__file__).resolve().parent


def load_rule_config(filename: str) -> list[dict[str, Any]]:
    path = _root() / "config" / filename
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(content) or []
    except Exception:
        return json.loads(content)


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}"


def _matches(summary_metrics: dict[str, Any], condition: dict[str, Any]) -> bool:
    for key, expected in condition.items():
        if key.endswith("_gte"):
            metric = summary_metrics.get(key[:-4])
            if metric is None or metric < expected:
                return False
        elif key.endswith("_gt"):
            metric = summary_metrics.get(key[:-3])
            if metric is None or metric <= expected:
                return False
        elif key.endswith("_lte"):
            metric = summary_metrics.get(key[:-4])
            if metric is None or metric > expected:
                return False
        elif key.endswith("_lt"):
            metric = summary_metrics.get(key[:-3])
            if metric is None or metric >= expected:
                return False
        elif key == "classification_in":
            if summary_metrics.get("classification") not in expected:
                return False
        else:
            if summary_metrics.get(key) != expected:
                return False
    return True


def evaluate_contribution_rules(
    repo_summaries: list[RepoContributionSummary],
    unattributed_contribution_repos: int = 0,
) -> list[RuleResult]:
    rules = load_rule_config("contribution_rules.yaml")
    results: list[RuleResult] = []
    repo_count = len(repo_summaries)
    minor_count = sum(1 for item in repo_summaries if item.classification.value == "minor_contributor")
    profile_metrics = {
        "repo_count": repo_count,
        "minor_ratio": (minor_count / repo_count) if repo_count else 0.0,
        "minor_ratio_pct": _pct((minor_count / repo_count) if repo_count else 0.0),
        "unattributed_contribution_repos": unattributed_contribution_repos,
    }
    for rule in rules:
        if rule.get("scope") == "profile":
            triggered = _matches(profile_metrics, rule["when"])
            results.append(
                RuleResult(
                    rule_id=rule["id"],
                    category="contribution",
                    target="profile",
                    triggered=triggered,
                    severity=rule["severity"],
                    metrics=profile_metrics,
                    explanation=rule["explanation"].format(**profile_metrics),
                )
            )
            continue
        for summary in repo_summaries:
            metrics = {
                "repo": summary.repository.full_name,
                "classification": summary.classification.value,
                "contributor_rank": summary.contributor_rank or 9999,
                "contribution_share": summary.contribution_share or 0.0,
                "contribution_share_pct": _pct(summary.contribution_share or 0.0),
                "active_days": summary.active_days or 0,
                "days_from_repo_creation_to_first_contribution": summary.days_from_repo_creation_to_first_contribution or 0,
                "total_actions": summary.subject.total_actions,
            }
            triggered = _matches(metrics, rule["when"])
            results.append(
                RuleResult(
                    rule_id=rule["id"],
                    category="contribution",
                    target=summary.repository.full_name,
                    triggered=triggered,
                    severity=rule["severity"],
                    metrics=metrics,
                    explanation=rule["explanation"].format(**metrics),
                )
            )
    return results


def evaluate_star_rules(repo_stars: list[RepoStarSummary], repo_contributions: list[RepoContributionSummary]) -> list[RuleResult]:
    rules = load_rule_config("star_rules.yaml")
    contribution_lookup = {item.repository.full_name: item for item in repo_contributions}
    results: list[RuleResult] = []
    for star_summary in repo_stars:
        contribution = contribution_lookup.get(star_summary.repository.full_name)
        for rule in rules:
            metrics = {
                "repo": star_summary.repository.full_name,
                "total_stars": star_summary.total_stars,
                "analyzed_stargazers": star_summary.analyzed_stargazers,
                "recent_account_ratio": star_summary.recent_account_ratio or 0.0,
                "recent_account_ratio_pct": _pct(star_summary.recent_account_ratio or 0.0),
                "young_account_ratio": star_summary.young_account_ratio or 0.0,
                "young_account_ratio_pct": _pct(star_summary.young_account_ratio or 0.0),
                "suspicious_ratio": star_summary.suspicious_ratio or 0.0,
                "suspicious_ratio_pct": _pct(star_summary.suspicious_ratio or 0.0),
                "forks": star_summary.repository.forks_count,
                "top_contributor_actions": contribution.top_contributor_actions if contribution and contribution.top_contributor_actions is not None else 0,
            }
            triggered = _matches(metrics, rule["when"])
            results.append(
                RuleResult(
                    rule_id=rule["id"],
                    category="star",
                    target=star_summary.repository.full_name,
                    triggered=triggered,
                    severity=rule["severity"],
                    metrics=metrics,
                    explanation=rule["explanation"].format(**metrics),
                )
            )
    return results

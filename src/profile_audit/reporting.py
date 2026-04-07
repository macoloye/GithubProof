from __future__ import annotations

from pathlib import Path
from statistics import median

from .models import AuditArtifacts, ContributionLevel, CredibilityBand


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_days(value: int | None) -> str:
    return "—" if value is None else str(value)


def _fmt_int(value: int | None) -> str:
    return "—" if value is None else str(value)


def _repo_scope_label(item) -> str:
    if item.repository.is_pinned:
        return "pinned"
    if item.repository.ownership in {item.repository.ownership.OWNED, item.repository.ownership.BOTH}:
        return "owned"
    return "contributed"


def render_report(artifacts: AuditArtifacts, figure_paths: dict[str, str]) -> str:
    summary = artifacts.summary
    top_repos = [item.repository.full_name for item in artifacts.repo_contributions if item.classification == ContributionLevel.TOP]
    suspicious_repos = [item.repository.full_name for item in artifacts.repo_stars if item.classification == CredibilityBand.SUSPICIOUS]
    measurable_repos = [item for item in artifacts.repo_contributions if item.subject.total_actions > 0]
    active_days = [item.active_days for item in measurable_repos if item.active_days is not None]
    first_delay_days = [item.days_from_repo_creation_to_first_contribution for item in measurable_repos if item.days_from_repo_creation_to_first_contribution is not None]
    total_actions = sum(item.subject.total_actions for item in measurable_repos)
    commit_share = (
        sum(item.subject.commit_count for item in measurable_repos) / total_actions if total_actions else None
    )
    unattributed_repos = [item for item in artifacts.repo_contributions if item.subject.total_actions > 0 and item.contributor_rank is None]

    lines: list[str] = []
    lines.extend(
        [
            f"# GitHubProof Audit: {artifacts.subject.login}",
            "",
            "## Executive Summary",
            f"- Contribution Credibility: `{summary.contribution_credibility.value}`",
            f"- Star Credibility: `{summary.star_credibility.value}`",
            f"- Pinned repos analyzed first: {summary.pinned_repo_count}",
            f"- Top-contributor repos: {summary.top_repo_count}",
            f"- Major-contributor repos: {summary.major_repo_count}",
            f"- Minor-contributor repos: {summary.minor_repo_count}",
            f"- Discovered repos with suspicious star patterns: {summary.suspicious_star_repo_count}",
            f"- Direct answer: top contributor anywhere? {'yes' if top_repos else 'no'}",
            f"- Direct answer: footprint deep or shallow? {'deep in select repos' if summary.top_repo_count or summary.major_repo_count else 'broad but shallow'}",
            f"- Direct answer: stars suspicious? {'yes, caution required' if suspicious_repos else 'no strong suspicious pattern detected'}",
            "",
            "## Key Insights",
            f"- Repositories with measurable activity: {len(measurable_repos)} of {len(artifacts.repo_contributions)}.",
            f"- Median first-contribution delay: {_fmt_days(int(median(first_delay_days))) if first_delay_days else '—'} days.",
            f"- Median active duration: {_fmt_days(int(median(active_days))) if active_days else '—'} days.",
            f"- Action mix: commits account for {_fmt_pct(commit_share)} of all measured actions.",
            f"- Attribution coverage gap: {len(unattributed_repos)} active repos still lack contributor-rank attribution.",
            "",
            "## Subject Summary",
            f"- Login: [{artifacts.subject.login}]({artifacts.subject.html_url})",
            f"- Name: {artifacts.subject.name or 'n/a'}",
            f"- GitHub account created: {artifacts.subject.created_at.date().isoformat()}",
            f"- Public repos: {artifacts.subject.public_repos}",
            f"- Followers: {artifacts.subject.followers}",
            f"- Bio: {artifacts.subject.bio or 'n/a'}",
            "",
            "## Discovered Repositories",
            "| Repository | Analysis Order | Ownership | Stars | Forks | Classification | Rank | Share | First Contribution Delay | Active Days |",
            "|---|---|---|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for item in artifacts.repo_contributions:
        lines.append(
            f"| [{item.repository.full_name}]({item.repository.html_url}) | {_repo_scope_label(item)} | {item.repository.ownership.value} | "
            f"{item.repository.stargazers_count} | {item.repository.forks_count} | {item.classification.value} | "
            f"{_fmt_int(item.contributor_rank)} | {_fmt_pct(item.contribution_share)} | "
            f"{_fmt_days(item.days_from_repo_creation_to_first_contribution)} | {_fmt_days(item.active_days)} |"
        )
    lines.extend(["", "## Contribution Leaderboard Summary"])
    if top_repos:
        lines.append(f"- Top-contributor repos: {', '.join(top_repos)}")
    else:
        lines.append("- No repository met the deterministic top-contributor threshold.")
    lines.extend(
        [
            f"- Pinned repos discovered: {summary.pinned_repo_count}",
            f"- Owned repos discovered: {summary.owned_repo_count}",
            f"- Contributed repos discovered: {summary.contributed_repo_count}",
            "",
            "## Repo-by-Repo Contribution Findings",
        ]
    )
    pinned_items = [item for item in artifacts.repo_contributions if item.repository.is_pinned]
    owned_items = [item for item in artifacts.repo_contributions if not item.repository.is_pinned and item.repository.ownership in {item.repository.ownership.OWNED, item.repository.ownership.BOTH}]
    contributed_items = [item for item in artifacts.repo_contributions if not item.repository.is_pinned and item.repository.ownership == item.repository.ownership.CONTRIBUTED]
    for heading, entries in [
        ("### Pinned Repositories", pinned_items),
        ("### Owned Repositories", owned_items),
        ("### Other Contributed Repositories", contributed_items),
    ]:
        if not entries:
            continue
        lines.extend([heading, ""])
        for item in entries:
            lines.extend(
                [
                    f"#### {item.repository.full_name}",
                    f"- Analysis order: `{_repo_scope_label(item)}`",
                    f"- Classification: `{item.classification.value}`",
                    f"- Contributor rank: {_fmt_int(item.contributor_rank)} of {item.contributor_count}",
                    f"- Contribution share vs top contributor: {_fmt_pct(item.contribution_share)}",
                    f"- Measured actions: {item.subject.total_actions} "
                    f"(commits {item.subject.commit_count}, PRs {item.subject.pr_opened_count}, issues {item.subject.issue_opened_count}, reviews {item.subject.review_count})",
                    f"- First contribution: {item.subject.first_contribution_at.isoformat() if item.subject.first_contribution_at else '—'}",
                    f"- Last contribution: {item.subject.last_contribution_at.isoformat() if item.subject.last_contribution_at else '—'}",
                    f"- Delay from repo creation to first contribution: {_fmt_days(item.days_from_repo_creation_to_first_contribution)} days",
                    f"- Active duration: {_fmt_days(item.active_days)} days",
                ]
            )
            if item.collection_warnings:
                lines.append(f"- Collection warnings: {'; '.join(item.collection_warnings)}")
            lines.append("")
    lines.extend(["## Star Analysis Across Discovered Repositories"])
    if artifacts.repo_stars:
        lines.append("| Repository | Scope | Stars | Analyzed Stargazers | Recent Account Ratio | Suspicious Ratio | Classification |")
        lines.append("|---|---|---:|---:|---:|---:|---|")
        for item in artifacts.repo_stars:
            lines.append(
                f"| [{item.repository.full_name}]({item.repository.html_url}) | "
                f"{'pinned' if item.repository.is_pinned else item.repository.ownership.value} | "
                f"{item.total_stars} | {item.analyzed_stargazers} | "
                f"{_fmt_pct(item.recent_account_ratio)} | {_fmt_pct(item.suspicious_ratio)} | {item.classification.value} |"
            )
        lines.append("")
    else:
        lines.append("- No discovered repositories were available for star analysis.")
        lines.append("")
    lines.extend(["## Triggered Risk Flags"])
    triggered = [rule for rule in artifacts.rules if rule.triggered]
    if not triggered:
        lines.append("- No risk flags triggered under the current deterministic thresholds.")
    else:
        for rule in triggered:
            lines.append(f"- `{rule.category}:{rule.rule_id}` on `{rule.target}` [{rule.severity}]: {rule.explanation}")
    lines.extend(
        [
            "",
            "## Final Contribution Conclusion",
            f"- Contribution credibility band: `{summary.contribution_credibility.value}`",
            f"- The account is a top contributor on {summary.top_repo_count} repos, a major contributor on {summary.major_repo_count} repos, and only a minor contributor on {summary.minor_repo_count} repos.",
            "",
            "## Final Star-Pattern Conclusion",
            f"- Star credibility band: `{summary.star_credibility.value}`",
            "- Suspicious star findings are evidence-based signals from stargazer account-age and engagement patterns across all discovered repos, not proof of bought stars.",
            "",
            "## Figures",
        ]
    )
    if figure_paths:
        for label, path in figure_paths.items():
            rel = Path(path).name
            lines.append(f"- {label}: ![{label}](figures/{rel})")
    else:
        lines.append("- No figures were generated.")
    lines.extend(["", "## Limitations"])
    if artifacts.collection_warnings:
        for warning in artifacts.collection_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- This audit uses public GitHub data only; some contribution attribution may be incomplete.")
    return "\n".join(lines) + "\n"

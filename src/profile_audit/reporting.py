from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from urllib.parse import quote

from .metrics import (
    compute_trust_scores,
    days_since_last_contribution,
    per_repo_velocity,
    severity_breakdown,
)
from .models import AuditArtifacts, ContributionLevel, CredibilityBand, RuleResult

REPORT_VERSION = "v2"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_days(value: int | None) -> str:
    return "—" if value is None else str(value)


def _fmt_int(value: int | None) -> str:
    return "—" if value is None else str(value)


def _fmt_float(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _repo_scope_label(item) -> str:
    if item.repository.is_pinned:
        return "pinned"
    if item.repository.ownership in {item.repository.ownership.OWNED, item.repository.ownership.BOTH}:
        return "owned"
    return "contributed"


def _band_color(band: CredibilityBand) -> str:
    return {
        CredibilityBand.STRONG: "brightgreen",
        CredibilityBand.ORGANIC: "brightgreen",
        CredibilityBand.MIXED: "yellow",
        CredibilityBand.INCONCLUSIVE: "lightgrey",
        CredibilityBand.WEAK: "orange",
        CredibilityBand.SUSPICIOUS: "red",
    }.get(band, "lightgrey")


def _trust_color(score: int) -> str:
    if score >= 80:
        return "brightgreen"
    if score >= 65:
        return "green"
    if score >= 50:
        return "yellow"
    if score >= 35:
        return "orange"
    return "red"


def _score_bar(score: int, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _shield(label: str, message: str, color: str) -> str:
    base = "https://img.shields.io/badge"
    return f"![{label}: {message}]({base}/{quote(label)}-{quote(message)}-{color})"


def _verdict_for_repo(item) -> str:
    cls = item.classification.value
    if cls == ContributionLevel.TOP.value:
        return f"Owns the workload (rank {item.contributor_rank}/{item.contributor_count}, {_fmt_pct(item.contribution_share)} of top contributor's actions)."
    if cls == ContributionLevel.MAJOR.value:
        return f"Substantial co-author (rank {item.contributor_rank}/{item.contributor_count})."
    if cls == ContributionLevel.MID.value:
        return f"Meaningful but not central (rank {item.contributor_rank}/{item.contributor_count})."
    if cls == ContributionLevel.MINOR.value:
        return f"Minor footprint only (rank {item.contributor_rank}/{item.contributor_count}, {_fmt_pct(item.contribution_share)})."
    return "Insufficient public data to attribute contribution."


def _build_recommendations(artifacts: AuditArtifacts, trust: dict, top_repos: list[str], suspicious_repos: list[str]) -> list[str]:
    recs: list[str] = []
    if not top_repos:
        recs.append(
            "No repository qualifies as a top-contributor footprint under the deterministic threshold "
            "(rank 1, ≥35% share, ≥5 actions). Treat claims of authorship cautiously and verify with commit history."
        )
    else:
        recs.append(
            f"Authorship claims are well-supported on: {', '.join(top_repos)}. These repos pass rank, share and action thresholds."
        )
    if suspicious_repos:
        recs.append(
            "Re-examine star credibility on: "
            + ", ".join(suspicious_repos)
            + ". A high share of stargazers signed up close to the star date is consistent with mutual promotion or paid stars; cross-check with fork/issue activity before concluding."
        )
    if trust["composite"] < 50:
        recs.append(
            "Composite trust score is below 50. Combine this audit with a manual code review of the top-contributor repos and a check of issue/PR review history before relying on the profile for hiring or grant decisions."
        )
    if trust["triggered_high"] >= 2:
        recs.append(
            f"{trust['triggered_high']} high-severity flags triggered. Treat the profile as 'mixed' and ask the candidate to walk through specific commits in the flagged repos."
        )
    if not recs:
        recs.append("No actionable concerns flagged; standard reference checks remain advisable.")
    return recs


def _key_observations(artifacts: AuditArtifacts, trust: dict) -> list[str]:
    summary = artifacts.summary
    repo_contributions = artifacts.repo_contributions
    measurable = [item for item in repo_contributions if item.subject.total_actions > 0]
    obs: list[str] = []
    obs.append(
        f"Composite Trust Score **{trust['composite']}/100** "
        f"(contribution {trust['contribution']}, authenticity {trust['stars']}, engagement {trust['engagement']}, risk penalty −{trust['risk_penalty']})."
    )
    obs.append(
        f"Discovered {len(repo_contributions)} repos: "
        f"{summary.top_repo_count} top-contributor, {summary.major_repo_count} major, "
        f"{summary.minor_repo_count} minor, {len(measurable)} with measurable activity."
    )
    if measurable:
        velocities = [v for v in (per_repo_velocity(item) for item in measurable) if v]
        if velocities:
            obs.append(
                f"Median action velocity: {_fmt_float(median(velocities), 2)} actions/active-day across measurable repos."
            )
    recencies = [
        days_since_last_contribution(item) for item in measurable
    ]
    recencies = [r for r in recencies if r is not None]
    if recencies:
        obs.append(
            f"Most recent measured contribution: {min(recencies)} days ago; oldest tracked tail: {max(recencies)} days ago."
        )
    if summary.suspicious_star_repo_count:
        obs.append(
            f"{summary.suspicious_star_repo_count} of {len(artifacts.repo_stars)} discovered repos show suspicious star concentration patterns."
        )
    return obs


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

    trust = compute_trust_scores(artifacts.repo_contributions, artifacts.repo_stars, artifacts.rules)
    severity = severity_breakdown(artifacts.rules)
    triggered_rules = [rule for rule in artifacts.rules if rule.triggered]

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    account_age_days = max((datetime.now(timezone.utc) - artifacts.subject.created_at).days, 0)

    lines: list[str] = []

    lines.extend([
        f"# GitHubProof Audit · `{artifacts.subject.login}`",
        "",
        f"_Generated {generated_at} · Engine {REPORT_VERSION} · Deterministic, reproducible from the persisted normalized data._",
        "",
        " ".join([
            _shield("trust", f"{trust['composite']}/100", _trust_color(trust["composite"])),
            _shield("contribution", summary.contribution_credibility.value, _band_color(summary.contribution_credibility)),
            _shield("stars", summary.star_credibility.value, _band_color(summary.star_credibility)),
            _shield("repos", str(len(artifacts.repo_contributions)), "blue"),
            _shield(
                "high-severity flags",
                str(severity.get("high", 0)),
                "red" if severity.get("high", 0) else "lightgrey",
            ),
        ]),
        "",
        "## Table of Contents",
        "",
        "1. [Trust Score](#1-trust-score)",
        "2. [Executive Summary](#2-executive-summary)",
        "3. [Subject Profile](#3-subject-profile)",
        "4. [Discovered Repositories](#4-discovered-repositories)",
        "5. [Contribution Analysis](#5-contribution-analysis)",
        "6. [Star-Pattern Analysis](#6-star-pattern-analysis)",
        "7. [Risk Flags & Severity](#7-risk-flags--severity)",
        "8. [Recommendations](#8-recommendations)",
        "9. [Figures](#9-figures)",
        "10. [Methodology & Scoring](#10-methodology--scoring)",
        "11. [Glossary](#11-glossary)",
        "12. [Limitations & Reproducibility](#12-limitations--reproducibility)",
        "",
        "---",
        "",
    ])

    # 1. Trust Score
    weights = trust["weights"]
    lines.extend([
        "## 1. Trust Score",
        "",
        f"**Composite Trust Score: `{trust['composite']} / 100`  `[{_score_bar(trust['composite'])}]`**",
        "",
        "| Component | Score (0–100) | Weight | Contribution to composite |",
        "|---|---:|---:|---:|",
        f"| Contribution credibility | {trust['contribution']} | {weights['contribution']:.0%} | {trust['contribution'] * weights['contribution']:.1f} |",
        f"| Star authenticity | {trust['stars']} | {weights['stars']:.0%} | {trust['stars'] * weights['stars']:.1f} |",
        f"| External engagement | {trust['engagement']} | {weights['engagement']:.0%} | {trust['engagement'] * weights['engagement']:.1f} |",
        f"| Risk penalty (high×6 + medium×3 + low×1, capped 30) | — | — | −{trust['risk_penalty']} |",
        "",
        "_The composite is a deterministic weighted sum minus a capped risk penalty. See [Methodology & Scoring](#10-methodology--scoring) for the formula._",
        "",
        "### Key Observations",
    ])
    for line in _key_observations(artifacts, trust):
        lines.append(f"- {line}")
    lines.extend(["", "---", ""])

    # 2. Executive Summary
    lines.extend([
        "## 2. Executive Summary",
        "",
        "| Question | Answer |",
        "|---|---|",
        f"| Top contributor on any discovered repo? | **{'Yes' if top_repos else 'No'}**{(' — ' + ', '.join(f'`{r}`' for r in top_repos)) if top_repos else ''} |",
        f"| Footprint shape | {'Deep in select repos' if summary.top_repo_count or summary.major_repo_count else 'Broad but shallow'} |",
        f"| Star pattern suspicious anywhere? | **{'Yes, caution required' if suspicious_repos else 'No strong suspicious pattern detected'}**{(' — ' + ', '.join(f'`{r}`' for r in suspicious_repos)) if suspicious_repos else ''} |",
        f"| Pinned repos analyzed first | {summary.pinned_repo_count} |",
        f"| Top / major / minor contributor repos | {summary.top_repo_count} / {summary.major_repo_count} / {summary.minor_repo_count} |",
        f"| Triggered risk flags (high / medium / low) | {severity.get('high', 0)} / {severity.get('medium', 0)} / {severity.get('low', 0)} |",
        "",
        "### Headline Insights",
        f"- Repositories with measurable activity: **{len(measurable_repos)} of {len(artifacts.repo_contributions)}**.",
        f"- Median first-contribution delay: **{_fmt_days(int(median(first_delay_days))) if first_delay_days else '—'} days** after repo creation.",
        f"- Median active duration on a repo: **{_fmt_days(int(median(active_days))) if active_days else '—'} days**.",
        f"- Action mix: commits account for **{_fmt_pct(commit_share)}** of all measured actions.",
        f"- Attribution coverage gap: **{len(unattributed_repos)}** active repo(s) still lack a contributor rank.",
        "",
        "---",
        "",
    ])

    # 3. Subject Profile
    follower_ratio = (
        artifacts.subject.followers / artifacts.subject.following
        if artifacts.subject.following
        else None
    )
    lines.extend([
        "## 3. Subject Profile",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Login | [`{artifacts.subject.login}`]({artifacts.subject.html_url}) |",
        f"| Name | {artifacts.subject.name or 'n/a'} |",
        f"| Bio | {artifacts.subject.bio or 'n/a'} |",
        f"| Account created | {artifacts.subject.created_at.date().isoformat()} ({account_age_days // 365}y {account_age_days % 365 // 30}m, {account_age_days} days) |",
        f"| Public repos | {artifacts.subject.public_repos} |",
        f"| Followers / Following | {artifacts.subject.followers} / {artifacts.subject.following} (ratio {_fmt_float(follower_ratio, 2)}) |",
        "",
        "---",
        "",
    ])

    # 4. Discovered Repositories
    lines.extend([
        "## 4. Discovered Repositories",
        "",
        "| Repository | Scope | Ownership | ★ | Forks | Classification | Rank | Share | First-contrib delay (d) | Active days | Verdict |",
        "|---|---|---|---:|---:|---|---:|---:|---:|---:|---|",
    ])
    for item in artifacts.repo_contributions:
        verdict = _verdict_for_repo(item)
        lines.append(
            f"| [{item.repository.full_name}]({item.repository.html_url}) | {_repo_scope_label(item)} | {item.repository.ownership.value} | "
            f"{item.repository.stargazers_count} | {item.repository.forks_count} | `{item.classification.value}` | "
            f"{_fmt_int(item.contributor_rank)} | {_fmt_pct(item.contribution_share)} | "
            f"{_fmt_days(item.days_from_repo_creation_to_first_contribution)} | {_fmt_days(item.active_days)} | {verdict} |"
        )

    lines.extend([
        "",
        "**Discovery summary**",
        f"- Pinned repos discovered: {summary.pinned_repo_count}",
        f"- Owned repos discovered: {summary.owned_repo_count}",
        f"- Contributed repos discovered: {summary.contributed_repo_count}",
        f"- Top-contributor repos: {', '.join(top_repos) if top_repos else 'none'}",
        "",
        "---",
        "",
    ])

    # 5. Contribution Analysis
    lines.extend([
        "## 5. Contribution Analysis",
        "",
        "### Velocity & Recency",
        "",
        "| Repository | Total actions | Active days | Velocity (actions/active-day) | Last contribution | Days since last |",
        "|---|---:|---:|---:|---|---:|",
    ])
    for item in measurable_repos:
        velocity = per_repo_velocity(item)
        recency = days_since_last_contribution(item)
        last_at = item.subject.last_contribution_at.date().isoformat() if item.subject.last_contribution_at else "—"
        lines.append(
            f"| [{item.repository.full_name}]({item.repository.html_url}) | "
            f"{item.subject.total_actions} | {_fmt_days(item.active_days)} | "
            f"{_fmt_float(velocity, 2)} | {last_at} | {_fmt_days(recency)} |"
        )
    if not measurable_repos:
        lines.append("| _No measurable activity across discovered repos._ |  |  |  |  |  |")

    lines.extend(["", "### Per-Repository Findings", ""])
    pinned_items = [item for item in artifacts.repo_contributions if item.repository.is_pinned]
    owned_items = [item for item in artifacts.repo_contributions if not item.repository.is_pinned and item.repository.ownership in {item.repository.ownership.OWNED, item.repository.ownership.BOTH}]
    contributed_items = [item for item in artifacts.repo_contributions if not item.repository.is_pinned and item.repository.ownership == item.repository.ownership.CONTRIBUTED]
    for heading, entries in [
        ("#### Pinned Repositories", pinned_items),
        ("#### Owned Repositories", owned_items),
        ("#### Other Contributed Repositories", contributed_items),
    ]:
        if not entries:
            continue
        lines.extend([heading, ""])
        for item in entries:
            velocity = per_repo_velocity(item)
            recency = days_since_last_contribution(item)
            lines.extend([
                f"##### {item.repository.full_name}",
                f"> _{_verdict_for_repo(item)}_",
                "",
                f"- Analysis order: `{_repo_scope_label(item)}` · Classification: `{item.classification.value}`",
                f"- Contributor rank: {_fmt_int(item.contributor_rank)} of {item.contributor_count} (share vs top contributor: {_fmt_pct(item.contribution_share)})",
                f"- Measured actions: {item.subject.total_actions} "
                f"(commits {item.subject.commit_count}, PRs {item.subject.pr_opened_count}, "
                f"issues {item.subject.issue_opened_count}, reviews {item.subject.review_count})",
                f"- First / last contribution: {item.subject.first_contribution_at.isoformat() if item.subject.first_contribution_at else '—'} → "
                f"{item.subject.last_contribution_at.isoformat() if item.subject.last_contribution_at else '—'}",
                f"- First-contribution delay: {_fmt_days(item.days_from_repo_creation_to_first_contribution)} days",
                f"- Active duration: {_fmt_days(item.active_days)} days · Velocity: {_fmt_float(velocity, 2)} actions/active-day · Last activity: {_fmt_days(recency)} days ago",
            ])
            if item.collection_warnings:
                lines.append(f"- Collection warnings: {'; '.join(item.collection_warnings)}")
            lines.append("")

    lines.extend(["---", ""])

    # 6. Star-Pattern Analysis
    lines.append("## 6. Star-Pattern Analysis")
    lines.append("")
    if artifacts.repo_stars:
        lines.append(
            "| Repository | Scope | Stars | Analyzed | 0–30d acct ratio | Susp. ratio | Stars/Top-contrib actions | Classification |"
        )
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")
        contribution_lookup = {item.repository.full_name: item for item in artifacts.repo_contributions}
        for star_item in artifacts.repo_stars:
            contrib = contribution_lookup.get(star_item.repository.full_name)
            top_actions = contrib.top_contributor_actions if contrib else None
            ratio = (
                f"{star_item.total_stars / top_actions:.2f}"
                if top_actions and top_actions > 0
                else "—"
            )
            lines.append(
                f"| [{star_item.repository.full_name}]({star_item.repository.html_url}) | "
                f"{'pinned' if star_item.repository.is_pinned else star_item.repository.ownership.value} | "
                f"{star_item.total_stars} | {star_item.analyzed_stargazers} | "
                f"{_fmt_pct(star_item.recent_account_ratio)} | {_fmt_pct(star_item.suspicious_ratio)} | "
                f"{ratio} | `{star_item.classification.value}` |"
            )
        lines.append("")
        lines.append(
            "_Stars/Top-contrib actions > 5 with low fork count and many young accounts is a typical promoted-repo signature; cross-check against repo content._"
        )
    else:
        lines.append("- No discovered repositories were available for star analysis.")
    lines.extend(["", "---", ""])

    # 7. Risk Flags
    lines.extend([
        "## 7. Risk Flags & Severity",
        "",
        f"Triggered: **{len(triggered_rules)}** of {len(artifacts.rules)} evaluated rules — "
        f"high {severity.get('high', 0)}, medium {severity.get('medium', 0)}, low {severity.get('low', 0)}.",
        "",
    ])
    if triggered_rules:
        order = {"high": 0, "medium": 1, "low": 2}
        for rule in sorted(triggered_rules, key=lambda r: (order.get(r.severity, 9), r.category, r.rule_id)):
            badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rule.severity, "•")
            lines.append(
                f"- {badge} **{rule.severity.upper()}** · `{rule.category}:{rule.rule_id}` on `{rule.target}` — {rule.explanation}"
            )
    else:
        lines.append("- No risk flags triggered under the current deterministic thresholds.")
    lines.extend(["", "---", ""])

    # 8. Recommendations
    lines.extend(["## 8. Recommendations", ""])
    for rec in _build_recommendations(artifacts, trust, top_repos, suspicious_repos):
        lines.append(f"- {rec}")
    lines.extend(["", "---", ""])

    # 9. Figures
    lines.extend(["## 9. Figures", ""])
    if figure_paths:
        for label, path in figure_paths.items():
            rel = Path(path).name
            lines.append(f"**{label}**")
            lines.append("")
            lines.append(f"![{label}](figures/{rel})")
            lines.append("")
    else:
        lines.append("- No figures were generated.")
    lines.extend(["---", ""])

    # 10. Methodology
    lines.extend([
        "## 10. Methodology & Scoring",
        "",
        "**Discovery.** The auditor inspects pinned repositories first, then ownership, then PushEvent and search results, capped at the configured limit.",
        "",
        "**Contribution classification thresholds (deterministic):**",
        "",
        "| Class | Rule |",
        "|---|---|",
        "| `top_contributor` | rank = 1 AND share ≥ 35% AND total_actions ≥ 5 |",
        "| `major_contributor` | rank ≤ 3 AND share ≥ 20% AND total_actions ≥ 5 |",
        "| `mid_contributor` | rank ≤ 10 AND share ≥ 5% AND total_actions ≥ 2 |",
        "| `minor_contributor` | total_actions ≥ 1 (and not above) |",
        "| `unclear_due_to_data_limits` | otherwise |",
        "",
        "**Star bucketing.** Stargazers are bucketed by account age at the time of starring: 0–30 days, 31–180 days, 181–365 days, 366+ days. The `suspicious_ratio` is the share whose accounts were ≤180 days old when starring; ≥45% suspicious or ≥35% in the 0–30 bucket flips a repo to `suspicious_pattern_requiring_caution`.",
        "",
        "**Trust score formula.**",
        "",
        "```text",
        "contribution = clamp(Σ class_weight + 10·deep_repos, 0, 100)",
        "  class_weights: top=25, major=18, mid=10, minor=3, unclear=0; capped at 80",
        "  deep_repos = top/major repos with active_days ≥ 30; bonus capped at 20",
        "stars        = clamp((1 − weighted_avg(suspicious_ratio)) · 100, 0, 100)",
        "engagement   = clamp(avg(min(★,20) + min(forks,10) + min(watchers,5)) · (100/35), 0, 100)",
        "risk_penalty = min(30, 6·high + 3·medium + 1·low)  # triggered rules",
        "composite    = clamp(0.55·contribution + 0.30·stars + 0.15·engagement − risk_penalty, 0, 100)",
        "```",
        "",
        "All inputs are persisted under `data/normalized/` so the score can be recomputed offline.",
        "",
        "---",
        "",
    ])

    # 11. Glossary
    lines.extend([
        "## 11. Glossary",
        "",
        "- **Contributor rank** — position in the repo's contributor list ordered by recorded contributions; 1 = top contributor.",
        "- **Contribution share** — measured actions for the subject divided by the top contributor's actions in the same repo.",
        "- **Active days** — calendar days between the subject's first and last measurable contribution to a repo.",
        "- **Velocity** — total measured actions divided by active days; intuitively, actions per active day.",
        "- **Recency** — days since the subject's most recent measurable action in a repo.",
        "- **Suspicious ratio (stars)** — share of analyzed stargazers whose GitHub account was ≤180 days old when they starred.",
        "- **Recent account ratio** — share whose account was ≤30 days old when starring; this is the strongest single signal of inorganic stars.",
        "- **Engagement score** — combines stars, forks and watchers across owned repos, capped per-repo to discourage single-repo distortion.",
        "",
        "---",
        "",
    ])

    # 12. Limitations & Reproducibility
    lines.extend([
        "## 12. Limitations & Reproducibility",
        "",
        f"- Audit run timestamp: **{generated_at}**",
        f"- Engine version: **{REPORT_VERSION}**",
        "- Data sources: GitHub REST + GraphQL public endpoints; rate-limited and capped per run.",
        "- Star buckets are computed against the star event timestamp when available; otherwise the audit run timestamp.",
        "- Contributor counts come from GitHub's contributor index, which can drop authors GitHub has not linked to a public account.",
        "- Suspicious-star findings are evidence-based signals, not proof of bought stars.",
    ])
    rolled_warnings = list(artifacts.collection_warnings)
    seen = set(rolled_warnings)
    for item in artifacts.repo_contributions:
        for warning in item.collection_warnings:
            if warning not in seen:
                rolled_warnings.append(warning)
                seen.add(warning)
    for star in artifacts.repo_stars:
        for warning in star.collection_warnings:
            if warning not in seen:
                rolled_warnings.append(warning)
                seen.add(warning)
    if rolled_warnings:
        lines.extend(["", "### Collection warnings"])
        for warning in rolled_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- No collection warnings recorded.")
    lines.append("")
    return "\n".join(lines) + "\n"

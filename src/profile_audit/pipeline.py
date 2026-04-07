from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .collectors import (
    collect_repo_contributors,
    collect_stargazer_records,
    collect_subject_contribution,
    collect_subject_profile,
    discover_repositories,
)
from .github_api import GitHubClient
from .metrics import build_rank_input, build_repo_contribution_summary, build_star_summary, summarize_profile
from .models import AuditArtifacts, json_default
from .plotting import (
    plot_active_duration,
    plot_contribution_rank,
    plot_contribution_type_mix,
    plot_first_contribution_delay,
    plot_rule_summary,
    plot_stargazer_account_age,
    plot_suspicious_star_ratio,
)
from .progress import ProgressTracker
from .reporting import render_report
from .rules import evaluate_contribution_rules, evaluate_star_rules


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=json_default), encoding="utf-8")


def run_audit(
    subject: str,
    output_dir: str = "reports",
    max_repos: int | None = None,
    repo_search_limit: int = 100,
    stargazer_limit: int = 200,
    token: str | None = None,
    progress: ProgressTracker | None = None,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_dir) / subject / timestamp
    raw_dir = run_dir / "data" / "raw"
    normalized_dir = run_dir / "data" / "normalized"
    figures_dir = run_dir / "figures"
    client = GitHubClient(token=token)
    collection_warnings: list[str] = []
    try:
        if progress:
            progress.update(f"Fetching profile for GitHub ID {subject}")
        subject_profile = collect_subject_profile(client, subject)
        if progress:
            progress.advance(f"Fetched profile for GitHub ID {subject}")

            progress.update(f"Discovering repositories for GitHub ID {subject}")
        repositories, discovery_warnings = discover_repositories(client, subject, max_repos=max_repos, repo_search_limit=repo_search_limit)
        if progress:
            progress.advance(f"Discovered {len(repositories)} repositories for GitHub ID {subject}")
            progress.add_total(len(repositories) * 2 + 2)
        collection_warnings.extend(discovery_warnings)
        repo_contributions = []
        repo_stars = []
        unattributed_repos = 0
        raw_payload = {"subject": subject_profile.model_dump(mode="json"), "repositories": [item.model_dump(mode="json") for item in repositories]}
        for repo in repositories:
            if progress:
                progress.update(f"Collecting contribution data for {repo.full_name}")
            contributors = collect_repo_contributors(client, repo)
            contribution, warnings, raw_contribution = collect_subject_contribution(client, repo, subject_profile.login)
            contribution_actions = max(contribution.total_actions, contribution.commit_count)
            contributor_pairs = [(item.login, item.contributions) for item in contributors]
            rank_input = build_rank_input(subject_profile.login, contribution_actions, contributor_pairs)
            summary = build_repo_contribution_summary(
                repo,
                contribution,
                rank_input,
                subject_login=subject_profile.login,
                warnings=warnings,
            )
            if summary.classification.value == "unclear_due_to_data_limits":
                unattributed_repos += 1
            repo_contributions.append(summary)
            raw_payload[repo.full_name] = raw_contribution
            collection_warnings.extend(warnings)
            if progress:
                progress.advance(f"Collected contribution data for {repo.full_name}")

        for repo in repositories:
            try:
                if progress:
                    progress.update(f"Collecting stargazer data for {repo.full_name}")
                records, star_warnings, raw_star_payload = collect_stargazer_records(client, repo, limit=stargazer_limit)
                star_summary = build_star_summary(repo, records, warnings=star_warnings)
                repo_stars.append(star_summary)
                raw_payload[f"{repo.full_name}:stars"] = raw_star_payload
                collection_warnings.extend(star_warnings)
                if progress:
                    progress.advance(f"Collected stargazer data for {repo.full_name}")
            except Exception as exc:
                warning = f"Star collection failed for {repo.full_name}: {exc}"
                collection_warnings.append(warning)
                if progress:
                    progress.advance(f"Stargazer data failed for {repo.full_name}")
        contribution_rules = evaluate_contribution_rules(repo_contributions, unattributed_contribution_repos=unattributed_repos)
        star_rules = evaluate_star_rules(repo_stars, repo_contributions)
        rules = contribution_rules + star_rules
        summary = summarize_profile(repo_contributions, repo_stars)
        artifacts = AuditArtifacts(
            subject=subject_profile,
            repositories=repositories,
            repo_contributions=repo_contributions,
            repo_stars=repo_stars,
            rules=rules,
            summary=summary,
            collection_warnings=collection_warnings,
        )
        _write_json(raw_dir / "raw_payload.json", raw_payload)
        _write_json(normalized_dir / "subject_summary.json", subject_profile)
        _write_json(normalized_dir / "repo_contribution_summary.json", repo_contributions)
        _write_json(normalized_dir / "repo_star_summary.json", repo_stars)
        _write_json(normalized_dir / "rule_triggers.json", rules)
        _write_json(normalized_dir / "audit_summary.json", summary)
        if progress:
            progress.advance("Wrote raw and normalized audit data")

        if progress:
            progress.update("Rendering figures and final report")
        figure_paths = {
            "Contribution rank across repos": plot_contribution_rank(repo_contributions, figures_dir),
            "First contribution delay": plot_first_contribution_delay(repo_contributions, figures_dir),
            "Active duration": plot_active_duration(repo_contributions, figures_dir),
            "Contribution type mix": plot_contribution_type_mix(repo_contributions, figures_dir),
            "Discovered-repo stargazer account age": plot_stargazer_account_age(repo_stars, figures_dir),
            "Suspicious star ratio": plot_suspicious_star_ratio(repo_stars, figures_dir),
            "Triggered risk flags": plot_rule_summary(rules, figures_dir),
        }
        figure_paths = {label: path for label, path in figure_paths.items() if path}
        report = render_report(artifacts, figure_paths)
        report_path = run_dir / "final_report.md"
        report_path.write_text(report, encoding="utf-8")
        manifest = {
            "subject": subject_profile.login,
            "run_dir": str(run_dir),
            "report_path": str(report_path),
            "figure_paths": figure_paths,
            "normalized_paths": {
                "subject_summary": str(normalized_dir / "subject_summary.json"),
                "repo_contribution_summary": str(normalized_dir / "repo_contribution_summary.json"),
                "repo_star_summary": str(normalized_dir / "repo_star_summary.json"),
                "rule_triggers": str(normalized_dir / "rule_triggers.json"),
                "audit_summary": str(normalized_dir / "audit_summary.json"),
            },
        }
        _write_json(run_dir / "manifest.json", manifest)
        if progress:
            progress.advance("Finished report and manifest")
            progress.finish(f"Audit complete for GitHub ID {subject}")
        return run_dir
    finally:
        client.close()

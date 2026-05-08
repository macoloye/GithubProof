from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .models import (
    AuditArtifacts,
    AuditSummary,
    RepoContributionSummary,
    RepoStarSummary,
    RuleResult,
    SubjectProfile,
)
from .pipeline import run_audit
from .progress import ProgressTracker
from .reporting import render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-proof",
        description="GitHubProof: audit a GitHub account's contribution reality and star patterns.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "run arguments:\n"
            "  --subject SUBJECT           GitHub ID to audit. Required.\n"
            "  --output-dir OUTPUT_DIR     Base output directory. Default: reports\n"
            "  --max-repos MAX_REPOS       Maximum number of repos to analyze.\n"
            "  --repo-search-limit LIMIT   Maximum event/search results used during repo discovery. Default: 100\n"
            "  --stargazer-limit LIMIT     Maximum stargazers to analyze per discovered repo. Default: 200\n"
            "  --token TOKEN               GitHub token. Defaults to GITHUB_TOKEN if unset.\n"
            "\n"
            "examples:\n"
            "  github-proof run --subject octocat\n"
            "  github-proof run --subject octocat --max-repos 20 --repo-search-limit 50\n"
            "  github-proof run --subject octocat --stargazer-limit 100 --output-dir reports"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True, title="commands")

    run_parser = subparsers.add_parser(
        "run",
        help="Run an audit for one GitHub username.",
        description="Run an audit for one GitHub ID and write the report artifacts to disk.",
    )
    run_parser.add_argument("--subject", required=True, help="GitHub ID to audit.")
    run_parser.add_argument("--output-dir", default="reports", help="Base output directory.")
    run_parser.add_argument("--max-repos", type=int, default=None, help="Maximum number of repos to analyze.")
    run_parser.add_argument("--repo-search-limit", type=int, default=100, help="Maximum number of event/search results to use during repo discovery.")
    run_parser.add_argument("--stargazer-limit", type=int, default=200, help="Maximum number of stargazers to analyze per discovered repo.")
    run_parser.add_argument("--token", default=None, help="GitHub token. Defaults to GITHUB_TOKEN if unset.")

    render_parser = subparsers.add_parser(
        "render",
        help="Re-render final_report.md from a previously persisted run directory.",
        description=(
            "Reload the normalized JSON in <run_dir>/data/normalized/ and re-render "
            "<run_dir>/final_report.md using the current reporting engine. No network calls."
        ),
    )
    render_parser.add_argument("--run-dir", required=True, help="Path to a run directory (e.g. reports/octocat/20260101T000000Z).")
    return parser


def _rerender_run_dir(run_dir: Path) -> Path:
    normalized = run_dir / "data" / "normalized"
    if not normalized.exists():
        raise FileNotFoundError(f"Normalized data not found at {normalized}")

    def _load(name: str):
        with (normalized / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    subject = SubjectProfile.model_validate(_load("subject_summary.json"))
    repo_contributions = [RepoContributionSummary.model_validate(item) for item in _load("repo_contribution_summary.json")]
    repo_stars = [RepoStarSummary.model_validate(item) for item in _load("repo_star_summary.json")]
    rules = [RuleResult.model_validate(item) for item in _load("rule_triggers.json")]
    summary = AuditSummary.model_validate(_load("audit_summary.json"))
    artifacts = AuditArtifacts(
        subject=subject,
        repositories=[item.repository for item in repo_contributions],
        repo_contributions=repo_contributions,
        repo_stars=repo_stars,
        rules=rules,
        summary=summary,
    )
    figure_paths: dict[str, str] = {}
    figures_dir = run_dir / "figures"
    if figures_dir.exists():
        label_for_stem = {
            "contribution_rank": "Contribution rank across repos",
            "first_contribution_delay": "First contribution delay",
            "active_duration": "Active duration",
            "contribution_type_mix": "Contribution type mix",
            "stargazer_account_age": "Discovered-repo stargazer account age",
            "suspicious_star_ratio": "Suspicious star ratio",
            "risk_flags": "Triggered risk flags",
        }
        for path in sorted(figures_dir.glob("*.png")):
            label = label_for_stem.get(path.stem, path.stem.replace("_", " ").title())
            figure_paths[label] = str(path)
    report = render_report(artifacts, figure_paths)
    report_path = run_dir / "final_report.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        token = args.token or os.getenv("GITHUB_TOKEN")
        progress = ProgressTracker(total=2)
        run_dir = run_audit(
            subject=args.subject,
            output_dir=args.output_dir,
            max_repos=args.max_repos,
            repo_search_limit=args.repo_search_limit,
            stargazer_limit=args.stargazer_limit,
            token=token,
            progress=progress,
        )
        print(f"Audit complete. Report written to {run_dir / 'final_report.md'}")
        return 0
    if args.command == "render":
        report_path = _rerender_run_dir(Path(args.run_dir))
        print(f"Report re-rendered: {report_path}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import os
import sys

from .pipeline import run_audit
from .progress import ProgressTracker


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
    return parser


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
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

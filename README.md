# GitHubProof

GitHubProof is a deterministic CLI for checking the real GitHub impact of one account.

It is built to answer, quickly and clearly:

1. Is this account actually a top contributor anywhere?
2. Is the account's visible footprint deep or shallow across repos?
3. Do the stars on the account's discovered repos look organic or suspicious?

## What It Checks

- Owned repos and contributed repos
- Contributor rank per repo
- Contribution depth by commits, PRs, issues, and reviews
- First contribution time and active duration
- Repo-level classification:
  `top_contributor`, `major_contributor`, `mid_contributor`, `minor_contributor`, `unclear_due_to_data_limits`
- Stargazer account-age patterns across discovered repos
- Rule-based caution flags such as late entry, thin contribution spread, and suspicious young-account star skew

## What It Produces

Each run writes:

```text
reports/<subject>/<timestamp>/
```

With:

- `final_report.md`
- `manifest.json`
- `data/raw/raw_payload.json`
- `data/normalized/subject_summary.json`
- `data/normalized/repo_contribution_summary.json`
- `data/normalized/repo_star_summary.json`
- `data/normalized/rule_triggers.json`
- `data/normalized/audit_summary.json`
- `figures/*.png` when plotting is enabled

## Quick Start

Set a GitHub token first and install editable package:

```bash
export GITHUB_TOKEN=your_token_here
pip install -e .
```

Run one audit for a GitHub ID. In the examples below, `octocat` is the GitHub ID to search:

```bash
github-proof run --subject octocat
```

## Common Commands

Basic run:

```bash
github-proof run --subject octocat
```

Search with limited repo discovery:

```bash
github-proof run --subject octocat --max-repos 20 --repo-search-limit 50
```

Search with capped stargazer analysis:

```bash
github-proof run --subject octocat --stargazer-limit 100
```

Search and write results to a custom output directory:

```bash
github-proof run --subject octocat --output-dir reports
```

## How To Read The Result

Start with `final_report.md`.

The report opens with three direct answers:

- whether the account is a top contributor anywhere
- whether the contribution footprint is deep or shallow
- whether owned-repo stars show suspicious patterns

Then read:

- `Discovered Repositories` for the full repo list
- `Contribution Leaderboard Summary` for the account's real standing
- `Repo-by-Repo Contribution Findings` for hard numbers
- `Star Analysis Across Discovered Repositories` for suspicious star signals
- `Triggered Risk Flags` for deterministic rule hits

## Important Limits

- GitHubProof uses public GitHub data only
- Some contribution attribution is approximate
- Suspicious star findings are signals, not proof of bought stars
- No LLM is used anywhere in collection, analysis, scoring, or reporting
- If `matplotlib` is not installed, the audit still runs but skips figure generation

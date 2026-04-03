from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from .github_api import GitHubClient, parse_github_datetime
from .models import (
    ContributorStat,
    RepoOwnership,
    Repository,
    StargazerRecord,
    SubjectContribution,
    SubjectProfile,
)


def _repo_from_payload(payload: dict[str, Any], ownership: RepoOwnership) -> Repository:
    return Repository(
        name=payload["name"],
        full_name=payload["full_name"],
        html_url=payload["html_url"],
        description=payload.get("description"),
        owner_login=payload["owner"]["login"],
        created_at=parse_github_datetime(payload["created_at"]),
        pushed_at=parse_github_datetime(payload.get("pushed_at")),
        stargazers_count=payload.get("stargazers_count", 0),
        forks_count=payload.get("forks_count", 0),
        open_issues_count=payload.get("open_issues_count", 0),
        watchers_count=payload.get("watchers_count", 0),
        archived=payload.get("archived", False),
        fork=payload.get("fork", False),
        language=payload.get("language"),
        default_branch=payload.get("default_branch") or "main",
        ownership=ownership,
        is_pinned=payload.get("is_pinned", False),
    )


def _repo_from_graphql(payload: dict[str, Any], username: str) -> Repository:
    owner_login = payload["owner"]["login"]
    ownership = RepoOwnership.OWNED if owner_login.lower() == username.lower() else RepoOwnership.CONTRIBUTED
    return Repository(
        name=payload["name"],
        full_name=payload["nameWithOwner"],
        html_url=payload["url"],
        description=payload.get("description"),
        owner_login=owner_login,
        created_at=parse_github_datetime(payload["createdAt"]),
        pushed_at=parse_github_datetime(payload.get("pushedAt")),
        stargazers_count=payload.get("stargazerCount", 0),
        forks_count=payload.get("forkCount", 0),
        open_issues_count=(payload.get("issues") or {}).get("totalCount", 0),
        watchers_count=(payload.get("watchers") or {}).get("totalCount", 0),
        archived=payload.get("isArchived", False),
        fork=payload.get("isFork", False),
        language=(payload.get("primaryLanguage") or {}).get("name"),
        default_branch=((payload.get("defaultBranchRef") or {}).get("name") or "main"),
        ownership=ownership,
        is_pinned=True,
    )


def _merge_repository(existing: Repository | None, incoming: Repository) -> Repository:
    if existing is None:
        return incoming
    ownership = existing.ownership
    if existing.ownership != incoming.ownership:
        if RepoOwnership.OWNED in {existing.ownership, incoming.ownership}:
            ownership = RepoOwnership.BOTH if RepoOwnership.CONTRIBUTED in {existing.ownership, incoming.ownership} else RepoOwnership.OWNED
        elif RepoOwnership.BOTH in {existing.ownership, incoming.ownership}:
            ownership = RepoOwnership.BOTH
        else:
            ownership = incoming.ownership
    return existing.model_copy(
        update={
            "ownership": ownership,
            "is_pinned": existing.is_pinned or incoming.is_pinned,
            "pushed_at": incoming.pushed_at or existing.pushed_at,
            "stargazers_count": max(existing.stargazers_count, incoming.stargazers_count),
            "forks_count": max(existing.forks_count, incoming.forks_count),
            "watchers_count": max(existing.watchers_count, incoming.watchers_count),
            "open_issues_count": max(existing.open_issues_count, incoming.open_issues_count),
            "description": existing.description or incoming.description,
            "language": existing.language or incoming.language,
            "default_branch": incoming.default_branch or existing.default_branch,
        }
    )


def sort_repositories(repositories: list[Repository]) -> list[Repository]:
    ownership_rank = {
        RepoOwnership.BOTH: 0,
        RepoOwnership.OWNED: 1,
        RepoOwnership.CONTRIBUTED: 2,
    }
    return sorted(
        repositories,
        key=lambda item: (
            0 if item.is_pinned else 1,
            ownership_rank.get(item.ownership, 3),
            -(item.stargazers_count or 0),
            -(item.pushed_at.timestamp() if item.pushed_at else item.created_at.timestamp()),
        ),
    )


def collect_subject_profile(client: GitHubClient, username: str) -> SubjectProfile:
    payload = client.get_user(username)
    return SubjectProfile(
        login=payload["login"],
        html_url=payload["html_url"],
        created_at=parse_github_datetime(payload["created_at"]),
        name=payload.get("name"),
        bio=payload.get("bio"),
        public_repos=payload.get("public_repos", 0),
        followers=payload.get("followers", 0),
        following=payload.get("following", 0),
    )


def discover_repositories(client: GitHubClient, username: str, max_repos: int | None = None, repo_search_limit: int = 100) -> tuple[list[Repository], list[str]]:
    repo_map: dict[str, Repository] = {}
    warnings: list[str] = []
    for repo in client.get_user_repos(username, limit=max_repos):
        item = _repo_from_payload(repo, RepoOwnership.OWNED)
        repo_map[item.full_name] = _merge_repository(repo_map.get(item.full_name), item)

    try:
        for repo in client.get_pinned_repositories(username):
            item = _repo_from_graphql(repo, username)
            repo_map[item.full_name] = _merge_repository(repo_map.get(item.full_name), item)
    except Exception as exc:
        warnings.append(f"Pinned repository discovery failed: {exc}")

    for event in client.get_user_events(username, limit=repo_search_limit):
        repo_name = event.get("repo", {}).get("name")
        if not repo_name or repo_name in repo_map:
            continue
        owner, _, repo = repo_name.partition("/")
        if not owner or not repo:
            continue
        try:
            payload = client._request("GET", f"/repos/{owner}/{repo}")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        ownership = RepoOwnership.BOTH if payload.get("owner", {}).get("login", "").lower() == username.lower() else RepoOwnership.CONTRIBUTED
        repo_map[repo_name] = _merge_repository(repo_map.get(repo_name), _repo_from_payload(payload, ownership))
        if max_repos and len(repo_map) >= max_repos:
            break

    search_results = client.search_issues_and_prs(username, limit=repo_search_limit)
    for item in search_results:
        repo_url = item.get("repository_url")
        if not repo_url:
            continue
        parts = repo_url.rstrip("/").split("/")
        owner = parts[-2]
        repo = parts[-1]
        full_name = f"{owner}/{repo}"
        if full_name in repo_map:
            continue
        try:
            payload = client._request("GET", f"/repos/{owner}/{repo}")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        ownership = RepoOwnership.BOTH if payload.get("owner", {}).get("login", "").lower() == username.lower() else RepoOwnership.CONTRIBUTED
        repo_map[full_name] = _merge_repository(repo_map.get(full_name), _repo_from_payload(payload, ownership))
        if max_repos and len(repo_map) >= max_repos:
            break

    repos = sort_repositories(list(repo_map.values()))
    return (repos[:max_repos] if max_repos else repos), warnings


def collect_repo_contributors(client: GitHubClient, repo: Repository) -> list[ContributorStat]:
    payload = client.get_repo_contributors(repo.owner_login, repo.name, limit=100)
    return [
        ContributorStat(login=item["login"], contributions=item.get("contributions", 0))
        for item in payload
        if item.get("login")
    ]


def collect_subject_contribution(client: GitHubClient, repo: Repository, username: str) -> tuple[SubjectContribution, list[str], dict[str, Any]]:
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    commits = client.get_repo_commits_for_author(repo.owner_login, repo.name, username, limit=100)
    raw["commits"] = commits

    pulls = client.get_repo_pulls_for_creator(repo.owner_login, repo.name, username, limit=100)
    raw["pulls"] = pulls

    issues = client.get_repo_issues_for_creator(repo.owner_login, repo.name, username, limit=100)
    issues = [issue for issue in issues if "pull_request" not in issue]
    raw["issues"] = issues

    try:
        reviews = client.get_repo_reviews_by_user(repo.owner_login, repo.name, username, limit_prs=30)
    except Exception as exc:
        reviews = []
        warnings.append(f"Review collection failed for {repo.full_name}: {exc}")
    raw["reviews"] = reviews

    timestamps: list[datetime] = []
    for commit in commits:
        stamp = parse_github_datetime(commit.get("commit", {}).get("author", {}).get("date"))
        if stamp:
            timestamps.append(stamp)
    for pull in pulls:
        stamp = parse_github_datetime(pull.get("created_at"))
        if stamp:
            timestamps.append(stamp)
    for issue in issues:
        stamp = parse_github_datetime(issue.get("created_at"))
        if stamp:
            timestamps.append(stamp)
    for review in reviews:
        stamp = parse_github_datetime(review.get("submitted_at"))
        if stamp:
            timestamps.append(stamp)

    timestamps = sorted(timestamps)
    contribution = SubjectContribution(
        commit_count=len(commits),
        pr_opened_count=len(pulls),
        pr_merged_count=sum(1 for pull in pulls if pull.get("merged_at")),
        issue_opened_count=len(issues),
        review_count=len(reviews),
        first_contribution_at=timestamps[0] if timestamps else None,
        last_contribution_at=timestamps[-1] if timestamps else None,
        total_actions=len(commits) + len(pulls) + len(issues) + len(reviews),
        contribution_types={
            "commits": len(commits),
            "pull_requests": len(pulls),
            "issues": len(issues),
            "reviews": len(reviews),
        },
    )
    if contribution.total_actions == 0:
        warnings.append(f"No measurable activity found for {username} in {repo.full_name}.")
    return contribution, warnings, raw


def collect_stargazer_records(client: GitHubClient, repo: Repository, limit: int = 200) -> tuple[list[StargazerRecord], list[str], dict[str, Any]]:
    warnings: list[str] = []
    raw_records = client.get_stargazers(repo.owner_login, repo.name, limit=limit)
    records: list[StargazerRecord] = []
    user_cache: dict[str, datetime | None] = {}
    for item in raw_records:
        login = item.get("user", {}).get("login") or item.get("login")
        if not login:
            continue
        if login not in user_cache:
            try:
                user_payload = client.get_user_brief(login)
                user_cache[login] = parse_github_datetime(user_payload.get("created_at"))
            except Exception as exc:
                user_cache[login] = None
                warnings.append(f"Failed to collect account creation for stargazer {login}: {exc}")
        records.append(
            StargazerRecord(
                login=login,
                starred_at=parse_github_datetime(item.get("starred_at")),
                account_created_at=user_cache[login],
            )
        )
    return records, warnings, {"stargazers": raw_records}


def summarize_discovery(repositories: list[Repository]) -> dict[str, int]:
    counts = defaultdict(int)
    for repo in repositories:
        counts[repo.ownership.value] += 1
    return dict(counts)

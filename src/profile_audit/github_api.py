from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any
from json import JSONDecodeError
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GITHUB_API_URL = "https://api.github.com"
ACCEPT_JSON = "application/vnd.github+json"
ACCEPT_STAR = "application/vnd.github.star+json"


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": ACCEPT_JSON,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GitHubProof/0.1.0",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        self.timeout = timeout

    def close(self) -> None:
        return None

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        if method != "GET":
            raise ValueError("Only GET requests are supported.")
        url = f"{GITHUB_API_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        merged_headers = dict(self.headers)
        if headers:
            merged_headers.update(headers)
        request = Request(url, headers=merged_headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8", errors="replace").strip()
                if not raw_body:
                    return []
                try:
                    return json.loads(raw_body)
                except JSONDecodeError as exc:
                    content_type = response.headers.get("Content-Type", "unknown")
                    snippet = raw_body[:200].replace("\n", " ")
                    raise RuntimeError(
                        f"GitHub API returned non-JSON content for {url} "
                        f"(content-type: {content_type}, body starts with: {snippet!r})"
                    ) from exc
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed for {url}: {exc.code} {body}") from exc

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"
        request = Request(f"{GITHUB_API_URL}/graphql", data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8", errors="replace").strip()
                payload = json.loads(raw_body)
                if payload.get("errors"):
                    raise RuntimeError(f"GitHub GraphQL request failed: {payload['errors']}")
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise RuntimeError("GitHub GraphQL response missing data.")
                return data
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub GraphQL request failed: {exc.code} {body}") from exc

    def _paginate(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        while True:
            page_params = dict(params or {})
            page_params["per_page"] = min(per_page, limit - len(collected)) if limit else per_page
            page_params["page"] = page
            items = self._request("GET", path, params=page_params, headers=headers)
            if not isinstance(items, list):
                break
            collected.extend(items)
            if len(items) < page_params["per_page"]:
                break
            if limit and len(collected) >= limit:
                return collected[:limit]
            page += 1
        return collected

    def get_user(self, username: str) -> dict[str, Any]:
        payload = self._request("GET", f"/users/{username}")
        assert isinstance(payload, dict)
        return payload

    def get_user_repos(self, username: str, limit: int | None = None) -> list[dict[str, Any]]:
        return self._paginate(f"/users/{username}/repos", params={"type": "owner", "sort": "updated"}, limit=limit)

    def get_received_events(self, username: str, limit: int | None = 100) -> list[dict[str, Any]]:
        return self._paginate(f"/users/{username}/received_events/public", limit=limit)

    def get_user_events(self, username: str, limit: int | None = 100) -> list[dict[str, Any]]:
        return self._paginate(f"/users/{username}/events/public", limit=limit)

    def get_pinned_repositories(self, username: str, limit: int = 6) -> list[dict[str, Any]]:
        query = """
        query($login: String!, $limit: Int!) {
          user(login: $login) {
            pinnedItems(first: $limit, types: REPOSITORY) {
              nodes {
                ... on Repository {
                  name
                  nameWithOwner
                  description
                  url
                  createdAt
                  pushedAt
                  stargazerCount
                  forkCount
                  isArchived
                  isFork
                  watchers {
                    totalCount
                  }
                  issues(states: OPEN) {
                    totalCount
                  }
                  primaryLanguage {
                    name
                  }
                  defaultBranchRef {
                    name
                  }
                  owner {
                    login
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(query, {"login": username, "limit": limit})
        user = data.get("user") or {}
        pinned = user.get("pinnedItems", {}).get("nodes", [])
        return [item for item in pinned if isinstance(item, dict)]

    def search_issues_and_prs(self, username: str, limit: int | None = 100) -> list[dict[str, Any]]:
        per_page = 100
        page = 1
        collected: list[dict[str, Any]] = []
        while True:
            params = {
                "q": f"author:{username} type:pr archived:false",
                "sort": "updated",
                "order": "desc",
                "per_page": min(per_page, limit - len(collected)) if limit else per_page,
                "page": page,
            }
            payload = self._request("GET", "/search/issues", params=params)
            assert isinstance(payload, dict)
            items = payload.get("items", [])
            collected.extend(items)
            if len(items) < params["per_page"]:
                break
            if limit and len(collected) >= limit:
                return collected[:limit]
            page += 1
        return collected

    def get_repo_contributors(self, owner: str, repo: str, limit: int | None = None) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{owner}/{repo}/contributors", limit=limit)

    def get_repo_commits_for_author(self, owner: str, repo: str, author: str, limit: int | None = 100) -> list[dict[str, Any]]:
        try:
            return self._paginate(f"/repos/{owner}/{repo}/commits", params={"author": author}, limit=limit)
        except RuntimeError as exc:
            if "409" in str(exc) and "Git Repository is empty" in str(exc):
                return []
            raise

    def get_repo_issues_for_creator(self, owner: str, repo: str, creator: str, limit: int | None = 100) -> list[dict[str, Any]]:
        return self._paginate(
            f"/repos/{owner}/{repo}/issues",
            params={"creator": creator, "state": "all"},
            limit=limit,
        )

    def get_repo_pulls_for_creator(self, owner: str, repo: str, creator: str, limit: int | None = 100) -> list[dict[str, Any]]:
        pulls = self._paginate(f"/repos/{owner}/{repo}/pulls", params={"state": "all", "sort": "updated", "direction": "desc"}, limit=limit)
        return [pull for pull in pulls if pull.get("user", {}).get("login") == creator]

    def get_repo_reviews_by_user(self, owner: str, repo: str, username: str, limit_prs: int = 30) -> list[dict[str, Any]]:
        pulls = self._paginate(f"/repos/{owner}/{repo}/pulls", params={"state": "all"}, limit=limit_prs)
        reviews: list[dict[str, Any]] = []
        for pull in pulls:
            number = pull.get("number")
            if not number:
                continue
            for review in self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/reviews"):
                if review.get("user", {}).get("login") == username:
                    reviews.append(review)
        return reviews

    def get_stargazers(self, owner: str, repo: str, limit: int | None = 200) -> list[dict[str, Any]]:
        return self._paginate(
            f"/repos/{owner}/{repo}/stargazers",
            headers={"Accept": ACCEPT_STAR, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "GitHubProof/0.1.0", **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
            limit=limit,
        )

    def get_user_brief(self, username: str) -> dict[str, Any]:
        payload = self._request("GET", f"/users/{username}")
        assert isinstance(payload, dict)
        return payload

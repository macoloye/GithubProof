from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from profile_audit.collectors import sort_repositories
from profile_audit.models import RepoOwnership, Repository


def _repo(full_name: str, ownership: RepoOwnership, is_pinned: bool) -> Repository:
    now = datetime.now(timezone.utc)
    owner, name = full_name.split("/", 1)
    return Repository(
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        owner_login=owner,
        created_at=now - timedelta(days=100),
        pushed_at=now - timedelta(days=1),
        stargazers_count=10,
        forks_count=1,
        open_issues_count=0,
        watchers_count=10,
        archived=False,
        fork=False,
        language="Python",
        default_branch="main",
        ownership=ownership,
        is_pinned=is_pinned,
    )


class RepositoryOrderingTests(unittest.TestCase):
    def test_pinned_then_owned_then_contributed(self):
        repos = [
            _repo("alice/contrib", RepoOwnership.CONTRIBUTED, False),
            _repo("alice/owned", RepoOwnership.OWNED, False),
            _repo("bob/pinned-contrib", RepoOwnership.CONTRIBUTED, True),
            _repo("alice/pinned-owned", RepoOwnership.OWNED, True),
        ]
        ordered = sort_repositories(repos)
        self.assertEqual(
            [repo.full_name for repo in ordered],
            ["alice/pinned-owned", "bob/pinned-contrib", "alice/owned", "alice/contrib"],
        )


if __name__ == "__main__":
    unittest.main()

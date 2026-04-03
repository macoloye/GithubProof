from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from profile_audit.collectors import collect_subject_contribution
from profile_audit.models import RepoOwnership, Repository
from datetime import datetime, timezone


class CollectorEdgeCaseTests(unittest.TestCase):
    def test_empty_repo_409_returns_zero_commit_contribution(self):
        repo = Repository(
            name="empty-repo",
            full_name="alice/empty-repo",
            html_url="https://github.com/alice/empty-repo",
            owner_login="alice",
            created_at=datetime.now(timezone.utc),
            pushed_at=None,
            stargazers_count=0,
            forks_count=0,
            open_issues_count=0,
            watchers_count=0,
            archived=False,
            fork=False,
            language=None,
            default_branch="main",
            ownership=RepoOwnership.OWNED,
        )
        client = MagicMock()
        client.get_repo_commits_for_author.return_value = []
        client.get_repo_pulls_for_creator.return_value = []
        client.get_repo_issues_for_creator.return_value = []
        client.get_repo_reviews_by_user.return_value = []

        contribution, warnings, raw = collect_subject_contribution(client, repo, "alice")

        self.assertEqual(contribution.commit_count, 0)
        self.assertEqual(contribution.total_actions, 0)
        self.assertTrue(any("No measurable activity found" in warning for warning in warnings))
        self.assertIn("commits", raw)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from profile_audit.metrics import bucket_stargazers, build_rank_input, build_repo_contribution_summary, build_star_summary, classify_contribution
from profile_audit.models import RepoOwnership, Repository, StargazerRecord, SubjectContribution


def make_repo() -> Repository:
    now = datetime.now(timezone.utc)
    return Repository(
        name="demo",
        full_name="alice/demo",
        html_url="https://github.com/alice/demo",
        owner_login="alice",
        created_at=now - timedelta(days=200),
        pushed_at=now,
        stargazers_count=120,
        forks_count=2,
        open_issues_count=1,
        watchers_count=120,
        archived=False,
        fork=False,
        language="Python",
        default_branch="main",
        ownership=RepoOwnership.OWNED,
    )


class MetricsTests(unittest.TestCase):
    def test_top_contributor_classification(self):
        self.assertEqual(classify_contribution(rank=1, share=0.5, total_actions=10, active_days=40).value, "top_contributor")


    def test_minor_contributor_classification(self):
        self.assertEqual(classify_contribution(rank=9, share=0.02, total_actions=2, active_days=2).value, "minor_contributor")


    def test_build_rank_input_includes_subject_when_missing(self):
        ranked = build_rank_input("bob", 8, [("alice", 12), ("carol", 4)])
        self.assertTrue(any(login == "__subject__:bob" for login, _ in ranked))


    def test_repo_contribution_summary_rank_and_share(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=5,
            pr_opened_count=3,
            pr_merged_count=2,
            issue_opened_count=1,
            review_count=0,
            first_contribution_at=now - timedelta(days=90),
            last_contribution_at=now - timedelta(days=30),
            total_actions=9,
            contribution_types={},
        )
        ranked = build_rank_input("bob", 9, [("alice", 20), ("carol", 10)])
        summary = build_repo_contribution_summary(repo, contribution, ranked, subject_login="bob")
        self.assertEqual(summary.contributor_rank, 3)
        self.assertEqual(round(summary.contribution_share or 0, 2), 0.45)


    def test_repo_contribution_summary_rank_when_subject_already_in_contributors(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=4,
            pr_opened_count=0,
            pr_merged_count=0,
            issue_opened_count=0,
            review_count=0,
            first_contribution_at=now - timedelta(days=90),
            last_contribution_at=now - timedelta(days=20),
            total_actions=4,
            contribution_types={},
        )
        ranked = build_rank_input("bob", 4, [("alice", 20), ("bob", 8), ("carol", 7)])
        summary = build_repo_contribution_summary(repo, contribution, ranked, subject_login="bob")
        self.assertEqual(summary.contributor_rank, 2)
        self.assertEqual(round(summary.contribution_share or 0, 2), 0.40)


    def test_bucket_stargazers_recent_account_ratio(self):
        now = datetime.now(timezone.utc)
        records = [
            StargazerRecord(login="u1", starred_at=now, account_created_at=now - timedelta(days=10)),
            StargazerRecord(login="u2", starred_at=now, account_created_at=now - timedelta(days=200)),
            StargazerRecord(login="u3", starred_at=now, account_created_at=now - timedelta(days=500)),
        ]
        buckets, recent_ratio, young_ratio, suspicious_ratio = bucket_stargazers(records)
        self.assertEqual(buckets["0_30_days"], 1)
        self.assertEqual(round(recent_ratio or 0, 2), 0.33)
        self.assertEqual(round(young_ratio or 0, 2), 0.33)
        self.assertEqual(round(suspicious_ratio or 0, 2), 0.33)


    def test_star_summary_flags_suspicious_pattern(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        records = [
            StargazerRecord(login=f"u{idx}", starred_at=now, account_created_at=now - timedelta(days=5))
            for idx in range(10)
        ] + [
            StargazerRecord(login=f"v{idx}", starred_at=now, account_created_at=now - timedelta(days=40))
            for idx in range(10)
        ]
        summary = build_star_summary(repo, records)
        self.assertEqual(summary.classification.value, "suspicious_pattern_requiring_caution")


if __name__ == "__main__":
    unittest.main()

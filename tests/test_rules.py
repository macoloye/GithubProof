from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from profile_audit.metrics import build_rank_input, build_repo_contribution_summary, build_star_summary
from profile_audit.models import RepoOwnership, Repository, StargazerRecord, SubjectContribution
from profile_audit.rules import evaluate_contribution_rules, evaluate_star_rules


def _repo() -> Repository:
    now = datetime.now(timezone.utc)
    return Repository(
        name="demo",
        full_name="alice/demo",
        html_url="https://github.com/alice/demo",
        owner_login="alice",
        created_at=now - timedelta(days=400),
        pushed_at=now,
        stargazers_count=100,
        forks_count=1,
        open_issues_count=0,
        watchers_count=100,
        archived=False,
        fork=False,
        language="Python",
        default_branch="main",
        ownership=RepoOwnership.OWNED,
    )


class RuleTests(unittest.TestCase):
    def test_contribution_rules_trigger_late_entry_and_minor_presence(self):
        repo = _repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=1,
            pr_opened_count=0,
            pr_merged_count=0,
            issue_opened_count=0,
            review_count=0,
            first_contribution_at=now - timedelta(days=20),
            last_contribution_at=now - timedelta(days=20),
            total_actions=1,
            contribution_types={},
        )
        ranked = build_rank_input("bob", 1, [("alice", 40), ("carol", 30)])
        summary = build_repo_contribution_summary(repo, contribution, ranked)
        triggered = [item.rule_id for item in evaluate_contribution_rules([summary]) if item.triggered]
        self.assertIn("late_entry_on_repo", triggered)
        self.assertIn("minor_presence_misleading_scope", triggered)


    def test_star_rules_trigger_recent_account_skew(self):
        repo = _repo()
        now = datetime.now(timezone.utc)
        records = [
            StargazerRecord(login=f"s{idx}", starred_at=now, account_created_at=now - timedelta(days=5))
            for idx in range(15)
        ] + [
            StargazerRecord(login=f"o{idx}", starred_at=now, account_created_at=now - timedelta(days=100))
            for idx in range(10)
        ]
        star_summary = build_star_summary(repo, records)
        contribution = SubjectContribution(total_actions=5, contribution_types={})
        ranked = build_rank_input("alice", 50, [("carol", 10)])
        contrib_summary = build_repo_contribution_summary(repo, contribution, ranked)
        triggered = [item.rule_id for item in evaluate_star_rules([star_summary], [contrib_summary]) if item.triggered]
        self.assertIn("many_recently_created_stargazers", triggered)
        self.assertIn("young_account_star_skew", triggered)


if __name__ == "__main__":
    unittest.main()

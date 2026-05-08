from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from profile_audit.metrics import (
    bucket_stargazers,
    build_rank_input,
    build_repo_contribution_summary,
    build_star_summary,
    classify_contribution,
    compute_trust_scores,
    days_since_last_contribution,
    per_repo_velocity,
    severity_breakdown,
)
from profile_audit.models import (
    ContributionLevel,
    CredibilityBand,
    RepoContributionSummary,
    RepoOwnership,
    RepoStarSummary,
    Repository,
    RuleResult,
    StargazerRecord,
    SubjectContribution,
)


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


    def test_per_repo_velocity_and_recency(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=10,
            first_contribution_at=now - timedelta(days=20),
            last_contribution_at=now - timedelta(days=10),
            total_actions=10,
        )
        summary = RepoContributionSummary(
            repository=repo,
            subject=contribution,
            contributor_rank=1,
            contributor_count=1,
            top_contributor_actions=10,
            contribution_share=1.0,
            active_days=10,
            days_from_repo_creation_to_first_contribution=5,
            classification=ContributionLevel.TOP,
        )
        self.assertAlmostEqual(per_repo_velocity(summary), 1.0)
        self.assertEqual(days_since_last_contribution(summary, now=now), 10)

    def test_severity_breakdown_counts_only_triggered(self):
        rules = [
            RuleResult(rule_id="a", category="x", target="t", triggered=True, severity="high", explanation=""),
            RuleResult(rule_id="b", category="x", target="t", triggered=False, severity="high", explanation=""),
            RuleResult(rule_id="c", category="x", target="t", triggered=True, severity="medium", explanation=""),
        ]
        counts = severity_breakdown(rules)
        self.assertEqual(counts["high"], 1)
        self.assertEqual(counts["medium"], 1)
        self.assertEqual(counts["low"], 0)

    def test_compute_trust_scores_rewards_top_contributor(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=10,
            first_contribution_at=now - timedelta(days=60),
            last_contribution_at=now - timedelta(days=10),
            total_actions=10,
        )
        summary = RepoContributionSummary(
            repository=repo,
            subject=contribution,
            contributor_rank=1,
            contributor_count=1,
            top_contributor_actions=10,
            contribution_share=1.0,
            active_days=50,
            days_from_repo_creation_to_first_contribution=0,
            classification=ContributionLevel.TOP,
        )
        star_summary = RepoStarSummary(
            repository=repo,
            total_stars=120,
            analyzed_stargazers=100,
            bucket_counts={"0_30_days": 1, "366_plus_days": 99},
            recent_account_ratio=0.01,
            young_account_ratio=0.01,
            suspicious_ratio=0.01,
            classification=CredibilityBand.ORGANIC,
        )
        scores = compute_trust_scores([summary], [star_summary], rules=[])
        self.assertGreater(scores["composite"], 60)
        self.assertGreaterEqual(scores["contribution"], 35)
        self.assertGreaterEqual(scores["stars"], 95)

    def test_compute_trust_scores_penalizes_high_severity(self):
        repo = make_repo()
        now = datetime.now(timezone.utc)
        contribution = SubjectContribution(
            commit_count=1,
            first_contribution_at=now - timedelta(days=1),
            last_contribution_at=now,
            total_actions=1,
        )
        summary = RepoContributionSummary(
            repository=repo,
            subject=contribution,
            contributor_rank=10,
            contributor_count=20,
            top_contributor_actions=200,
            contribution_share=0.005,
            active_days=1,
            days_from_repo_creation_to_first_contribution=180,
            classification=ContributionLevel.MINOR,
        )
        star_summary = RepoStarSummary(
            repository=repo,
            total_stars=100,
            analyzed_stargazers=80,
            bucket_counts={"0_30_days": 60, "366_plus_days": 20},
            recent_account_ratio=0.75,
            young_account_ratio=0.75,
            suspicious_ratio=0.75,
            classification=CredibilityBand.SUSPICIOUS,
        )
        rules = [
            RuleResult(rule_id="r1", category="contribution", target="t", triggered=True, severity="high", explanation=""),
            RuleResult(rule_id="r2", category="contribution", target="t", triggered=True, severity="high", explanation=""),
            RuleResult(rule_id="r3", category="star", target="t", triggered=True, severity="medium", explanation=""),
        ]
        scores = compute_trust_scores([summary], [star_summary], rules=rules)
        self.assertLess(scores["composite"], 40)
        self.assertGreaterEqual(scores["risk_penalty"], 15)

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

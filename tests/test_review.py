import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.models import MonthSpan
from support import build_demo_service

WINDOW = MonthSpan("2025-01", "2025-12")


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service()
        self.calc_run = self.svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def test_reject_single_indicator_keeps_others(self):
        key = f"{self.calc_run.id}:M1:pollution_reduction:COD"
        self.svc.review(key, "rejected", "缺工况说明", reviewer="评审组")
        view = self.svc.run_view(self.calc_run.id)
        by_key = {r["key"]: r for r in view["results"]}
        self.assertEqual(by_key[key]["review_status"], "rejected")
        # 同一措施的其他指标、其他措施的结论保持有效
        nh3n = by_key[f"{self.calc_run.id}:M1:pollution_reduction:NH3N"]
        self.assertEqual(nh3n["review_status"], "pending")
        self.assertEqual(nh3n["value"], Decimal("18"))
        self.assertNotIn("warning", nh3n)

    def test_rejection_flags_dependents_only(self):
        key = f"{self.calc_run.id}:M1:pollution_reduction:COD"
        outcome = self.svc.review(key, "rejected", "退回补正")
        # M3、M4 依赖 M1 -> 被标记；M2 不受影响
        self.assertEqual(outcome["dependent_measures_flagged"], ["M3", "M4"])
        view = self.svc.run_view(self.calc_run.id)
        by_key = {r["key"]: r for r in view["results"]}
        self.assertIn(
            "warning", by_key[f"{self.calc_run.id}:M3:pollution_reduction:COD"]
        )
        self.assertNotIn(
            "warning", by_key[f"{self.calc_run.id}:M2:pollution_reduction:COD"]
        )

    def test_rejected_excluded_from_portfolio_totals(self):
        key = f"{self.calc_run.id}:M1:pollution_reduction:COD"
        self.svc.review(key, "rejected", "退回补正")
        synergy = self.svc.portfolio_synergy(self.calc_run.id)
        # COD 合计只剩 M2(100) + M3(144) = 244，M1 的 144 被排除
        self.assertEqual(
            Decimal(synergy["pollution_reduction_by_subject"]["COD"]),
            Decimal("244"),
        )
        self.assertIn(key, synergy["excluded_rejected"])

    def test_run_immutable_under_review(self):
        key = f"{self.calc_run.id}:M1:pollution_reduction:COD"
        before = [r.value for r in self.calc_run.results]
        self.svc.review(key, "rejected", "退回补正")
        after = [r.value for r in self.svc.runs[self.calc_run.id].results]
        self.assertEqual(before, after, "评审不得改动计算版本")

    def test_invalid_decision_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.review(f"{self.calc_run.id}:M1:pollution_reduction:COD", "maybe")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from scenario import build_service


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_service()
        self.sid = self.svc.take_snapshot()
        self.report = self.svc.run_evaluation("rules-v1", "流域边界", self.sid)

    def test_reject_single_indicator_keeps_other_conclusions(self):
        self.svc.review_indicator(
            self.report.report_id, "M4:pollution:COD", "rejected",
            "监测断面布设存疑，退回补证", "评审员甲",
        )
        view = self.svc.portfolio(self.report.report_id)
        # 原报告结论未被改写
        self.assertEqual(self.report.totals["pollution:COD"], Decimal("10"))
        # 评审后合计只剔除被退回的指标，其余有效结论保留
        self.assertEqual(view["adjusted_totals_after_review"]["pollution:COD"], "0")
        self.assertEqual(view["adjusted_totals_after_review"]["pollution:TP"], "5")
        self.assertEqual(view["adjusted_totals_after_review"]["ghg:co2e"], "55.00")
        # 被退回指标进入待办，而不是消失
        bounced = {p["indicator"] for p in view["pending"]["退回待整改"]}
        self.assertEqual(bounced, {"M4:pollution:COD"})

    def test_rejected_indicator_can_be_reapproved(self):
        rid = self.report.report_id
        self.svc.review_indicator(rid, "M4:pollution:COD", "rejected", "补证", "甲")
        self.svc.review_indicator(rid, "M4:pollution:COD", "approved", "已补断面记录", "甲")
        view = self.svc.portfolio(rid)
        self.assertEqual(view["adjusted_totals_after_review"]["pollution:COD"], "10")
        self.assertEqual(view["pending"]["退回待整改"], [])

    def test_reject_unknown_indicator_raises(self):
        with self.assertRaises(ValueError):
            self.svc.review_indicator(
                self.report.report_id, "M9:pollution:COD", "rejected", "x", "甲"
            )


if __name__ == "__main__":
    unittest.main()

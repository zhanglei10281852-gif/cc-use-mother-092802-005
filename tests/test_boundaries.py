import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from scenario import build_service


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_service()
        self.sid = self.svc.take_snapshot()

    def test_reconcile_explains_boundary_differences(self):
        diffs = self.svc.reconcile("rules-v1", "流域边界", "行政边界", self.sid)
        by_key = {d.key: d for d in diffs}

        # M2 的 R2 在行政边界内权重 0.5：55 → 27.5
        d = by_key["M2:ghg:co2e"]
        self.assertEqual(d.value_a, Decimal("55.00"))
        self.assertEqual(d.value_b, Decimal("27.500"))
        self.assertTrue(any("权重" in r for r in d.reasons))

        # M3 的 R3 跨界，不在行政边界内
        d3 = by_key["M3:pollution:TP"]
        self.assertEqual(d3.value_a, Decimal("5"))
        self.assertIsNone(d3.value_b)
        self.assertTrue(any("行政边界" in r for r in d3.reasons))

        # M1 完全在两种边界内，不产生差异项
        self.assertNotIn("M1:ghg:co2e", by_key)

    def test_boundary_totals_differ_and_are_explainable(self):
        watershed = self.svc.run_evaluation("rules-v1", "流域边界", self.sid)
        admin = self.svc.run_evaluation("rules-v1", "行政边界", self.sid)
        self.assertEqual(watershed.totals["pollution:TP"], Decimal("5"))
        self.assertNotIn("pollution:TP", admin.totals)  # R3 不在界内，无该指标
        self.assertEqual(watershed.gross_totals["ghg:co2e"], Decimal("110.00"))
        self.assertEqual(admin.gross_totals["ghg:co2e"], Decimal("82.500"))


if __name__ == "__main__":
    unittest.main()

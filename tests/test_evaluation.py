import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from scenario import build_service


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_service()
        self.sid = self.svc.take_snapshot()
        self.report = self.svc.run_evaluation("rules-v1", "流域边界", self.sid)

    def indicator(self, key):
        return next(i for i in self.report.indicators if i.key == key)

    def test_monitoring_gap_suspends_indicator(self):
        ind = self.indicator("M1:pollution:COD")
        self.assertEqual(ind.status, "pending_data")
        self.assertIsNone(ind.value)
        self.assertTrue(any("监测缺期" in n and "2025-06" in n for n in ind.notes))

    def test_ghg_from_energy_evidence(self):
        ind = self.indicator("M1:ghg:co2e")
        self.assertEqual(ind.status, "computed")
        self.assertEqual(ind.value, Decimal("55.00"))  # 100 MWh × 0.55
        self.assertEqual(ind.factor_used, Decimal("0.55"))

    def test_dependency_missing_blocks_measure(self):
        ind = self.indicator("M5:pollution:COD")
        self.assertEqual(ind.status, "blocked")
        self.assertIsNone(ind.value)
        kinds = {c.kind for c in self.report.conflicts}
        self.assertIn("dependency_missing", kinds)

    def test_duplicate_evidence_flagged_and_deduplicated(self):
        dup = next(c for c in self.report.conflicts if c.kind == "duplicate_evidence")
        self.assertEqual(dup.evidence_id, "E1")
        self.assertEqual(set(dup.measure_ids), {"M1", "M2"})
        self.assertEqual(dup.amount_at_risk, Decimal("55.00"))
        # 分别报表的口径下合计 110，去重后 55
        self.assertEqual(self.report.gross_totals["ghg:co2e"], Decimal("110.00"))
        self.assertEqual(self.report.totals["ghg:co2e"], Decimal("55.00"))

    def test_totals_only_count_active_indicators(self):
        # M1 挂起、M5 阻塞，COD 只剩 M4 的 10 t
        self.assertEqual(self.report.totals["pollution:COD"], Decimal("10"))
        self.assertEqual(self.report.totals["pollution:TP"], Decimal("5"))

    def test_report_is_deterministic(self):
        again = self.svc.run_evaluation("rules-v1", "流域边界", self.sid)
        self.assertEqual(again.report_id, self.report.report_id)


if __name__ == "__main__":
    unittest.main()

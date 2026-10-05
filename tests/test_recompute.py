import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.models import MonthSpan
from support import build_demo_service

WINDOW = MonthSpan("2025-01", "2025-12")
BASELINE = MonthSpan("2024-01", "2024-12")


class RecomputeTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service()
        self.run1 = self.svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def _mutate_data(self):
        self.svc.add_monitoring("R2", "COD", "2025-07", "69", "补测")
        self.svc.add_monitoring("R2", "COD", "2025-08", "71", "补测")
        self.svc.revise_baseline(
            "R2", "COD", "72", BASELINE, "v2", "PERMIT-R2-2025-TEMP", "临时许可调整"
        )

    def test_historical_run_recomputes_identically_after_changes(self):
        self._mutate_data()
        check = self.svc.recompute(self.run1.id)
        self.assertTrue(check["matches"], check["differences"])
        self.assertEqual(check["rule_version"], "RS-1")
        self.assertEqual(check["data_seq"], self.run1.data_seq)

    def test_recompute_does_not_overwrite_original(self):
        self._mutate_data()
        n_runs = len(self.svc.runs)
        check = self.svc.recompute(self.run1.id)
        self.assertEqual(len(self.svc.runs), n_runs + 1)
        self.assertNotEqual(check["recomputed_run"], self.run1.id)
        original = self.svc.runs[self.run1.id]
        m2 = [r for r in original.results if r.measure_id == "M2"][0]
        self.assertEqual(m2.value, Decimal("100"))
        self.assertEqual(m2.status, "estimated")

    def test_new_run_reflects_backfill_and_baseline(self):
        self._mutate_data()
        run2 = self.svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        m2 = [r for r in run2.results if r.measure_id == "M2"][0]
        self.assertEqual(m2.value, Decimal("24"))
        self.assertEqual(m2.status, "ok")
        self.assertEqual(m2.gap_months, ())
        self.assertEqual(
            m2.provenance["reach_breakdown"]["R2"]["baseline_version"], "v2"
        )

    def test_recompute_after_ruleset_revision_keeps_original_factors(self):
        self._mutate_data()
        run2 = self.svc.create_run(WINDOW, "B-ADMIN", "RS-2")
        check = self.svc.recompute(run2.id)
        self.assertTrue(check["matches"], check["differences"])
        recomputed = self.svc.runs[check["recomputed_run"]]
        m4 = [
            r
            for r in recomputed.results
            if r.measure_id == "M4" and r.subject == "grid_saving"
        ][0]
        self.assertEqual(m4.value, Decimal("416.00"))
        self.assertEqual(m4.provenance["factor"], "0.52")


if __name__ == "__main__":
    unittest.main()

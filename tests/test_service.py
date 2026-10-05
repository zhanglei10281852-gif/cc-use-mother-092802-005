import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.models import MonthSpan
from support import build_demo_service

WINDOW = MonthSpan("2025-01", "2025-12")


class PortfolioSynergyTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_demo_service()
        self.calc_run = self.svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def test_shared_evidence_counted_once(self):
        synergy = self.svc.portfolio_synergy(self.calc_run.id)
        # M4 与 M5 重复引用 E-INV-01：440 只计一次
        self.assertEqual(Decimal(synergy["ghg_reduction_raw"]), Decimal("2020.00"))
        self.assertEqual(
            Decimal(synergy["ghg_reduction_deduplicated"]), Decimal("1580.00")
        )
        self.assertEqual(len(synergy["conflict_deductions"]), 1)
        deduction = synergy["conflict_deductions"][0]
        self.assertEqual(deduction["evidence_id"], "E-INV-01")
        self.assertEqual(deduction["kept_measure"], "M4")
        self.assertEqual(deduction["dropped_measures"], ["M5"])
        self.assertEqual(Decimal(deduction["deducted"]), Decimal("440.00"))

    def test_co_benefit_and_dependency_chains(self):
        synergy = self.svc.portfolio_synergy(self.calc_run.id)
        # M4 同时产出污染削减与温室气体减排
        self.assertEqual(synergy["co_benefit_measures"], ["M4"])
        chains = {(c["from"], c["to"]) for c in synergy["dependency_chains"]}
        self.assertIn(("M1", "M3"), chains)
        self.assertIn(("M1", "M4"), chains)

    def test_pollution_totals_by_subject(self):
        synergy = self.svc.portfolio_synergy(self.calc_run.id)
        totals = synergy["pollution_reduction_by_subject"]
        # COD: M1 144 + M2 100 + M3 144 = 388；NH3N: M1 18 + M4 18 = 36
        self.assertEqual(Decimal(totals["COD"]), Decimal("388"))
        self.assertEqual(Decimal(totals["NH3N"]), Decimal("36"))


class PendingTests(unittest.TestCase):
    def test_pending_lists_gaps_and_unverified(self):
        svc = build_demo_service()
        run_admin = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        pending = svc.portfolio_pending(run_admin.id)
        gaps = {g["measure_id"]: g for g in pending["monitoring_gaps"]}
        self.assertEqual(gaps["M2"]["gap_months"], ["2025-07", "2025-08"])
        # 行政边界内没有未核实证据
        self.assertEqual(pending["unverified_evidence"], [])

        run_basin = svc.create_run(WINDOW, "B-BASIN", "RS-1")
        pending_basin = svc.portfolio_pending(run_basin.id)
        unverified = {e["evidence_id"] for e in pending_basin["unverified_evidence"]}
        self.assertIn("E-FIELD-01", unverified)

    def test_pending_lists_rejected(self):
        svc = build_demo_service()
        run = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        key = f"{run.id}:M5:ghg_reduction:grid_saving"
        svc.review(key, "rejected", "重复计入")
        pending = svc.portfolio_pending(run.id)
        self.assertEqual(
            pending["rejected_awaiting_resubmission"][0]["result_key"], key
        )


class BoundaryCompareTests(unittest.TestCase):
    def test_compare_boundaries_returns_two_runs_and_report(self):
        svc = build_demo_service()
        outcome = svc.compare_boundaries(WINDOW, "B-ADMIN", "B-BASIN", "RS-2")
        self.assertIn(outcome["run_a"], svc.runs)
        self.assertIn(outcome["run_b"], svc.runs)
        report = outcome["difference"]
        self.assertEqual(
            report.totals_b["pollution_reduction"]
            - report.totals_a["pollution_reduction"],
            Decimal("72"),
        )


if __name__ == "__main__":
    unittest.main()

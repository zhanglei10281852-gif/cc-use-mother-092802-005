import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from scenario import build_service, fill_gap_and_adjust_baseline


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.svc = build_service()
        self.sid = self.svc.take_snapshot()
        self.report = self.svc.run_evaluation("rules-v1", "流域边界", self.sid)
        self.view = self.svc.portfolio(self.report.report_id)

    def test_synergy_lists_cobenefit_measures(self):
        syn = {s["measure_id"]: s for s in self.view["synergies"]}
        self.assertIn("M1", syn)  # 同时有污染与温室气体指标
        self.assertNotIn("M2", syn)  # 只有温室气体
        self.assertEqual(syn["M1"]["ghg_tco2e"], "55.00")
        self.assertIn("pollution:COD", syn["M1"]["pending_metrics"])

    def test_conflicts_surface_duplicate_and_dependency(self):
        kinds = {c["kind"] for c in self.view["conflicts"]}
        self.assertEqual(kinds, {"duplicate_evidence", "dependency_missing"})
        dup = next(c for c in self.view["conflicts"] if c["kind"] == "duplicate_evidence")
        self.assertEqual(dup["evidence_id"], "E1")
        self.assertEqual(dup["amount_at_risk"], "55.00")

    def test_pending_lists_gaps_unverified_and_blocked(self):
        pending = self.view["pending"]
        self.assertIn("M1:pollution:COD", {p["indicator"] for p in pending["待补数据"]})
        self.assertIn("M5:pollution:COD", {p["indicator"] for p in pending["依赖阻塞"]})
        self.assertIn("E1", {u["evidence_id"] for u in pending["未核实证据"]})

    def test_pending_clears_after_gap_filled_and_source_verified(self):
        fill_gap_and_adjust_baseline(self.svc)
        sid2 = self.svc.take_snapshot()
        r2 = self.svc.run_evaluation("rules-v2", "流域边界", sid2)
        view2 = self.svc.portfolio(r2.report_id)
        self.assertEqual(view2["pending"]["未核实证据"], [])
        # M1 缺期已补齐；剩下的是新基准未覆盖的 TP
        self.assertEqual(
            {p["indicator"] for p in view2["pending"]["待补数据"]},
            {"M3:pollution:TP"},
        )


if __name__ == "__main__":
    unittest.main()

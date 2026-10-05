import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.engine import (
    DependencyError,
    MissingBaselineError,
    UnknownActivityKindError,
    topo_sort,
)
from basin_review.models import (
    EnergyActivity,
    Measure,
    MonthSpan,
    RuleSet,
)
from support import build_demo_service

WINDOW = MonthSpan("2025-01", "2025-12")


def _result(run, measure_id, subject):
    for r in run.results:
        if r.measure_id == measure_id and r.subject == subject:
            return r
    raise AssertionError(f"未找到结果 {measure_id}/{subject}")


class TopoSortTests(unittest.TestCase):
    def test_dependency_order(self):
        svc = build_demo_service()
        ordered = [m.id for m in topo_sort(svc.measures)]
        self.assertLess(ordered.index("M1"), ordered.index("M3"))
        self.assertLess(ordered.index("M1"), ordered.index("M4"))

    def test_cycle_rejected(self):
        measures = {
            "A": Measure("A", "a", ("R1",), depends_on=("B",)),
            "B": Measure("B", "b", ("R1",), depends_on=("A",)),
        }
        with self.assertRaises(DependencyError):
            topo_sort(measures)

    def test_missing_dependency_rejected(self):
        measures = {"A": Measure("A", "a", ("R1",), depends_on=("ZZ",))}
        with self.assertRaises(DependencyError):
            topo_sort(measures)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = build_demo_service()
        cls.calc_run = cls.svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def test_pollution_reduction_value(self):
        # (100 - 88) * 12 = 144
        self.assertEqual(_result(self.calc_run, "M1", "COD").value, Decimal("144"))
        # (8 - 6.5) * 12 = 18
        self.assertEqual(_result(self.calc_run, "M1", "NH3N").value, Decimal("18"))

    def test_monitoring_gap_marks_estimated(self):
        r = _result(self.calc_run, "M2", "COD")
        self.assertEqual(r.status, "estimated")
        self.assertEqual(r.gap_months, ("2025-07", "2025-08"))
        # 缺期按已观测的 10 个月折算：(80 - 70) * 10 = 100
        self.assertEqual(r.value, Decimal("100"))

    def test_ghg_uses_ruleset_factor(self):
        # 800 MWh * 0.55 = 440；60 万m3 * 19 = 1140
        self.assertEqual(
            _result(self.calc_run, "M4", "grid_saving").value, Decimal("440.00")
        )
        self.assertEqual(
            _result(self.calc_run, "M4", "biogas_use").value, Decimal("1140")
        )

    def test_boundary_excludes_outside_measures(self):
        self.assertNotIn("M6", self.calc_run.measure_ids)
        self.assertIn("M2", self.calc_run.measure_ids)

    def test_provenance_records_caliber(self):
        r = _result(self.calc_run, "M2", "COD")
        self.assertEqual(r.provenance["rule_version"], "RS-1")
        self.assertEqual(
            r.provenance["reach_breakdown"]["R2"]["baseline_version"], "v1"
        )
        self.assertEqual(r.provenance["data_seq"], self.calc_run.data_seq)

    def test_no_data_when_window_unobserved(self):
        svc = build_demo_service()
        svc.register_measure(Measure("MX", "无监测措施", ("R2",), ("NH3N",)))
        # R2 没有 NH3N 基准线 -> 先补基准线但不补监测
        svc.revise_baseline("R2", "NH3N", "5", MonthSpan("2024-01", "2024-12"), "v1")
        run = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        r = _result(run, "MX", "NH3N")
        self.assertEqual(r.status, "no_data")
        self.assertIsNone(r.value)

    def test_missing_baseline_raises(self):
        svc = build_demo_service()
        svc.register_measure(Measure("MY", "缺基准措施", ("R2",), ("TP",)))
        with self.assertRaises(MissingBaselineError):
            svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def test_unknown_activity_kind_raises(self):
        svc = build_demo_service()
        svc.register_measure(Measure(
            "MZ", "未知能源活动", ("R1",),
            energy_activities=(
                EnergyActivity("solar_thermal", Decimal("3"), "GJ", WINDOW),
            ),
        ))
        with self.assertRaises(UnknownActivityKindError):
            svc.create_run(WINDOW, "B-ADMIN", "RS-1")

    def test_new_ruleset_changes_ghg_only(self):
        svc = build_demo_service()
        run2 = svc.create_run(WINDOW, "B-ADMIN", "RS-2")
        self.assertEqual(
            _result(run2, "M4", "grid_saving").value, Decimal("416.00")
        )
        self.assertEqual(_result(run2, "M1", "COD").value, Decimal("144"))


if __name__ == "__main__":
    unittest.main()

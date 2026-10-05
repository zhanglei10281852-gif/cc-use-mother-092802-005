import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.models import EnergyActivity, Measure, MonthSpan
from support import build_demo_service

WINDOW = MonthSpan("2025-01", "2025-12")


class ConflictTests(unittest.TestCase):
    def test_duplicate_exclusive_evidence_detected(self):
        svc = build_demo_service()
        conflicts = svc.portfolio_conflicts()
        dup = [c for c in conflicts if c.kind == "duplicate_evidence"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0].evidence_id, "E-INV-01")
        self.assertEqual(set(dup[0].measure_ids), {"M4", "M5"})
        self.assertEqual(dup[0].subject, "grid_saving")

    def test_shared_monitoring_report_not_flagged(self):
        # E-MON-R1 是非独占监测报告，M1 与 M3 共用不构成重复计入
        svc = build_demo_service()
        conflicts = svc.portfolio_conflicts()
        self.assertFalse(
            any(c.evidence_id == "E-MON-R1" for c in conflicts),
            "共享监测报告不应被标记为重复引用",
        )

    def test_declared_dependency_avoids_overlap_flag(self):
        # M3 依赖 M1，同河段同污染物不构成未分摊重叠
        svc = build_demo_service()
        conflicts = svc.portfolio_conflicts()
        self.assertFalse(
            any(
                c.kind == "overlap_unallocated"
                and set(c.measure_ids) == {"M1", "M3"}
                for c in conflicts
            )
        )

    def test_overlap_without_dependency_flagged(self):
        svc = build_demo_service()
        svc.register_measure(Measure("M7", "未声明依赖的河道整治", ("R1",), ("COD",)))
        conflicts = svc.portfolio_conflicts()
        overlap = [
            c
            for c in conflicts
            if c.kind == "overlap_unallocated" and "M7" in c.measure_ids
        ]
        self.assertTrue(overlap, "同河段同污染物且未声明依赖应被标记")
        self.assertEqual(overlap[0].severity, "medium")

    def test_non_overlapping_energy_spans_not_flagged(self):
        svc = build_demo_service()
        svc.register_measure(Measure(
            "M8", "跨年能源专项", ("R1",),
            energy_activities=(
                EnergyActivity(
                    "grid_saving", Decimal("100"), "MWh",
                    MonthSpan("2026-01", "2026-12"), "E-INV-01",
                ),
            ),
        ))
        conflicts = svc.portfolio_conflicts()
        for c in conflicts:
            if c.kind == "duplicate_evidence" and c.evidence_id == "E-INV-01":
                self.assertNotIn("M8", c.measure_ids)


if __name__ == "__main__":
    unittest.main()

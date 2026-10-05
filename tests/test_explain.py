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


def _component(report, measure_id, subject):
    for c in report.components:
        if c.measure_id == measure_id and c.subject == subject:
            return c
    raise AssertionError(f"未找到差异分量 {measure_id}/{subject}")


class ExplainTests(unittest.TestCase):
    def test_boundary_difference_attributed_to_scope(self):
        svc = build_demo_service()
        outcome = svc.compare_boundaries(WINDOW, "B-ADMIN", "B-BASIN", "RS-2")
        report = outcome["difference"]
        comp = _component(report, "M6", "COD")
        self.assertEqual(comp.causes, ("boundary_scope",))
        self.assertIsNone(comp.amount_a)
        self.assertEqual(comp.amount_b, Decimal("72"))
        # 两个边界都包含的措施不产生差异分量
        self.assertFalse(
            any(c.measure_id == "M1" for c in report.components),
            "边界内共有措施不应出现在差异中",
        )

    def test_rule_change_attributed_to_ghg_only(self):
        svc = build_demo_service()
        run1 = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        run2 = svc.create_run(WINDOW, "B-ADMIN", "RS-2")
        report = svc.compare_runs(run1.id, run2.id)
        comp = _component(report, "M4", "grid_saving")
        self.assertEqual(comp.causes, ("rule_change",))
        self.assertEqual(comp.delta, Decimal("-24.00"))  # 416 - 440
        # 污染指标不受排放因子修订影响
        self.assertFalse(
            any(c.indicator == "pollution_reduction" for c in report.components)
        )

    def test_baseline_and_monitoring_changes_attributed(self):
        svc = build_demo_service()
        run1 = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        # 补齐监测 + 临时许可调整基准
        svc.add_monitoring("R2", "COD", "2025-07", "69", "补测")
        svc.add_monitoring("R2", "COD", "2025-08", "71", "补测")
        svc.revise_baseline("R2", "COD", "72", BASELINE, "v2", "PERMIT-R2-2025-TEMP")
        run2 = svc.create_run(WINDOW, "B-ADMIN", "RS-1")
        report = svc.compare_runs(run1.id, run2.id)
        comp = _component(report, "M2", "COD")
        self.assertIn("baseline_change", comp.causes)
        self.assertIn("monitoring_change", comp.causes)
        self.assertNotIn("rule_change", comp.causes)
        # 基准 80->72 且补齐 7/8 月：72*12 - (70*10+69+71) = 24
        self.assertEqual(comp.amount_b, Decimal("24"))
        self.assertEqual(comp.delta, Decimal("-76"))

    def test_summary_mentions_causes(self):
        svc = build_demo_service()
        outcome = svc.compare_boundaries(WINDOW, "B-ADMIN", "B-BASIN", "RS-2")
        text = "\n".join(outcome["difference"].summary)
        self.assertIn("边界组成", text)


if __name__ == "__main__":
    unittest.main()

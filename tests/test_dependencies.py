import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from basin_review.contracts import AssessmentWindow
from basin_review.dependencies import structural_violations, topological_order
from basin_review.domain import Measure


def make_measure(mid, depends_on=(), start=(2025, 1, 1), end=(2025, 12, 31)):
    return Measure(
        mid,
        mid,
        ("R1",),
        (),
        (),
        AssessmentWindow(date(*start), date(*end), "baseline-v1"),
        AssessmentWindow(date(2024, 1, 1), date(2024, 12, 31), "baseline-v1"),
        (),
        depends_on,
    )


class DependencyTests(unittest.TestCase):
    def test_topological_order_respects_dependencies(self):
        measures = (
            make_measure("C", ("B",)),
            make_measure("A"),
            make_measure("B", ("A",)),
        )
        order, cycles = topological_order(measures)
        self.assertEqual(order, ("A", "B", "C"))
        self.assertEqual(cycles, ())

    def test_cycle_detected_and_excluded_from_order(self):
        measures = (make_measure("A", ("B",)), make_measure("B", ("A",)), make_measure("C"))
        order, cycles = topological_order(measures)
        self.assertEqual(order, ("C",))
        self.assertEqual(cycles, (("A", "B"),))

    def test_missing_dependency_flagged(self):
        violations = structural_violations((make_measure("A", ("ghost",)),))
        self.assertEqual([v.kind for v in violations], ["dependency_missing"])
        self.assertEqual(violations[0].dependency_id, "ghost")

    def test_temporal_inversion_flagged(self):
        dep = make_measure("A", (), (2025, 1, 1), (2025, 12, 31))
        nxt = make_measure("B", ("A",), (2025, 6, 1), (2025, 12, 31))
        violations = structural_violations((dep, nxt))
        self.assertEqual([v.kind for v in violations], ["dependency_order"])

    def test_legal_sequence_has_no_violation(self):
        dep = make_measure("A", (), (2025, 1, 1), (2025, 6, 30))
        nxt = make_measure("B", ("A",), (2025, 7, 1), (2025, 12, 31))
        self.assertEqual(structural_violations((dep, nxt)), ())


if __name__ == "__main__":
    unittest.main()

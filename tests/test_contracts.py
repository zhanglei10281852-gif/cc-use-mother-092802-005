import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from basin_review.contracts import AssessmentWindow, MeasureEvidence


class BasinContractTests(unittest.TestCase):
    def test_evidence_keeps_baseline_revision(self):
        window = AssessmentWindow(date(2025, 1, 1), date(2025, 12, 31), "baseline-v2")
        evidence = MeasureEvidence("m-1", "e-9", "carbon", Decimal("3"), "tonne", window)
        self.assertEqual(evidence.window.baseline_revision, "baseline-v2")

    def test_window_endpoints_are_dates(self):
        window = AssessmentWindow(date(2025, 1, 1), date(2025, 6, 30), "b1")
        self.assertLess(window.starts_on, window.ends_on)


if __name__ == "__main__":
    unittest.main()

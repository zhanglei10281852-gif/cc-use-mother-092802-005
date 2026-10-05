import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from basin_review.api import Api
from support import build_demo_service


class ApiDispatchTests(unittest.TestCase):
    """在分发层测试 HTTP 接口（不启动服务器）。"""

    def setUp(self):
        self.api = Api(build_demo_service())

    def test_full_workflow_over_http_surface(self):
        status, _ = self.api.dispatch("GET", "/api/health", {})
        self.assertEqual(status, 200)

        status, created = self.api.dispatch(
            "POST",
            "/api/runs",
            {"window_start": "2025-01", "window_end": "2025-12",
             "boundary_id": "B-ADMIN", "rule_version": "RS-1"},
        )
        self.assertEqual(status, 200)
        run_id = created["run_id"]

        status, view = self.api.dispatch("GET", f"/api/runs/{run_id}", {})
        self.assertEqual(status, 200)
        self.assertTrue(view["results"])

        status, conflicts = self.api.dispatch("GET", "/api/portfolio/conflicts", {})
        self.assertEqual(status, 200)
        self.assertEqual(conflicts["conflicts"][0]["kind"], "duplicate_evidence")

        status, synergy = self.api.dispatch(
            "GET", f"/api/portfolio/synergy?run_id={run_id}", {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(synergy["ghg_reduction_deduplicated"], "1580.00")

        # 评审退回单个指标
        key = f"{run_id}:M5:ghg_reduction:grid_saving"
        status, _ = self.api.dispatch(
            "POST", "/api/reviews", {"result_key": key, "decision": "rejected"}
        )
        self.assertEqual(status, 200)

        status, pending = self.api.dispatch(
            "GET", f"/api/portfolio/pending?run_id={run_id}", {}
        )
        self.assertEqual(pending["rejected_awaiting_resubmission"][0]["result_key"], key)

        # 补齐监测 + 调整基准后，历史版本仍按原口径复算
        self.api.dispatch(
            "POST", "/api/monitoring",
            {"reach_id": "R2", "pollutant": "COD", "month": "2025-07", "load": "69"},
        )
        self.api.dispatch(
            "POST", "/api/baselines",
            {"reach_id": "R2", "pollutant": "COD", "monthly_load": "72",
             "span_start": "2024-01", "span_end": "2024-12",
             "version": "v2", "permit_ref": "PERMIT-R2-2025-TEMP"},
        )
        status, check = self.api.dispatch("POST", f"/api/runs/{run_id}/recompute", {})
        self.assertEqual(status, 200)
        self.assertTrue(check["matches"])

        # 边界对比
        status, diff = self.api.dispatch(
            "GET",
            "/api/portfolio/boundary-diff?window_start=2025-01&window_end=2025-12"
            "&boundary_a=B-ADMIN&boundary_b=B-BASIN&rule_version=RS-2",
            {},
        )
        self.assertEqual(status, 200)
        self.assertTrue(diff["difference"]["summary"])

    def test_unknown_route_404(self):
        status, payload = self.api.dispatch("GET", "/api/nope", {})
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    def test_bad_request_400(self):
        status, payload = self.api.dispatch("POST", "/api/runs", {"boundary_id": "B-ADMIN"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()

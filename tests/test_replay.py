import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from scenario import build_service, fill_gap_and_adjust_baseline


def indicator(report, key):
    return next(i for i in report.indicators if i.key == key)


class ReplayTests(unittest.TestCase):
    def test_historical_report_recomputable_after_data_and_rule_changes(self):
        svc = build_service()
        sid1 = svc.take_snapshot()
        r1 = svc.run_evaluation("rules-v1", "流域边界", sid1)
        self.assertEqual(indicator(r1, "M1:pollution:COD").status, "pending_data")

        # 年度复盘之后：补齐监测缺期、许可调整改变基准、票据核实、发布新规则
        fill_gap_and_adjust_baseline(svc)
        sid2 = svc.take_snapshot()
        self.assertNotEqual(sid1, sid2)

        # 1) 历史报告仍可按原口径复算：数据已变，但快照冻结、规则版本保留
        check = svc.replay(r1.report_id)
        self.assertTrue(check.matches, check.detail)

        # 2) 原规则 × 新数据：仅缺期指标翻正，其余口径不变
        r1b = svc.run_evaluation("rules-v1", "流域边界", sid2)
        self.assertEqual(indicator(r1b, "M1:pollution:COD").value, Decimal("40"))
        self.assertEqual(indicator(r1b, "M1:ghg:co2e").value, Decimal("55.00"))
        diffs = svc.explain(r1.report_id, r1b.report_id)
        self.assertEqual([d.key for d in diffs], ["M1:pollution:COD"])
        self.assertTrue(any("状态" in reason for reason in diffs[0].reasons))

        # 3) 新规则 × 新数据：生成可比但不覆盖的计算版本
        r2 = svc.run_evaluation("rules-v2", "流域边界", sid2)
        self.assertNotEqual(r2.report_id, r1.report_id)
        self.assertEqual(indicator(r2, "M1:ghg:co2e").value, Decimal("58.00"))
        self.assertEqual(indicator(r2, "M1:pollution:COD").value, Decimal("40"))
        # 新基准只覆盖了 COD：TP 缺 baseline-v2 基准而挂起
        self.assertEqual(indicator(r2, "M3:pollution:TP").status, "pending_data")

        # 4) 新旧版本并排比较，差异来源可解释
        reasons = {d.key: d.reasons for d in svc.explain(r1b.report_id, r2.report_id)}
        self.assertTrue(any("排放因子" in r for r in reasons["M1:ghg:co2e"]))
        self.assertTrue(any("基准版本" in r for r in reasons["M1:pollution:COD"]))
        self.assertTrue(any("基准版本" in r for r in reasons["M3:pollution:TP"]))

        # 5) 旧报告未被覆盖，复算仍然一致
        self.assertTrue(svc.replay(r1.report_id).matches)
        self.assertEqual(
            svc.portfolio(r1.report_id)["totals"],
            {"ghg:co2e": "55.00", "pollution:COD": "10", "pollution:TP": "5"},
        )

    def test_ruleset_versions_are_immutable(self):
        svc = build_service()
        from basin_review.rules import RuleSet
        from datetime import date

        with self.assertRaises(ValueError):
            svc.publish_ruleset(
                RuleSet("rules-v1", "baseline-v1", {}, date(2026, 1, 1))
            )


if __name__ == "__main__":
    unittest.main()

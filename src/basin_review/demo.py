"""端到端演示：从分别报表到可比、可复算、可评审的评估后端。

情景取自典型年度复盘问题：
- 污染削减与温室气体减排分别报表，同一项能源替代收益被两个措施重复计入；
- 一次临时排污许可调整改变了基准线；
- 监测存在缺期，事后补齐；
- 规则修订（电力排放因子更新）后新旧口径需要可比且不互相覆盖；
- 行政边界与流域边界的结果差异需要解释来源。

运行：``PYTHONPATH=src python -m basin_review.demo``
"""

from __future__ import annotations

import json
from decimal import Decimal

from .models import EnergyActivity, Evidence, Measure, MonthSpan, RuleSet
from .service import BasinService

WINDOW_2025 = MonthSpan("2025-01", "2025-12")
BASELINE_2024 = MonthSpan("2024-01", "2024-12")


def build_demo_service() -> BasinService:
    svc = BasinService()

    # 河段与统计边界
    svc.register_reach("R1", "城区河段")
    svc.register_reach("R2", "工业园区河段")
    svc.register_reach("R3", "上游生态河段")
    svc.register_boundary("B-ADMIN", "行政边界", ["R1", "R2"])
    svc.register_boundary("B-BASIN", "流域边界", ["R1", "R2", "R3"])

    # 基准线（2024 基准期间，排污许可口径）
    svc.revise_baseline("R1", "COD", "100", BASELINE_2024, "v1", "PERMIT-R1-2024")
    svc.revise_baseline("R1", "NH3N", "8", BASELINE_2024, "v1", "PERMIT-R1-2024")
    svc.revise_baseline("R2", "COD", "80", BASELINE_2024, "v1", "PERMIT-R2-2024")
    svc.revise_baseline("R3", "COD", "40", BASELINE_2024, "v1", "PERMIT-R3-2024")

    # 2025 年监测（吨/月）；R2 的 7、8 月缺测，事后补齐
    for i in range(1, 13):
        month = f"2025-{i:02d}"
        svc.add_monitoring("R1", "COD", month, "88", "自动站")
        svc.add_monitoring("R1", "NH3N", month, "6.5", "自动站")
        svc.add_monitoring("R3", "COD", month, "34", "手工监测")
        if month not in ("2025-07", "2025-08"):
            svc.add_monitoring("R2", "COD", month, "70", "自动站")

    # 证据来源
    svc.register_evidence(Evidence("E-MON-R1", "monitoring_report", "市监测站", WINDOW_2025,
                                   status="verified", exclusive=False, doc_ref="年报-2025-R1"))
    svc.register_evidence(Evidence("E-MON-R2", "monitoring_report", "市监测站", WINDOW_2025,
                                   status="verified", exclusive=False, doc_ref="年报-2025-R2"))
    svc.register_evidence(Evidence("E-INV-01", "invoice", "供电公司", WINDOW_2025,
                                   status="verified", exclusive=True, doc_ref="电费结算单-2025"))
    svc.register_evidence(Evidence("E-BIO-01", "meter_report", "沼气计量站", WINDOW_2025,
                                   status="verified", exclusive=True, doc_ref="计量-2025-06"))
    svc.register_evidence(Evidence("E-FIELD-01", "field_record", "项目组", WINDOW_2025,
                                   status="unverified", exclusive=True, doc_ref="现场记录-37"))

    # 治理措施登记
    svc.register_measure(Measure(
        "M1", "污水处理厂提标改造", ("R1",), ("COD", "NH3N"),
        baseline_span=BASELINE_2024, evidence_ids=("E-MON-R1",),
    ))
    svc.register_measure(Measure(
        "M2", "工业园区预处理设施", ("R2",), ("COD",),
        baseline_span=BASELINE_2024, evidence_ids=("E-MON-R2",),
    ))
    svc.register_measure(Measure(
        "M3", "深度处理与回用", ("R1",), ("COD",),
        baseline_span=BASELINE_2024, evidence_ids=("E-MON-R1",), depends_on=("M1",),
    ))
    svc.register_measure(Measure(
        "M4", "沼气回收与能源替代", ("R1",), ("NH3N",),
        energy_activities=(
            EnergyActivity("biogas_use", Decimal("60"), "万m3", WINDOW_2025, "E-BIO-01"),
            EnergyActivity("grid_saving", Decimal("800"), "MWh", WINDOW_2025, "E-INV-01"),
        ),
        baseline_span=BASELINE_2024, depends_on=("M1",),
    ))
    svc.register_measure(Measure(
        "M5", "厂区能源替代专项", ("R1",),
        energy_activities=(
            EnergyActivity("grid_saving", Decimal("800"), "MWh", WINDOW_2025, "E-INV-01"),
        ),
        baseline_span=BASELINE_2024,
    ))
    svc.register_measure(Measure(
        "M6", "上游生态缓冲带", ("R3",), ("COD",),
        baseline_span=BASELINE_2024, evidence_ids=("E-FIELD-01",),
    ))

    # 规则版本：RS-1 初始口径；RS-2 修订电力排放因子
    svc.register_ruleset(RuleSet(
        "RS-1",
        {"grid_saving": Decimal("0.55"), "biogas_use": Decimal("19")},
        note="初始口径", issued_on="2025-01-01",
    ))
    svc.register_ruleset(RuleSet(
        "RS-2",
        {"grid_saving": Decimal("0.52"), "biogas_use": Decimal("19")},
        note="修订电力排放因子", issued_on="2025-09-15",
    ))
    return svc


def _print(title: str, payload) -> None:
    print(f"\n=== {title} ===")
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(text if len(text) < 2400 else text[:2400] + "\n...（截断）")


def main() -> None:
    svc = build_demo_service()

    # 1) 年度报表：行政边界 + 初始规则
    run1 = svc.create_run(WINDOW_2025, "B-ADMIN", "RS-1")
    _print("1. 年度计算版本（行政边界 / RS-1）", svc.run_view(run1.id))

    # 2) 冲突检测：同一电费证据被 M4、M5 重复引用
    _print("2. 冲突项（跨措施重复引用证据）",
           [c.__dict__ for c in svc.portfolio_conflicts()])

    # 3) 评审：退回重复计入的 M5 温室气体指标；退回 M1 的 COD（待补充说明）
    svc.review(f"{run1.id}:M5:ghg_reduction:grid_saving", "rejected",
               "与 M4 重复引用 E-INV-01", reviewer="评审组")
    svc.review(f"{run1.id}:M1:pollution_reduction:COD", "rejected",
               "缺 7-8 月工况说明，退回补正", reviewer="评审组")
    _print("3. 评审后计算版本（其他结论保留，下游依赖仅标记）", svc.run_view(run1.id))

    # 4) 组合协同收益：重复证据只计一次
    _print("4. 项目组合协同收益（去重后）", svc.portfolio_synergy(run1.id))

    # 5) 尚待核实
    _print("5. 尚待核实的数据", svc.portfolio_pending(run1.id))

    # 6) 监测补齐 + 临时排污许可调整基准 + 规则修订
    svc.add_monitoring("R2", "COD", "2025-07", "69", "补测")
    svc.add_monitoring("R2", "COD", "2025-08", "71", "补测")
    svc.revise_baseline("R2", "COD", "72", BASELINE_2024, "v2",
                        "PERMIT-R2-2025-TEMP", "临时排污许可调整")
    run2 = svc.create_run(WINDOW_2025, "B-ADMIN", "RS-2")
    _print("6. 新计算版本（补齐监测 / 基准 v2 / RS-2）", svc.run_view(run2.id))

    # 7) 新旧版本差异归因
    diff = svc.compare_runs(run1.id, run2.id)
    _print("7. 版本间差异归因", diff.summary + tuple(
        f"{c.measure_id}/{c.subject}: {c.amount_a} -> {c.amount_b}（{c.detail}）"
        for c in diff.components
    ))

    # 8) 历史报告按原口径复算
    _print("8. 原口径复算校验（run-1）", svc.recompute(run1.id))

    # 9) 统计边界对比：行政 vs 流域
    boundary_diff = svc.compare_boundaries(WINDOW_2025, "B-ADMIN", "B-BASIN", "RS-2")
    _print("9. 边界差异归因（行政 vs 流域）",
           boundary_diff["difference"].summary + tuple(
               f"{c.measure_id}/{c.subject}: {c.amount_a} -> {c.amount_b}（{c.detail}）"
               for c in boundary_diff["difference"].components
           ))

    # 10) 流域口径下的待核实数据（含未核实证据 E-FIELD-01）
    _print("10. 流域口径待核实", svc.portfolio_pending(boundary_diff["run_b"]))


if __name__ == "__main__":
    main()

"""年度复盘演示场景：污染削减与温室气体减排曾分别报表。

情节：
- M1 污水处理厂提标（R1，COD + 节电），M2 光伏替代（R2）——两者重复引用同一份
  能源替代票据 E1，同一项收益被分别计入两张报表；
- M1 的 R1/COD 监测缺 2025-06（监测缺期）；
- M4 依赖 M1（先后依赖，顺序合法）；M5 依赖未登记的 M0（依赖缺失）；
- 年中一次临时排污许可调整把 COD 基准从 baseline-v1 改为 baseline-v2，
  规则随之发布 rules-v2（新排放因子），旧口径保留可复算。
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from basin_review.contracts import AssessmentWindow, MeasureEvidence
from basin_review.domain import (
    Baseline,
    Boundary,
    EvidenceSource,
    Measure,
    MonitoringRecord,
    Reach,
)
from basin_review.rules import RuleSet
from basin_review.service import BasinReviewService

D = Decimal


def _window(start_month: int, end_month: int, year: int = 2025) -> AssessmentWindow:
    return AssessmentWindow(date(year, start_month, 1), date(year, end_month, 28), "baseline-v1")


def build_service() -> BasinReviewService:
    svc = BasinReviewService()
    svc.register_reach(Reach("R1", "上游清水河段", "澜沧江支流"))
    svc.register_reach(Reach("R2", "中游灌区段", "澜沧江支流"))
    svc.register_reach(Reach("R3", "下游跨界段", "澜沧江支流"))

    svc.register_source(
        EvidenceSource("SRC-1", "季度监测报告 JM-2025-Q4", ("E2", "E4", "E5", "E6"), True)
    )
    svc.register_source(EvidenceSource("SRC-2", "能源替代结算票据 INV-88", ("E1",), False))
    svc.register_source(EvidenceSource("SRC-3", "排污许可调整文件 PA-2025-17", (), True))

    base_period = AssessmentWindow(date(2024, 1, 1), date(2024, 12, 31), "baseline-v1")
    svc.register_baseline(Baseline("pollution:COD", "R1", "baseline-v1", D("100"), "t", base_period))
    svc.register_baseline(Baseline("pollution:TP", "R3", "baseline-v1", D("12"), "t", base_period))

    svc.register_measure(
        Measure(
            "M1", "污水处理厂提标", ("R1",), ("COD",), ("grid_electricity",),
            _window(1, 6), base_period, ("E1", "E2"),
        )
    )
    svc.register_measure(
        Measure(
            "M2", "光伏替代燃煤锅炉", ("R2",), (), ("grid_electricity",),
            _window(1, 12), base_period, ("E1",),
        )
    )
    svc.register_measure(
        Measure("M3", "生态缓冲带", ("R3",), ("TP",), (), _window(3, 11), base_period, ("E4",))
    )
    svc.register_measure(
        Measure(
            "M4", "深度处理扩容", ("R1",), ("COD",), (),
            _window(7, 12), base_period, ("E5",), ("M1",),
        )
    )
    svc.register_measure(
        Measure(
            "M5", "河口湿地（前置工程未登记）", ("R2",), ("COD",), (),
            _window(4, 10), base_period, ("E6",), ("M0",),
        )
    )

    year_window = _window(1, 12)
    svc.register_evidence(
        MeasureEvidence("M1", "E1", "energy:grid_electricity", D("100"), "MWh", year_window)
    )
    # 同一份票据 E1 又被 M2 引用 —— 重复计入的来源
    svc.register_evidence(
        MeasureEvidence("M2", "E1", "energy:grid_electricity", D("100"), "MWh", year_window)
    )
    svc.register_evidence(MeasureEvidence("M1", "E2", "pollution:COD", D("40"), "t", year_window))
    svc.register_evidence(MeasureEvidence("M3", "E4", "pollution:TP", D("5"), "t", year_window))
    svc.register_evidence(MeasureEvidence("M4", "E5", "pollution:COD", D("10"), "t", year_window))
    svc.register_evidence(MeasureEvidence("M5", "E6", "pollution:COD", D("8"), "t", year_window))

    # 监测：R1/COD 缺 2025-06；R3/TP 齐全
    for month in range(1, 13):
        if month != 6:
            svc.register_monitoring(MonitoringRecord("R1", "COD", date(2025, month, 1), D("2.1")))
    for month in range(3, 12):
        svc.register_monitoring(MonitoringRecord("R3", "TP", date(2025, month, 1), D("0.4")))

    svc.publish_ruleset(
        RuleSet(
            "rules-v1",
            "baseline-v1",
            {"grid_electricity": D("0.55"), "coal": D("0.90")},
            date(2025, 1, 1),
            gap_policy="strict",
        )
    )
    svc.define_boundary(Boundary("流域边界", {"R1": D(1), "R2": D(1), "R3": D(1)}))
    # 行政边界：R3 跨界不计入，R2 只有一半在辖区内
    svc.define_boundary(Boundary("行政边界", {"R1": D(1), "R2": D("0.5")}))
    return svc


def fill_gap_and_adjust_baseline(svc: BasinReviewService) -> None:
    """年度复盘之后：补齐监测缺期；许可调整产生新基准版本；票据核实；发布新规则。"""
    svc.register_monitoring(MonitoringRecord("R1", "COD", date(2025, 6, 1), D("2.0")))
    svc.register_baseline(
        Baseline(
            "pollution:COD", "R1", "baseline-v2", D("90"), "t",
            AssessmentWindow(date(2024, 1, 1), date(2024, 12, 31), "baseline-v2"),
        )
    )
    svc.verify_source("SRC-2")
    svc.publish_ruleset(
        RuleSet(
            "rules-v2",
            "baseline-v2",
            {"grid_electricity": D("0.58"), "coal": D("0.92")},
            date(2026, 1, 1),
            gap_policy="strict",
            notes="排污许可临时调整后的新口径",
        )
    )

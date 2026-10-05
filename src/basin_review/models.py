"""流域治理评估的领域模型。

所有会随时间变化的记录（监测值、基准线、证据状态）都由
:class:`basin_review.store.Ledger` 以只增不改的方式保存，
本模块中的实体本身是不可变的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


# ---------------------------------------------------------------------------
# 期间


def _month_index(label: str) -> int:
    """把 ``YYYY-MM`` 转成可比较的序号。"""
    try:
        year, month = label.split("-")
        year_i, month_i = int(year), int(month)
    except ValueError as exc:  # pragma: no cover - 防御性校验
        raise ValueError(f"非法月份标签: {label!r}，应为 YYYY-MM") from exc
    if not 1 <= month_i <= 12:
        raise ValueError(f"非法月份标签: {label!r}，月份需在 01-12 之间")
    return year_i * 12 + (month_i - 1)


def _month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass(frozen=True)
class MonthSpan:
    """闭区间月份区间，如 ``MonthSpan("2025-01", "2025-12")``。"""

    start: str
    end: str

    def __post_init__(self) -> None:
        if _month_index(self.start) > _month_index(self.end):
            raise ValueError(f"期间起点晚于终点: {self.start} > {self.end}")

    def months(self) -> tuple[str, ...]:
        lo, hi = _month_index(self.start), _month_index(self.end)
        return tuple(_month_label(i) for i in range(lo, hi + 1))

    def overlaps(self, other: "MonthSpan") -> bool:
        return _month_index(self.start) <= _month_index(other.end) and _month_index(
            other.start
        ) <= _month_index(self.end)

    def contains(self, month: str) -> bool:
        return _month_index(self.start) <= _month_index(month) <= _month_index(self.end)

    def intersection(self, other: "MonthSpan") -> Optional["MonthSpan"]:
        if not self.overlaps(other):
            return None
        lo = max(_month_index(self.start), _month_index(other.start))
        hi = min(_month_index(self.end), _month_index(other.end))
        return MonthSpan(_month_label(lo), _month_label(hi))


# ---------------------------------------------------------------------------
# 空间维度


@dataclass(frozen=True)
class Reach:
    """河段。"""

    id: str
    name: str


@dataclass(frozen=True)
class StatisticalBoundary:
    """统计边界：一组河段的集合，如行政边界、流域边界。"""

    id: str
    name: str
    reach_ids: frozenset[str]


# ---------------------------------------------------------------------------
# 证据与监测


#: 证据核实状态
EVIDENCE_UNVERIFIED = "unverified"
EVIDENCE_VERIFIED = "verified"
EVIDENCE_REJECTED = "rejected"


@dataclass(frozen=True)
class Evidence:
    """证据来源（电费单、许可文件、监测报告、现场记录等）。

    ``exclusive=True`` 表示该证据只能支撑一个措施的同一指标
    （如电费单、计量读数）；共享监测报告应置为 ``False``。
    """

    id: str
    kind: str
    issuer: str
    span: MonthSpan
    status: str = EVIDENCE_UNVERIFIED
    exclusive: bool = True
    doc_ref: str = ""
    recorded_seq: int = 0  # 由 Ledger 赋值


@dataclass(frozen=True)
class MonitoringRecord:
    """某河段某污染物单月负荷监测记录（吨/月）。"""

    reach_id: str
    pollutant: str
    month: str
    load: Decimal
    source: str = ""
    recorded_seq: int = 0  # 由 Ledger 赋值


@dataclass(frozen=True)
class Baseline:
    """基准线：某河段某污染物的基准月负荷。

    排污许可调整等情形通过追加新的 ``version`` 生效，旧版本保留，
    历史计算版本仍按原基准复算。
    """

    reach_id: str
    pollutant: str
    monthly_load: Decimal
    span: MonthSpan
    version: str
    permit_ref: str = ""
    note: str = ""
    recorded_seq: int = 0  # 由 Ledger 赋值


# ---------------------------------------------------------------------------
# 治理措施与规则


@dataclass(frozen=True)
class EnergyActivity:
    """能源活动：措施带来的能源替代/节约量。"""

    kind: str  # 如 "grid_saving"（节电）、"biogas_use"（沼气利用）
    amount: Decimal
    unit: str
    span: MonthSpan
    evidence_id: str = ""


@dataclass(frozen=True)
class Measure:
    """治理措施登记。

    - ``reach_ids``：适用河段
    - ``pollutants``：考核污染物
    - ``energy_activities``：能源活动
    - ``baseline_span``：基准期间
    - ``evidence_ids``：证据来源（措施级，如监测报告）
    - ``depends_on``：先后依赖的措施 id（前序措施见效后本措施才评估）
    """

    id: str
    name: str
    reach_ids: tuple[str, ...]
    pollutants: tuple[str, ...] = ()
    energy_activities: tuple[EnergyActivity, ...] = ()
    baseline_span: MonthSpan = MonthSpan("2024-01", "2024-12")
    evidence_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class RuleSet:
    """计算规则版本：排放因子与口径说明。

    规则修订时登记新的 RuleSet，旧版本保留，新旧计算版本可比且不互相覆盖。
    """

    version: str
    emission_factors: dict[str, Decimal]
    note: str = ""
    issued_on: str = ""


# ---------------------------------------------------------------------------
# 计算结果


#: 指标结果状态
STATUS_OK = "ok"
STATUS_ESTIMATED = "estimated"  # 监测缺期，按已观测月份折算
STATUS_NO_DATA = "no_data"  # 窗口内无任何监测记录

INDICATOR_POLLUTION = "pollution_reduction"
INDICATOR_GHG = "ghg_reduction"


@dataclass(frozen=True)
class IndicatorResult:
    """单个措施单个指标的计算结果。

    ``provenance`` 记录得出该数值所用的规则版本、基准版本、
    数据快照序号与排放因子，用于差异归因与原口径复算。
    """

    run_id: str
    measure_id: str
    indicator: str
    subject: str  # 污染物代码或能源活动类型
    span: MonthSpan
    value: Optional[Decimal]
    unit: str
    status: str = STATUS_OK
    gap_months: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    provenance: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.run_id}:{self.measure_id}:{self.indicator}:{self.subject}"


@dataclass(frozen=True)
class CalculationRun:
    """一次不可变的计算版本。

    同一批措施在规则修订、基准调整或监测补齐后重新计算时，
    生成新的 CalculationRun，旧版本保留且可按原口径复算。
    """

    id: str
    rule_version: str
    boundary_id: str
    window: MonthSpan
    data_seq: int  # 计算时可见的数据快照序号
    measure_ids: tuple[str, ...]
    results: tuple[IndicatorResult, ...]
    warnings: tuple[str, ...] = ()
    recompute_of: str = ""

    def results_for(self, measure_id: str) -> tuple[IndicatorResult, ...]:
        return tuple(r for r in self.results if r.measure_id == measure_id)


# ---------------------------------------------------------------------------
# 评审


REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_PENDING = "pending"


@dataclass(frozen=True)
class ReviewDecision:
    """对单个指标结果的评审决定，不改动计算版本本身。"""

    result_key: str
    decision: str  # REVIEW_APPROVED / REVIEW_REJECTED
    note: str = ""
    reviewer: str = ""
    seq: int = 0

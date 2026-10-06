"""流域治理评估的领域实体。

每个治理措施登记适用河段、污染物、能源活动、基准期间与证据来源。
所有实体不可变：数据修正（补齐监测、调整基准）以追加新记录的方式
进入下一份快照，历史快照保持不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from .contracts import AssessmentWindow


@dataclass(frozen=True)
class Reach:
    """河段。"""

    reach_id: str
    name: str
    basin: str


@dataclass(frozen=True)
class Measure:
    """治理措施登记卡。"""

    measure_id: str
    name: str
    reach_ids: tuple[str, ...]  # 适用河段
    pollutants: tuple[str, ...]  # 污染物（如 COD、NH3-N、TP）
    energy_activities: tuple[str, ...]  # 能源活动（如 grid_electricity、coal）
    window: AssessmentWindow  # 实施窗口
    baseline_period: AssessmentWindow  # 基准期间
    evidence_ids: tuple[str, ...] = ()  # 引用的证据来源
    depends_on: tuple[str, ...] = ()  # 先后依赖的前置措施


@dataclass(frozen=True)
class EvidenceSource:
    """证据来源（监测报告、结算票据、许可文件等）。"""

    source_id: str
    origin: str
    evidence_ids: tuple[str, ...] = ()
    verified: bool = False


@dataclass(frozen=True)
class MonitoringRecord:
    """逐月监测记录；窗口内缺月份即监测缺期。"""

    reach_id: str
    pollutant: str
    month: date  # 当月首日
    value: Decimal


@dataclass(frozen=True)
class Baseline:
    """某一基准版本下、某河段、某指标的基准值。

    临时排污许可调整等情形产生新的 revision，而不是覆盖旧版本，
    使历史报告仍可按原基准复算。
    """

    metric: str
    reach_id: str
    revision: str  # 基准版本，如 baseline-v1
    value: Decimal
    unit: str
    period: AssessmentWindow


@dataclass(frozen=True)
class Boundary:
    """统计边界：河段 -> 计入权重（未列出的河段权重为 0）。"""

    name: str
    reach_weights: Mapping[str, Decimal]

    def weight_for(self, reach_ids: tuple[str, ...]) -> Decimal:
        """措施在边界内的计入权重：其适用河段权重的均值。"""
        if not reach_ids:
            return Decimal(0)
        total = sum(
            (self.reach_weights.get(r, Decimal(0)) for r in reach_ids), Decimal(0)
        )
        return total / len(reach_ids)

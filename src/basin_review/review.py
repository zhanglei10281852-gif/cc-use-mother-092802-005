"""评审：按指标粒度退回或确认，不丢弃其他有效结论。

评审决定与计算报告分离存放：退回只改变"生效指标集合"，
不改写报告本身，因此被退回的指标可随时恢复，其余结论不受影响。
"""

from __future__ import annotations

from dataclasses import dataclass

from .evaluation import IndicatorResult, Report


@dataclass(frozen=True)
class ReviewDecision:
    report_id: str
    indicator_key: str
    decision: str  # approved | rejected
    reason: str
    reviewer: str


class ReviewBoard:
    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], ReviewDecision] = {}

    def record(self, decision: ReviewDecision) -> None:
        # 同一指标的后一次决定覆盖前一次（退回后整改可再确认）
        self._decisions[(decision.report_id, decision.indicator_key)] = decision

    def decisions_for(self, report_id: str) -> tuple[ReviewDecision, ...]:
        return tuple(
            d for (rid, _), d in sorted(self._decisions.items()) if rid == report_id
        )

    def rejected_keys(self, report_id: str) -> frozenset[str]:
        return frozenset(
            key
            for (rid, key), d in self._decisions.items()
            if rid == report_id and d.decision == "rejected"
        )

    def effective_indicators(self, report: Report) -> tuple[IndicatorResult, ...]:
        """剔除被退回指标后的生效集合；报告本身保持不变。"""
        rejected = self.rejected_keys(report.report_id)
        return tuple(i for i in report.indicators if i.key not in rejected)

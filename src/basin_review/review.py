"""指标级评审工作流。

评审决定存放在独立的登记簿中，不改动不可变的计算版本：
退回（reject）某个指标只影响该指标本身，同一计算版本中的其他
结论保持有效；被退回措施的下游依赖措施仅追加提示，不丢弃结果。
"""

from __future__ import annotations

from .models import (
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    Measure,
    ReviewDecision,
)


class ReviewRegistry:
    """按结果 key 记录最新评审决定。"""

    def __init__(self) -> None:
        self._decisions: dict[str, ReviewDecision] = {}
        self._seq = 0

    def decide(
        self,
        result_key: str,
        decision: str,
        note: str = "",
        reviewer: str = "",
    ) -> ReviewDecision:
        if decision not in (REVIEW_APPROVED, REVIEW_REJECTED):
            raise ValueError(f"非法评审决定: {decision!r}")
        self._seq += 1
        record = ReviewDecision(
            result_key=result_key,
            decision=decision,
            note=note,
            reviewer=reviewer,
            seq=self._seq,
        )
        self._decisions[result_key] = record
        return record

    def status_of(self, result_key: str) -> str:
        record = self._decisions.get(result_key)
        return record.decision if record else REVIEW_PENDING

    def decision_of(self, result_key: str) -> ReviewDecision | None:
        return self._decisions.get(result_key)

    def rejected_keys(self) -> set[str]:
        return {k for k, d in self._decisions.items() if d.decision == REVIEW_REJECTED}


def dependent_measures(measures: dict[str, Measure], root_ids: set[str]) -> set[str]:
    """返回直接或间接依赖于 ``root_ids`` 的措施集合（不含自身）。"""
    affected: set[str] = set()
    changed = True
    while changed:
        changed = False
        for m in measures.values():
            if m.id in root_ids or m.id in affected:
                continue
            if any(dep in root_ids or dep in affected for dep in m.depends_on):
                affected.add(m.id)
                changed = True
    return affected

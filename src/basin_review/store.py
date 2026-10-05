"""只增不改的版本化台账。

所有监测记录、基准线版本、证据版本追加时分配单调递增的
``recorded_seq``。计算版本（CalculationRun）记录计算时刻的
``data_seq``，之后无论补齐监测还是调整基准，按原 ``data_seq``
仍然看到当时的数据视图，从而保证历史报告可按原口径复算。
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Optional

from .models import Baseline, Evidence, MonitoringRecord, MonthSpan


class Ledger:
    """监测记录、基准线与证据的追加式存储。"""

    def __init__(self) -> None:
        self._seq = 0
        self._monitoring: list[MonitoringRecord] = []
        self._baselines: list[Baseline] = []
        self._evidence: list[Evidence] = []

    # -- 写入（只增不改） -------------------------------------------------

    def _tick(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def current_seq(self) -> int:
        return self._seq

    def add_monitoring(
        self,
        reach_id: str,
        pollutant: str,
        month: str,
        load: Decimal,
        source: str = "",
    ) -> MonitoringRecord:
        record = MonitoringRecord(
            reach_id=reach_id,
            pollutant=pollutant,
            month=month,
            load=load,
            source=source,
            recorded_seq=self._tick(),
        )
        self._monitoring.append(record)
        return record

    def add_baseline(
        self,
        reach_id: str,
        pollutant: str,
        monthly_load: Decimal,
        span: MonthSpan,
        version: str,
        permit_ref: str = "",
        note: str = "",
    ) -> Baseline:
        baseline = Baseline(
            reach_id=reach_id,
            pollutant=pollutant,
            monthly_load=monthly_load,
            span=span,
            version=version,
            permit_ref=permit_ref,
            note=note,
            recorded_seq=self._tick(),
        )
        self._baselines.append(baseline)
        return baseline

    def add_evidence(self, evidence: Evidence) -> Evidence:
        """登记证据；同一 id 再次登记视为该证据的新版本（如核实状态变更）。"""
        versioned = replace(evidence, recorded_seq=self._tick())
        self._evidence.append(versioned)
        return versioned

    # -- 按快照序号读取 ----------------------------------------------------

    def monitoring_as_of(
        self,
        reach_id: str,
        pollutant: str,
        window: MonthSpan,
        seq: int,
    ) -> list[MonitoringRecord]:
        return [
            r
            for r in self._monitoring
            if r.reach_id == reach_id
            and r.pollutant == pollutant
            and r.recorded_seq <= seq
            and window.contains(r.month)
        ]

    def baseline_as_of(
        self, reach_id: str, pollutant: str, seq: int
    ) -> Optional[Baseline]:
        candidates = [
            b
            for b in self._baselines
            if b.reach_id == reach_id
            and b.pollutant == pollutant
            and b.recorded_seq <= seq
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda b: b.recorded_seq)

    def evidence_as_of(self, seq: int) -> dict[str, Evidence]:
        """返回截至 ``seq`` 各证据的最新版本。"""
        latest: dict[str, Evidence] = {}
        for e in self._evidence:
            if e.recorded_seq > seq:
                continue
            prev = latest.get(e.id)
            if prev is None or prev.recorded_seq < e.recorded_seq:
                latest[e.id] = e
        return latest

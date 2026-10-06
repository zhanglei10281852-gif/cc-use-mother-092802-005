"""计算规则版本。

规则修订只发布新版本，绝不覆盖旧版本；每套规则钉住一个基准版本，
因此历史报告始终可按原口径复算，新旧口径的结果可并排比较。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class RuleSet:
    """一套不可变的计算口径。"""

    version: str
    baseline_revision: str  # 本口径钉住的基准版本
    emission_factors: Mapping[str, Decimal]  # 能源活动 -> 排放因子（tCO2e/单位）
    published_on: date
    gap_policy: str = "strict"  # strict=监测缺期挂起；interpolate=标记为估算
    dedupe_shared_evidence: bool = True  # 合计时同一证据只计一次
    notes: str = ""

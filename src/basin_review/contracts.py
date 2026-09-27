"""治理措施与指标证据契约。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class AssessmentWindow:
    starts_on: date
    ends_on: date
    baseline_revision: str


@dataclass(frozen=True)
class MeasureEvidence:
    measure_id: str
    evidence_id: str
    metric: str
    amount: Decimal
    unit: str
    window: AssessmentWindow

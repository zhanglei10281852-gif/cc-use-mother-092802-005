"""确定性序列化、哈希与月份工具。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping


def to_canonical(obj: Any) -> Any:
    """把领域对象转换为可确定性 JSON 序列化的结构。"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_canonical(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Mapping):
        return {str(k): to_canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, frozenset, set)):
        return [to_canonical(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(
        to_canonical(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:16]


def month_range(start: date, end: date) -> tuple[date, ...]:
    """[start, end] 覆盖的全部月份（以每月首日表示）。"""
    months: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(date(year, month, 1))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return tuple(months)

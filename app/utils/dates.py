from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterator

DATE_FMT = "%Y-%m-%d"


def parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_FMT).date()


def format_date(value: date) -> str:
    return value.strftime(DATE_FMT)


def today_local() -> date:
    return date.today()


def iter_dates(start: date, end: date) -> Iterator[date]:
    if end < start:
        raise ValueError("end date must be >= start date")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def rolling_window(end_date: date, days: int) -> tuple[date, date]:
    if days <= 0:
        raise ValueError("days must be > 0")
    start_date = end_date - timedelta(days=days - 1)
    return start_date, end_date

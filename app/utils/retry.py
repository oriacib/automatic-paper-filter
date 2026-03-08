from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_retry(
    func: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.2,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except retry_exceptions:
            if attempt >= max_attempts:
                raise
            sleep_seconds = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if jitter > 0:
                sleep_seconds *= 1 + random.uniform(-jitter, jitter)
            time.sleep(max(0, sleep_seconds))

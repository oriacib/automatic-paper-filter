from __future__ import annotations

import time
from collections.abc import Callable

import requests


class NetworkAwareScheduler:
    def __init__(
        self,
        job: Callable[[], None],
        *,
        interval_seconds: int,
        network_check_url: str,
        logger,
        notifier=None,
        max_backoff_seconds: int = 600,
    ) -> None:
        self.job = job
        self.interval_seconds = interval_seconds
        self.network_check_url = network_check_url
        self.logger = logger
        self.notifier = notifier
        self.max_backoff_seconds = max_backoff_seconds

    def _network_ok(self) -> bool:
        try:
            response = requests.get(self.network_check_url, timeout=5)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def run_forever(self) -> None:
        backoff = 1
        network_alerted = False
        while True:
            if not self._network_ok():
                self.logger.warning("network unavailable, retry in %ss", backoff)
                if self.notifier and not network_alerted:
                    self.notifier.popup(
                        "PaperWatcher 失败提醒",
                        "网络不可用或超时，本轮抓取已放弃，系统将自动重试。",
                        level="error",
                    )
                    network_alerted = True
                time.sleep(backoff)
                backoff = min(self.max_backoff_seconds, backoff * 2)
                continue

            try:
                network_alerted = False
                self.job()
                backoff = 1
                time.sleep(self.interval_seconds)
            except Exception as exc:
                self.logger.exception("job failed: %s", exc)
                if self.notifier:
                    self.notifier.popup(
                        "PaperWatcher 失败提醒",
                        f"本轮抓取执行失败: {exc}",
                        level="error",
                    )
                time.sleep(backoff)
                backoff = min(self.max_backoff_seconds, backoff * 2)

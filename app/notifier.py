from __future__ import annotations

import os
import shutil
import subprocess

class Notifier:
    def __init__(self, logger, *, popup_enabled: bool = False, popup_timeout_seconds: int = 8) -> None:
        self.logger = logger
        self.popup_enabled = popup_enabled
        self.popup_timeout_seconds = max(1, int(popup_timeout_seconds))

    def info(self, message: str, *args) -> None:
        self.logger.info(message, *args)

    def warning(self, message: str, *args) -> None:
        self.logger.warning(message, *args)

    def error(self, message: str, *args) -> None:
        self.logger.error(message, *args)

    def popup(self, title: str, message: str, *, level: str = "info") -> None:
        if not self.popup_enabled:
            return
        try:
            if os.name == "nt":
                self._popup_windows(title, message, level)
                return
            if shutil.which("notify-send"):
                subprocess.Popen(
                    ["notify-send", title, message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
        except Exception as exc:
            self.logger.debug("popup failed: %s", exc)

    def _popup_windows(self, title: str, message: str, level: str) -> None:
        icon_map = {
            "info": 64,
            "warning": 48,
            "error": 16,
        }
        icon_code = icon_map.get(level, 64)
        ps_title = title.replace("'", "''")
        ps_message = message.replace("'", "''")
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"[void]$ws.Popup('{ps_message}', {self.popup_timeout_seconds}, '{ps_title}', {icon_code})"
        )
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

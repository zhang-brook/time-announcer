"""系统托盘图标（可选能力，依赖 pystray + Pillow）。"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray

from .icon import draw


class TrayIcon:
    """托盘图标：双击或菜单可打开主窗口，菜单可退出。"""

    def __init__(self, on_open: Callable[[], None], on_quit: Callable[[], None], title: str = "北京时间播报器"):
        self._on_open = on_open
        self._on_quit = on_quit
        self._icon: Optional[pystray.Icon] = pystray.Icon(
            "TimeAnnouncer",
            draw(64),
            title,
            menu=pystray.Menu(
                pystray.MenuItem("打开主窗口", self._open, default=True),
                pystray.MenuItem("退出", self._quit),
            ),
        )
        self._thread: Optional[threading.Thread] = None

    def _open(self, *_args) -> None:
        self._on_open()

    def _quit(self, *_args) -> None:
        self._on_quit()

    def start(self) -> None:
        if self._icon is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._icon.run, name="tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self._icon = None
        self._thread = None

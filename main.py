"""北京时间播报器 —— 程序入口。

用法：
    python main.py              显示主窗口
    python main.py --minimized  启动后最小化到系统托盘
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, timeutil  # noqa: E402
from core.announcer import Announcer  # noqa: E402
from core.scheduler import Scheduler  # noqa: E402
from core.ui import create  # noqa: E402


def ensure_single_instance() -> bool:
    """保证只运行一个实例（返回 False 表示已有实例在运行）。"""
    try:
        import win32api
        import win32event
        import winerror
    except ImportError:
        return True

    handle = win32event.CreateMutex(None, False, "Global\\TimeAnnouncer_SingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return False
    # 持有句柄，进程退出前互斥体一直有效
    globals()["_instance_mutex"] = handle
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="北京时间整点播报器")
    parser.add_argument("--minimized", action="store_true", help="启动后最小化到系统托盘")
    args = parser.parse_args()

    if not ensure_single_instance():
        print("程序已在运行中。")
        return 0

    cfg = config.load()
    announcer = Announcer()
    scheduler = Scheduler(lambda: cfg, announcer)

    # 后台校时，避免系统时钟不准导致报时偏差
    threading.Thread(target=timeutil.refresh_offset, name="ntp", daemon=True).start()

    app = create(cfg, announcer, scheduler, start_minimized=args.minimized or cfg.get("start_minimized", False))
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

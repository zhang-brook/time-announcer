"""开机自启：通过 HKCU 注册表 Run 项实现（无需管理员权限）。"""

from __future__ import annotations

import os
import sys
from typing import Optional

import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TimeAnnouncer"


def _pythonw() -> str:
    """优先使用无控制台的 pythonw.exe，避免开机弹黑窗。"""
    exe = sys.executable
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidate if os.path.exists(candidate) else exe


def launch_command() -> str:
    """生成自启命令行（指向 main.py）。"""
    script = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"))
    return f'"{_pythonw()}" "{script}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def enable() -> bool:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        return True
    except OSError:
        return False


def disable() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()


def current_command() -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except OSError:
        return None

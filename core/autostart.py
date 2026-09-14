"""开机自启：通过 HKCU 注册表 Run 项实现（无需管理员权限）。"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional, Tuple

import winreg

# 计算机\HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TimeAnnouncer"

logger = logging.getLogger(__name__)


def _pythonw() -> str:
    """优先使用无控制台的 pythonw.exe，避免开机弹黑窗。"""
    exe = sys.executable
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidate if os.path.exists(candidate) else exe


def launch_command() -> str:
    """生成自启命令行：打包环境只指向 exe，源码环境指向 pythonw + main.py。"""
    # exe
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    # 源码运行
    script = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"))
    return f'"{_pythonw()}" "{script}"'


def is_enabled() -> bool:
    """只判断启动项是否存在；指向是否正确由启动时的检查处理。"""
    return bool(current_command())


def enable() -> Tuple[bool, Optional[str]]:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        return True, None
    except OSError as exc:
        msg = f"无法写入注册表: {exc}"
        logger.warning(msg)
        return False, msg


def disable() -> Tuple[bool, Optional[str]]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True, None
    except OSError as exc:
        msg = f"无法删除注册表项: {exc}"
        logger.warning(msg)
        return False, msg


def set_enabled(enabled: bool) -> Tuple[bool, Optional[str]]:
    return enable() if enabled else disable()


def current_command() -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except OSError:
        return None

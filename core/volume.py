"""系统主音量 / 静音状态读写（Windows Core Audio API）。"""

from __future__ import annotations

from typing import Optional, Tuple

try:
    from pycaw.pycaw import AudioUtilities
except Exception:  # pragma: no cover - 缺少依赖时降级为无操作
    AudioUtilities = None  # type: ignore


class VolumeUnavailable(Exception):
    """音频设备不可用或依赖缺失。"""


def _endpoint():
    """获取默认播放设备的音量接口。"""
    if AudioUtilities is None:
        raise VolumeUnavailable("未安装 pycaw，无法控制系统音量")
    try:
        import comtypes  # noqa: F401  comtypes 需要在 COM 调用前可用
        import pythoncom

        pythoncom.CoInitialize()
        device = AudioUtilities.GetSpeakers()
        if device is None:
            raise VolumeUnavailable("未找到默认播放设备")
        return device.EndpointVolume
    except VolumeUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VolumeUnavailable(str(exc)) from exc


def get_state() -> Tuple[Optional[int], Optional[bool]]:
    """返回 (音量百分比 0~100, 是否静音)；获取失败返回 (None, None)。"""
    try:
        ep = _endpoint()
        level = int(round(ep.GetMasterVolumeLevelScalar() * 100))
        muted = bool(ep.GetMute())
        return max(0, min(100, level)), muted
    except Exception:  # noqa: BLE001
        return None, None


def set_volume(percent: int) -> bool:
    """设置主音量百分比。"""
    try:
        ep = _endpoint()
        ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, percent / 100.0)), None)
        return True
    except Exception:  # noqa: BLE001
        return False


def set_mute(muted: bool) -> bool:
    """设置静音状态。"""
    try:
        ep = _endpoint()
        ep.SetMute(1 if muted else 0, None)
        return True
    except Exception:  # noqa: BLE001
        return False

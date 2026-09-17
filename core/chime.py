"""播报前的提示音：先滴一声再说话，避免突然出声吓人。"""

from __future__ import annotations

import winsound

# 优先用系统提示音（音色柔和）；系统未配置声音方案时退化为短促蜂鸣
_ALIASES = ("SystemNotification", "SystemAsterisk")
_BEEP_FREQ = 880
_BEEP_MS = 120

LEAD_SECONDS = 0.8   # 提示音与语音之间的间隔，留出「先听到提示」的时间


def play() -> None:
    """异步播放提示音；调用方需自行等待 LEAD_SECONDS 后再说话。"""
    for alias in _ALIASES:
        try:
            winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            return
        except RuntimeError:
            continue
    try:
        winsound.Beep(_BEEP_FREQ, _BEEP_MS)
    except Exception:  # noqa: BLE001 无音频设备时静默跳过
        pass

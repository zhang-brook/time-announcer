"""播报执行：把「文本 -> 语音」与「音量临时调高 / 还原」组合起来。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from . import volume
from .speaker import Speaker, pick_voice_name


class Announcer:
    """按配置播报一句话；必要时临时拉高系统音量并在结束后还原。"""

    def __init__(self, on_state: Optional[Callable[[str], None]] = None) -> None:
        self._speaker = Speaker()
        self._lock = threading.Lock()
        self._voice_name: Optional[str] = None
        self._voice_cfg_name: Optional[str] = None
        self._speaking = False
        self.on_state = on_state or (lambda _msg: None)

    @property
    def is_speaking(self) -> bool:
        """当前是否有播报正在进行（供界面决定「停止」是否可用）。"""
        with self._lock:
            return self._speaking

    def cancel(self) -> None:
        self._speaker.cancel()

    def _resolve_voice(self, cfg_name: str) -> str:
        if self._voice_name is None or self._voice_cfg_name != cfg_name:
            self._voice_name = pick_voice_name(cfg_name)
            self._voice_cfg_name = cfg_name
        return self._voice_name

    def announce(self, text: str, cfg: Dict[str, Any]) -> bool:
        if not text:
            return False
        voice_cfg = cfg.get("voice", {})
        audio_cfg = cfg.get("audio", {})

        snapshot = None
        if audio_cfg.get("boost_enabled", True):
            snapshot = self._boost_volume(int(audio_cfg.get("boost_volume", 60)))

        with self._lock:
            self._speaking = True
        try:
            self.on_state(f"播报中：{text}")
            ok = self._speaker.speak(
                text,
                self._resolve_voice(voice_cfg.get("name", "")),
                int(voice_cfg.get("rate", 0)),
                int(voice_cfg.get("volume", 100)),
            )
            return ok
        finally:
            with self._lock:
                self._speaking = False
            if snapshot is not None and audio_cfg.get("restore_after", True):
                level, muted = snapshot
                volume.set_volume(level)
                volume.set_mute(muted)
            self.on_state("待机")

    @staticmethod
    def _boost_volume(target: int):
        """若静音或音量低于目标值，则临时调高；返回需要还原的 (音量, 静音)。"""
        level, muted = volume.get_state()
        if level is None:
            return None
        if muted or level < target:
            volume.set_mute(False)
            volume.set_volume(target)
            return level, muted
        return None

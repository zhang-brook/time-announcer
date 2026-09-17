"""播报执行：把「音量临时调高 / 还原」「提示音」与「文本 -> 语音」组合起来。"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from . import chime, volume
from .speaker import Speaker, pick_voice_name


class Announcer:
    """按配置播报一句话；必要时临时拉高系统音量并在结束后还原。"""

    def __init__(self, on_state: Optional[Callable[[str], None]] = None) -> None:
        self._speaker = Speaker()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
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
        self._cancel.set()
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
        self._cancel.clear()

        snapshot = None
        if audio_cfg.get("boost_enabled", True):
            snapshot = self._boost_volume(int(audio_cfg.get("boost_volume", 60)))

        with self._lock:
            self._speaking = True
        try:
            self.on_state(f"播报中：{text}")
            if audio_cfg.get("chime_enabled", True):
                # 先响提示音再说话：音量已经调高，提示音才能被听到
                chime.play()
                if not self._wait(chime.LEAD_SECONDS):
                    return False
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

    def _wait(self, seconds: float) -> bool:
        """等待提示音播放；期间被取消则返回 False（不再说话）。"""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                return False
            time.sleep(0.05)
        return not self._cancel.is_set()

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

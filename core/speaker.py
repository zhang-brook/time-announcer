"""SAPI 语音合成封装：语音枚举与文本播报。"""

from __future__ import annotations

import threading
from typing import List, Optional

import pythoncom
import win32com.client

SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2

# 中文语音的优先匹配关键字
_CN_HINTS = ("chinese", "huihui", "yaoyao", "kangkang", "xiaoxiao", "yunyang", "中文")


def list_voices() -> List[str]:
    """返回系统已安装语音的描述列表。"""
    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voices = voice.GetVoices()
        return [voices.Item(i).GetDescription() for i in range(voices.Count)]
    except Exception:  # noqa: BLE001
        return []
    finally:
        pythoncom.CoUninitialize()


def pick_voice_name(preferred: str = "") -> str:
    """挑选语音名称：优先用户指定，其次自动选择中文语音。"""
    names = list_voices()
    if not names:
        return ""
    if preferred and preferred in names:
        return preferred
    for name in names:
        low = name.lower()
        if any(hint in low for hint in _CN_HINTS):
            return name
    return names[0]


class Speaker:
    """线程安全的播报器；每次播报独立初始化 COM，避免跨线程复用 COM 对象。"""

    def __init__(self) -> None:
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """请求停止当前播报。"""
        self._cancel.set()

    def speak(
        self,
        text: str,
        voice_name: str = "",
        rate: int = 0,
        volume: int = 100,
    ) -> bool:
        """同步播报文本（阻塞直到读完或被取消）。"""
        if not text:
            return False
        self._cancel.clear()
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            try:
                if voice_name:
                    token = self._find_token(voice, voice_name)
                    if token is not None:
                        voice.Voice = token
                voice.Rate = max(-10, min(10, int(rate)))
                voice.Volume = max(0, min(100, int(volume)))
                voice.Speak(text, SVSF_ASYNC)
                while True:
                    if self._cancel.is_set():
                        voice.Speak("", SVSF_PURGE_BEFORE_SPEAK)
                        return False
                    if voice.WaitUntilDone(200):
                        return True
            finally:
                del voice
        except Exception:  # noqa: BLE001
            return False
        finally:
            pythoncom.CoUninitialize()

    @staticmethod
    def _find_token(voice, name: str) -> Optional[object]:
        voices = voice.GetVoices()
        for i in range(voices.Count):
            token = voices.Item(i)
            if token.GetDescription() == name:
                return token
        return None

"""播报前的提示音：自行合成的柔和双音，先"叮"一声再说话。"""

from __future__ import annotations

import array
import math
import os
import sys
import wave
from typing import Optional

import winsound

from .icon import resource_root

WAV_FILE = "chime.wav"
LEAD_SECONDS = 0.8      # 提示音与语音的间隔：提示音将尽时开口，衔接自然

_RATE = 44100
_DURATION = 0.72
_ATTACK = 0.006         # 起音淡入，避免爆音
_FADE_OUT = 0.05        # 收尾淡出，避免截断的咔哒声
_PEAK = 0.6             # 归一化峰值，留足余量
# (起始秒, 频率 Hz, 衰减时间常数, 相对音量)：木琴般上行的两声「叮-咚」
_TONES = (
    (0.00, 783.99, 0.10, 0.85),      # G5
    (0.18, 1046.50, 0.22, 1.00),     # C6
)
# (倍频, 相对幅度)：少量泛音让音色通透，又不至于尖锐
_HARMONICS = ((1.0, 1.0), (2.0, 0.22), (3.0, 0.07))

_cached_path: Optional[str] = None


def _envelope(u: float, tau: float) -> float:
    if u >= _DURATION:
        return 0.0
    env = min(1.0, u / _ATTACK) * math.exp(-u / tau)
    remain = _DURATION - u
    return env * min(1.0, remain / _FADE_OUT)


def _render() -> array.array:
    """合成并归一化 16bit 单声道采样。"""
    total = int(_RATE * _DURATION)
    raw = [0.0] * total
    for i in range(total):
        t = i / _RATE
        sample = 0.0
        for start, freq, tau, gain in _TONES:
            u = t - start
            if u < 0:
                continue
            env = _envelope(u, tau)
            if not env:
                continue
            sample += gain * env * sum(amp * math.sin(2 * math.pi * freq * mult * u)
                                       for mult, amp in _HARMONICS)
        raw[i] = sample

    peak = max(abs(value) for value in raw) or 1.0
    scale = _PEAK * 32767 / peak
    return array.array("h", (int(value * scale) for value in raw))


def target_path() -> str:
    """源码目录下的 assets/chime.wav（打包后不用于写入）。"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", WAV_FILE)


def generate(path: Optional[str] = None) -> str:
    """合成提示音并写入 wav，返回文件路径。"""
    target = path or target_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with wave.open(target, "wb") as fp:
        fp.setnchannels(1)
        fp.setsampwidth(2)
        fp.setframerate(_RATE)
        fp.writeframes(_render().tobytes())
    return target


def wav_path() -> Optional[str]:
    """返回可用的提示音文件；源码运行时缺失则现场生成。"""
    path = os.path.join(resource_root(), "assets", WAV_FILE)
    if os.path.exists(path):
        return path
    if getattr(sys, "frozen", False):
        return None
    try:
        return generate(target_path())
    except OSError:
        return None


def play() -> None:
    """异步播放提示音；调用方需自行等待 LEAD_SECONDS 后再说话。"""
    global _cached_path
    if _cached_path is None:
        _cached_path = wav_path() or ""
    if _cached_path:
        try:
            winsound.PlaySound(
                _cached_path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        except RuntimeError:
            _cached_path = ""
    try:
        winsound.Beep(880, 120)
    except Exception:  # noqa: BLE001 无音频设备时静默跳过
        pass


if __name__ == "__main__":
    print(generate())

"""时间工具：强制按北京时间（Asia/Shanghai）计算，并支持可选的 NTP 校时。"""

from __future__ import annotations

import socket
import struct
import time
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

# SNTP 服务器与本地时钟的偏差（秒），由 refresh_offset() 更新
_offset = 0.0
_offset_at = 0.0
_OFFSET_TTL = 1800  # 偏差缓存 30 分钟

NTP_SERVERS = ("ntp.aliyun.com", "time.windows.com", "pool.ntp.org")


def now() -> datetime:
    """当前北京时间（带 NTP 偏差修正）。"""
    return datetime.fromtimestamp(time.time() + _offset, CN_TZ)


def offset() -> float:
    return _offset


def refresh_offset(timeout: float = 2.0) -> float:
    """通过 SNTP 获取本机时钟偏差；失败时保持上一次结果（默认 0）。"""
    global _offset, _offset_at
    for host in NTP_SERVERS:
        try:
            client = time.time()
            data = b"\x1b" + 47 * b"\0"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                sock.sendto(data, (host, 123))
                raw, _ = sock.recvfrom(48)
            server = time.time()
            if len(raw) < 48:
                continue
            seconds = struct.unpack("!12I", raw)[10]          # 传输时间戳
            ntp_time = seconds - 2208988800                   # 1900 -> 1970
            _offset = ntp_time - (client + server) / 2
            _offset_at = server
            return _offset
        except (OSError, struct.error):
            continue
    return _offset


def offset_text() -> str:
    """人类可读的时钟偏差描述。"""
    if _offset_at == 0.0:
        return "未校时"
    return f"{_offset:+.2f} 秒"


_CN_DIGITS = "零一二三四五六七八九"


def to_cn_number(n: int) -> str:
    """把 0~99 的数字转成中文读法：0->零，10->十，13->十三，30->三十。"""
    n = int(n)
    if n < 0 or n > 99:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n - 10] if n > 10 else "")
    tens, ones = divmod(n, 10)
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


def cn_hour_minute(dt: datetime) -> tuple[str, str]:
    """返回时、分的中文读法。"""
    return to_cn_number(dt.hour), to_cn_number(dt.minute)

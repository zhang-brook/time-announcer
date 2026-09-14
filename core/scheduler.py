"""定时调度：整点报时、整点+半点、自定义时刻、番茄钟。"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import timeutil
from .config import MODE_CUSTOM, MODE_HOURLY, MODE_HOURLY_HALF

CATCHUP_SECONDS = 90       # 允许迟到的秒数：期间内仍补播一次
POLL_SECONDS = 1.0         # 轮询间隔

KIND_TIME = "time"
KIND_POMODORO = "pomodoro"


@dataclass
class Event:
    key: str
    kind: str
    text: str
    at: datetime


def parse_hhmm(value: str) -> Optional[Tuple[int, int]]:
    """解析 "HH:MM"，非法输入返回 None。"""
    match = re.fullmatch(r"\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*", str(value))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _in_hour_range(hour: int, start: int, end: int) -> bool:
    """判断小时是否落在（可跨夜的）生效区间内。"""
    start, end = int(start) % 24, int(end) % 24
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def time_text(cfg: Dict[str, Any], dt: datetime) -> str:
    """按配置模板渲染报时文本。"""
    text_cfg = cfg.get("text", {})
    hour_cn, minute_cn = timeutil.cn_hour_minute(dt)
    template = text_cfg.get("on_hour", "") if dt.minute == 0 else text_cfg.get("on_minute", "")
    text = template.format(h=hour_cn, m=minute_cn, H=f"{dt.hour:02d}", M=f"{dt.minute:02d}")
    suffix = (text_cfg.get("suffix") or "").strip()
    return f"{text}。{suffix}" if suffix else text


class Scheduler:
    """后台调度线程：按配置计算到期事件并交给播报器。"""

    def __init__(
        self,
        cfg_getter: Callable[[], Dict[str, Any]],
        announcer,
        on_event: Optional[Callable[[Event, str], None]] = None,
    ) -> None:
        self._cfg_getter = cfg_getter
        self._announcer = announcer
        self.on_event = on_event or (lambda event, text: None)

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fired: Dict[str, float] = {}
        self._pomo: Optional[Dict[str, Any]] = None
        self._pomo_signature: Optional[Tuple] = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._announcer.cancel()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def reload(self) -> None:
        """配置变更后立即重新计算（唤醒等待中的线程）。"""
        self._wake.set()

    # ---------- 主循环 ----------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 调度线程不应因异常退出
                pass
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()

    def _tick(self) -> None:
        cfg = self._cfg_getter()
        now = timeutil.now()
        self._prune(now)

        # 全局总开关：关闭后报时与番茄钟一律不触发
        if not cfg.get("master_enabled", True):
            return

        # 报时开关只控制报时；番茄钟由自己的开关控制，互不牵连
        event = self._due_time_event(now, cfg) if cfg.get("enabled", True) else None
        if event is None:
            event = self._due_pomodoro_event(now, cfg)
        if event is None:
            return

        self._fired[event.key] = now.timestamp()
        self.on_event(event, event.text)
        self._announcer.announce(event.text, cfg)
        self.on_event(event, "")

    def _prune(self, now: datetime) -> None:
        for key, ts in list(self._fired.items()):
            if now.timestamp() - ts > 3600:
                self._fired.pop(key, None)

    # ---------- 报时事件 ----------

    def _due_time_event(self, now: datetime, cfg: Dict[str, Any]) -> Optional[Event]:
        for moment in self._candidate_moments(now, cfg):
            delta = (now - moment).total_seconds()
            if 0 <= delta <= CATCHUP_SECONDS:
                key = f"time|{moment:%Y-%m-%d %H:%M}"
                if key in self._fired:
                    continue
                return Event(key=key, kind=KIND_TIME, text=time_text(cfg, moment), at=moment)
        return None

    def _candidate_moments(self, now: datetime, cfg: Dict[str, Any], day_offsets=(-1, 0)) -> List[datetime]:
        """生成计划时刻。

        day_offsets 为相对今天的日期偏移：判定是否到期时比对昨天+今天（覆盖跨零点补播），
        计算下一次时间时用今天+明天。
        """
        mode = cfg.get("mode", MODE_HOURLY)
        moments: List[datetime] = []

        for offset in day_offsets:
            base = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            if mode == MODE_CUSTOM:
                for raw in cfg.get("custom_times", []):
                    parsed = parse_hhmm(raw)
                    if parsed:
                        moments.append(base + timedelta(hours=parsed[0], minutes=parsed[1]))
            else:
                if cfg.get("hour_all_day", False):
                    hours = list(range(24))
                else:
                    hours = [h for h in range(24) if _in_hour_range(h, cfg.get("hour_start", 0), cfg.get("hour_end", 23))]
                for hour in hours:
                    moments.append(base + timedelta(hours=hour))
                    if mode == MODE_HOURLY_HALF:
                        moments.append(base + timedelta(hours=hour, minutes=30))
        return sorted(moments)

    # ---------- 番茄钟事件 ----------

    def _due_pomodoro_event(self, now: datetime, cfg: Dict[str, Any]) -> Optional[Event]:
        pomo = cfg.get("pomodoro", {})
        if not pomo.get("enabled", False):
            self._pomo = None
            self._pomo_signature = None
            return None

        signature = (
            int(pomo.get("work_minutes", 25)),
            int(pomo.get("break_minutes", 5)),
            int(pomo.get("rounds", 0)),
        )
        if self._pomo is None or self._pomo_signature != signature:
            self._pomo_signature = signature
            self._pomo = {
                "phase": "work",
                "deadline": now + timedelta(minutes=signature[0]),
                "round": 1,
            }
            return None

        state = self._pomo
        if state["phase"] == "done" or now < state["deadline"]:
            return None

        text_cfg = cfg.get("text", {})
        if state["phase"] == "work":
            event = Event(
                key=f"pomo|break|{now:%Y-%m-%d %H:%M}",
                kind=KIND_POMODORO,
                text=text_cfg.get("pomodoro_break", ""),
                at=now,
            )
            rounds = signature[2]
            if rounds > 0 and state["round"] >= rounds:
                state["phase"] = "done"
                state["deadline"] = None
            else:
                state["phase"] = "break"
                state["deadline"] = now + timedelta(minutes=signature[1])
        elif state["phase"] == "break":
            event = Event(
                key=f"pomo|work|{now:%Y-%m-%d %H:%M}",
                kind=KIND_POMODORO,
                text=text_cfg.get("pomodoro_work", ""),
                at=now,
            )
            state["phase"] = "work"
            state["round"] += 1
            state["deadline"] = now + timedelta(minutes=signature[0])
        else:
            return None

        if event.key in self._fired:
            return None
        return event

    def pomodoro_deadline(self) -> Optional[datetime]:
        if not self._pomo or self._pomo.get("phase") == "done":
            return None
        return self._pomo["deadline"]

    # ---------- 供界面展示 ----------

    def next_event(self) -> Optional[Tuple[datetime, str]]:
        """返回下一次触发的 (时间, 说明)。"""
        cfg = self._cfg_getter()
        now = timeutil.now()
        candidates: List[Tuple[datetime, str]] = []

        if not cfg.get("master_enabled", True):
            return None

        if cfg.get("enabled", True):
            for moment in self._candidate_moments(now, cfg, day_offsets=(0, 1)):
                if moment <= now:
                    continue
                if moment.minute == 0:
                    kind = "整点报时"
                else:
                    kind = "定点报时"
                if moment.date() != now.date():
                    kind = "明日" + kind
                candidates.append((moment, kind))

        pomo = cfg.get("pomodoro", {})
        deadline = self.pomodoro_deadline()
        if pomo.get("enabled", False) and deadline and deadline > now:
            phase = self._pomo.get("phase") if self._pomo else "work"
            label = "番茄钟·专注结束" if phase == "work" else "番茄钟·休息结束"
            candidates.append((deadline, label))

        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])

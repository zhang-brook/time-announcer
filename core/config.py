"""配置读写。

配置以单个 JSON 文件保存在 ``%APPDATA%\\TimeAnnouncer\\config.json``，
不引入数据库；读取时用默认值补全缺失字段，保证版本升级后旧配置仍可用。
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any, Dict

from . import APP_NAME

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

_lock = threading.Lock()

MODE_HOURLY = "hourly"              # 整点报时
MODE_HOURLY_HALF = "hourly_half"    # 整点 + 半点报时
MODE_CUSTOM = "custom"              # 自定义时刻

DEFAULT_CONFIG: Dict[str, Any] = {
    "master_enabled": True,         # 全局总开关：关闭后报时与番茄钟都不提醒
    "enabled": True,                # 报时开关：关闭后不报时（不影响番茄钟）

    "mode": MODE_HOURLY,
    "hour_start": 8,                # 整点报时生效小时（含）
    "hour_end": 22,                 # 整点报时生效小时（含）
    "hour_all_day": False,          # 为 True 时不限时段时间，全天整点/半点均播报
    "custom_times": ["09:00", "12:00", "18:00"],

    "pomodoro": {
        "enabled": False,
        "work_minutes": 25,
        "break_minutes": 5,
        "rounds": 4,                # 0 表示无限循环
    },

    "voice": {
        "name": "",                 # 留空 = 自动挑选中文语音
        "rate": 0,                  # SAPI 语速，范围 -10 ~ 10
        "volume": 100,              # TTS 自身音量 0 ~ 100
    },

    "text": {
        "on_hour": "北京时间{h}点整",
        "on_minute": "北京时间{h}点{m}分",
        "pomodoro_work": "专注开始，请集中注意力",
        "pomodoro_break": "休息时间到，起来活动一下",
        "suffix": "",               # 附加在每句后面的自定义提醒
    },

    "audio": {
        "boost_enabled": True,      # 静音 / 音量过低时临时调高
        "boost_volume": 60,         # 调高到的系统主音量 0 ~ 100
        "restore_after": True,      # 播报结束后还原原音量与静音状态
        "chime_enabled": True,      # 播报前先播放提示音，避免突然出声
    },

    "autostart": False,
    "minimize_to_tray": True,
}


def _merge(defaults: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    """用默认值补全用户配置（只补全缺失项，保留用户已有的值）。"""
    result = deepcopy(defaults)
    for key, value in (user or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        elif key in result:
            result[key] = value
    return result


def load() -> Dict[str, Any]:
    """读取配置；文件不存在或损坏时回退到默认配置。"""
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            return deepcopy(DEFAULT_CONFIG)
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                user_cfg = json.load(fp)
        except (OSError, ValueError):
            return deepcopy(DEFAULT_CONFIG)
        return _merge(DEFAULT_CONFIG, user_cfg)


def save(cfg: Dict[str, Any]) -> None:
    """写入配置（原子写：先写临时文件再替换）。"""
    with _lock:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_PATH)


def config_path() -> str:
    return CONFIG_PATH

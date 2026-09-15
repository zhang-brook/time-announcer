"""图形界面（tkinter）。所有改动即时写入配置文件并重新加载调度。"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from . import autostart, config, timeutil, volume
from . import APP_NAME, APP_REPO_URL, APP_TITLE, APP_VERSION
from .config import MODE_CUSTOM, MODE_HOURLY, MODE_HOURLY_HALF
from .icon import icon_path
from .scheduler import parse_hhmm, time_text

try:  # 托盘为可选能力，缺失时自动降级
    from .tray import TrayIcon
except Exception:  # noqa: BLE001
    TrayIcon = None  # type: ignore

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
FONT_NORMAL = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_CLOCK = ("Microsoft YaHei UI", 26, "bold")


class _ScrollPage(ttk.Frame):
    """标签页容器：内容高于可视区域时才出现滚动条，窗口变矮也不会裁掉内容。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=background)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._sync_bar)

        self.body = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)

    def _sync_bar(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vbar.pack_forget()
        elif not self.vbar.winfo_ismapped():
            self.vbar.pack(side="right", fill="y")
        self.vbar.set(first, last)

    def _sync_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event) -> None:
        # 只做纵向滚动，内容宽度始终跟随窗口
        self.canvas.itemconfigure(self._window, width=event.width)

    def owns(self, widget) -> bool:
        """判断控件是否属于本页，用于把滚轮事件路由到正确的标签页。"""
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def scroll(self, delta: int) -> None:
        self.canvas.yview_scroll(-3 if delta > 0 else 3, "units")


class App(tk.Tk):
    def __init__(self, cfg: Dict[str, Any], announcer, scheduler, start_minimized: bool = False):
        super().__init__()
        # 必须在根窗口创建之后再设置主题，否则 tkinter 会隐式创建一个
        # 标题为 "tk" 的空白根窗口
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Master.TCheckbutton", font=FONT_BOLD)
        self.cfg = cfg
        self.announcer = announcer
        self.scheduler = scheduler
        self._loading = True
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._tray = None

        self.title(f"{config.APP_NAME} · 整点北京时间播报")
        self.geometry("780x700")
        self.minsize(680, 520)
        self._apply_icon()

        self._init_vars()
        self._build_header()
        # 底部条先占位：窗口再矮也始终贴在底部，不会被标签页内容挤掉
        self._build_bottom_bar()
        self._build_log()
        self._build_tabs()
        self.bind("<MouseWheel>", self._on_wheel)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._loading = False

        self.scheduler.on_event = self.handle_event
        self.scheduler.start()

        self._tick_clock()
        self._drain_log()
        if start_minimized:
            # 托盘不可用时降级为正常显示，避免程序隐藏后无法找回
            if self._ensure_tray():
                self.withdraw()
            else:
                self.deiconify()

        # 等主窗口显示后再检查启动项，避免弹窗出现在窗口之前
        self.after(300, self._check_autostart)

    def _apply_icon(self) -> None:
        """标题栏/任务栏图标与托盘、exe 共用同一份 assets/app.ico。"""
        path = icon_path()
        if not path:
            return
        try:
            self.iconbitmap(path)
        except tk.TclError:
            pass

    # ---------------- 变量与配置同步 ----------------

    def _init_vars(self) -> None:
        cfg = self.cfg
        self.v_master = tk.BooleanVar(value=cfg.get("master_enabled", True))
        self.v_enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        self.v_mode = tk.StringVar(value=cfg.get("mode", MODE_HOURLY))
        self.v_hour_start = tk.IntVar(value=cfg.get("hour_start", 8))
        self.v_hour_end = tk.IntVar(value=cfg.get("hour_end", 22))
        self.v_hour_all_day = tk.BooleanVar(value=cfg.get("hour_all_day", False))

        pomo = cfg.get("pomodoro", {})
        self.v_pomo_enabled = tk.BooleanVar(value=pomo.get("enabled", False))
        self.v_work = tk.IntVar(value=pomo.get("work_minutes", 25))
        self.v_break = tk.IntVar(value=pomo.get("break_minutes", 5))
        self.v_rounds = tk.IntVar(value=pomo.get("rounds", 4))

        voice = cfg.get("voice", {})
        self.v_voice = tk.StringVar(value=voice.get("name", ""))
        self.v_rate = tk.IntVar(value=voice.get("rate", 0))
        self.v_volume = tk.IntVar(value=voice.get("volume", 100))

        audio = cfg.get("audio", {})
        self.v_boost = tk.BooleanVar(value=audio.get("boost_enabled", True))
        self.v_boost_volume = tk.IntVar(value=audio.get("boost_volume", 60))
        self.v_restore = tk.BooleanVar(value=audio.get("restore_after", True))

        text = cfg.get("text", {})
        self.v_on_hour = tk.StringVar(value=text.get("on_hour", ""))
        self.v_on_minute = tk.StringVar(value=text.get("on_minute", ""))
        self.v_pomo_work = tk.StringVar(value=text.get("pomodoro_work", ""))
        self.v_pomo_break = tk.StringVar(value=text.get("pomodoro_break", ""))
        self.v_suffix = tk.StringVar(value=text.get("suffix", ""))
        self.v_test_text = tk.StringVar(value="北京时间播报测试")

        self.v_autostart = tk.BooleanVar(value=autostart.is_enabled())
        # 是否最小化直接以注册表内容为准，不写入配置文件
        self.v_start_min = tk.BooleanVar(value=autostart.is_minimized())
        self.v_tray = tk.BooleanVar(value=cfg.get("minimize_to_tray", True))
        # 纯界面状态：日志区默认收起，不写入配置文件
        self.v_show_log = tk.BooleanVar(value=False)

        for var in self._all_vars():
            var.trace_add("write", self.on_change)

    def _all_vars(self) -> List[tk.Variable]:
        return [
            self.v_master,
            self.v_enabled, self.v_mode, self.v_hour_start, self.v_hour_end, self.v_hour_all_day,
            self.v_pomo_enabled, self.v_work, self.v_break, self.v_rounds,
            self.v_voice, self.v_rate, self.v_volume,
            self.v_boost, self.v_boost_volume, self.v_restore,
            self.v_on_hour, self.v_on_minute, self.v_pomo_work, self.v_pomo_break, self.v_suffix,
            self.v_tray,
        ]

    def on_change(self, *_args) -> None:
        if self._loading:
            return
        self.apply()

    def apply(self) -> None:
        """把界面上的设置写回配置、落盘并重新加载调度。"""
        self.collect()
        config.save(self.cfg)
        self.scheduler.reload()
        self.refresh_controls()

    def collect(self) -> None:
        cfg = self.cfg
        cfg["master_enabled"] = bool(self.v_master.get())
        cfg["enabled"] = bool(self.v_enabled.get())
        cfg["mode"] = self.v_mode.get()
        cfg["hour_start"] = self._clamp(self.v_hour_start, 0, 23)
        cfg["hour_end"] = self._clamp(self.v_hour_end, 0, 23)
        cfg["hour_all_day"] = bool(self.v_hour_all_day.get())

        times: List[str] = []
        for line in self.custom_box.get("1.0", "end").splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = parse_hhmm(line)
            times.append(f"{parsed[0]:02d}:{parsed[1]:02d}" if parsed else line)
        cfg["custom_times"] = times

        cfg["pomodoro"] = {
            "enabled": bool(self.v_pomo_enabled.get()),
            "work_minutes": self._clamp(self.v_work, 1, 600),
            "break_minutes": self._clamp(self.v_break, 1, 120),
            "rounds": self._clamp(self.v_rounds, 0, 99),
        }
        cfg["voice"] = {
            "name": self.v_voice.get(),
            "rate": self._clamp(self.v_rate, -10, 10),
            "volume": self._clamp(self.v_volume, 0, 100),
        }
        cfg["audio"] = {
            "boost_enabled": bool(self.v_boost.get()),
            "boost_volume": self._clamp(self.v_boost_volume, 1, 100),
            "restore_after": bool(self.v_restore.get()),
        }
        cfg["text"] = {
            "on_hour": self.v_on_hour.get(),
            "on_minute": self.v_on_minute.get(),
            "pomodoro_work": self.v_pomo_work.get(),
            "pomodoro_break": self.v_pomo_break.get(),
            "suffix": self.v_suffix.get(),
        }
        cfg["minimize_to_tray"] = bool(self.v_tray.get())

    @staticmethod
    def _clamp(var: tk.Variable, low: int, high: int) -> int:
        try:
            value = int(var.get())
        except (TypeError, ValueError):
            return low
        return max(low, min(high, value))

    # ---------------- 界面构建 ----------------

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(16, 12, 16, 6))
        header.pack(fill="x")

        self.clock_label = ttk.Label(header, text="--:--:--", font=FONT_CLOCK)
        self.clock_label.grid(row=0, column=0, rowspan=2, sticky="w")

        info = ttk.Frame(header)
        info.grid(row=0, column=1, rowspan=2, sticky="new", padx=(20, 0))
        # 信息列可伸缩：窗口变窄时文字自动换行，而不是把右侧操作区挤没
        header.columnconfigure(1, weight=1)
        self.date_label = ttk.Label(info, text="", font=FONT_NORMAL, justify="left", wraplength=440)
        self.date_label.pack(anchor="w")
        self.next_label = ttk.Label(info, text="", font=FONT_NORMAL, justify="left", wraplength=440)
        self.next_label.pack(anchor="w", pady=(4, 0))
        self.state_label = ttk.Label(info, text="", font=FONT_NORMAL, foreground="#0078d4",
                                     justify="left", wraplength=440)
        self.state_label.pack(anchor="w")

        # 操作区纵向排两行，避免窗口不够宽时按钮和输入框被挤出可视范围
        actions = ttk.Frame(header)
        actions.grid(row=0, column=2, sticky="e")

        btns = ttk.Frame(actions)
        btns.pack(anchor="e")
        ttk.Button(btns, text="立即播报", command=self.speak_now).pack(fill="x")
        # 仅在播报进行中可用，其余时间置灰
        self.stop_button = ttk.Button(btns, text="停止", command=self.stop_speaking, state="disabled")
        self.stop_button.pack(fill="x", pady=(6, 0))
        self._stop_enabled = False

        # 按实际需要给操作列保底宽度，保证窄窗口下按钮完整可见
        self.update_idletasks()
        header.columnconfigure(2, minsize=actions.winfo_reqwidth())

        # 时钟偏差与总开关并排一行，省下的纵向空间留给标签页内容
        self.offset_label = ttk.Label(header, text="", font=("Microsoft YaHei UI", 8), foreground="#888")
        self.offset_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

        # 全局总开关放在标题区，任何标签页下都能随手开关
        self.master_check = ttk.Checkbutton(
            header, text=self._master_text(),
            variable=self.v_master, style="Master.TCheckbutton",
        )
        self.master_check.grid(row=2, column=1, columnspan=2, sticky="w", padx=(16, 0), pady=(6, 0))

    def _master_text(self) -> str:
        """总开关文案随状态变化，关闭时说明影响范围。"""
        if self.v_master.get():
            return "全局提醒总开关（已开启）"
        return "全局提醒总开关（已关闭，整点报时与番茄钟均不提醒）"

    def _build_tabs(self) -> None:
        notebook = ttk.Notebook(self, padding=(12, 4))
        notebook.pack(fill="both", expand=True)

        self.tabs = []
        for builder, title in (
            (self._tab_time, "报时设置"),
            (self._tab_pomodoro, "番茄钟"),
            (self._tab_voice, "语音与音量"),
            (self._tab_text, "播报文案"),
            (self._tab_about, "关于"),
        ):
            # 每个页面套一层滚动容器：窗口变矮时靠滚动查看，而不是裁掉控件
            page = _ScrollPage(notebook)
            builder(page.body).pack(fill="both", expand=True)
            self.tabs.append(page)
            notebook.add(page, text=title)

    def _tab_time(self, notebook) -> ttk.Frame:
        frame = ttk.Frame(notebook, padding=12)
        ttk.Checkbutton(
            frame, text="启用定时播报（关闭后不再报时）",
            variable=self.v_enabled,
        ).pack(anchor="w")

        mode_box = ttk.LabelFrame(frame, text="报时模式", padding=10)
        mode_box.pack(fill="x", pady=(10, 0))

        for text, value in (
            ("整点报时（如 8:00、9:00）", MODE_HOURLY),
            ("整点 + 半点报时（如 8:00、8:30）", MODE_HOURLY_HALF),
            ("自定义时刻（每天固定几个时间点）", MODE_CUSTOM),
        ):
            ttk.Radiobutton(mode_box, text=text, value=value, variable=self.v_mode).pack(anchor="w", pady=2)

        # 时段设置板块：与下方的「自定义时刻」并列，仅整点/半点模式生效
        self.range_frame = ttk.LabelFrame(frame, text="时段设置（整点/半点模式生效）", padding=10)
        self.range_frame.pack(fill="x", pady=(10, 0))
        self.all_day_check = ttk.Checkbutton(
            self.range_frame, text="全天生效（不限制时段，0-23 点整点/半点均播报）",
            variable=self.v_hour_all_day,
        )
        self.all_day_check.pack(anchor="w")

        range_box = ttk.Frame(self.range_frame)
        range_box.pack(anchor="w", pady=(4, 0))
        ttk.Label(range_box, text="生效时段：").pack(side="left")
        ttk.Spinbox(range_box, from_=0, to=23, width=4, textvariable=self.v_hour_start,
                    format="%02.0f").pack(side="left")
        ttk.Label(range_box, text=" 点 至 ").pack(side="left")
        ttk.Spinbox(range_box, from_=0, to=23, width=4, textvariable=self.v_hour_end,
                    format="%02.0f").pack(side="left")
        ttk.Label(range_box, text=" 点（支持跨夜，如 22 至 2）").pack(side="left")
        self.range_hint = range_box

        custom_box = ttk.LabelFrame(frame, text="自定义时刻（每行一个，格式 HH:MM）", padding=10)
        custom_box.pack(fill="both", expand=True, pady=(10, 0))
        self.custom_box = tk.Text(custom_box, height=6, font=("Consolas", 11), undo=True)
        self.custom_box.pack(fill="both", expand=True)
        self.custom_box.insert("1.0", "\n".join(self.cfg.get("custom_times", [])))
        self.custom_box.bind("<FocusOut>", lambda _e: self.apply())
        self.custom_frame = custom_box
        return frame

    def _tab_pomodoro(self, notebook) -> ttk.Frame:
        frame = ttk.Frame(notebook, padding=12)
        ttk.Checkbutton(frame, text="启用番茄钟（与整点报时互不冲突）",
                        variable=self.v_pomo_enabled).pack(anchor="w")

        box = ttk.LabelFrame(frame, text="节奏设置", padding=10)
        box.pack(fill="x", pady=(10, 0))

        self._spin_row(box, "专注时长（分钟）", self.v_work, 1, 600, 0)
        self._spin_row(box, "休息时长（分钟）", self.v_break, 1, 120, 1)
        self._spin_row(box, "循环轮数（0 表示一直循环）", self.v_rounds, 0, 99, 2)

        ttk.Label(
            frame,
            text="说明：程序启动后即进入第一个专注周期，专注结束播报休息提示，休息结束播报下一轮专注提示。",
            foreground="#666", wraplength=550, justify="left",
        ).pack(anchor="w", pady=(12, 0))
        return frame

    @staticmethod
    def _spin_row(parent, label: str, var: tk.IntVar, low: int, high: int, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(parent, from_=low, to=high, width=6, textvariable=var).grid(row=row, column=1, sticky="w", padx=8)
        parent.columnconfigure(2, weight=1)

    def _tab_voice(self, notebook) -> ttk.Frame:
        frame = ttk.Frame(notebook, padding=12)

        box = ttk.LabelFrame(frame, text="语音", padding=10)
        box.pack(fill="x")
        ttk.Label(box, text="发音人：").grid(row=0, column=0, sticky="w")
        self.voice_combo = ttk.Combobox(box, textvariable=self.v_voice, width=32, state="readonly")
        self.voice_combo.grid(row=0, column=1, sticky="ew", padx=6)
        box.columnconfigure(1, weight=1)
        ttk.Button(box, text="刷新列表", command=self.refresh_voices).grid(row=0, column=2)
        self._scale_row(box, "语速", self.v_rate, -10, 10, 1)
        self._scale_row(box, "语音音量", self.v_volume, 0, 100, 2)

        ttk.Separator(box, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        test_row = ttk.Frame(box)
        test_row.grid(row=4, column=0, columnspan=3, sticky="ew")
        test_row.columnconfigure(1, weight=1)
        ttk.Label(test_row, text="试听文本：").grid(row=0, column=0, sticky="w")
        ttk.Entry(test_row, textvariable=self.v_test_text).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(test_row, text="试听", command=self.speak_test).grid(row=0, column=2)

        audio_box = ttk.LabelFrame(frame, text="系统音量处理（静音也能听见）", padding=10)
        audio_box.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(audio_box, text="静音或音量过低时自动调高系统音量",
                        variable=self.v_boost).grid(row=0, column=0, columnspan=2, sticky="w")
        self._scale_row(audio_box, "播报时音量", self.v_boost_volume, 1, 100, 1)
        ttk.Checkbutton(audio_box, text="播报结束后还原原音量与静音状态",
                        variable=self.v_restore).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.volume_label = ttk.Label(frame, text="", foreground="#666")
        self.volume_label.pack(anchor="w", pady=(10, 0))
        return frame

    def _tab_text(self, notebook) -> ttk.Frame:
        frame = ttk.Frame(notebook, padding=12)
        entries = (
            ("整点文案", self.v_on_hour, "可用占位符 {h} 时、{H} 两位数字时"),
            ("含分钟文案", self.v_on_minute, "可用占位符 {h} {m} 中文时分、{H} {M} 数字时分"),
            ("番茄钟·开始专注", self.v_pomo_work, ""),
            ("番茄钟·开始休息", self.v_pomo_break, ""),
            ("附加提醒（追加在每句之后）", self.v_suffix, "留空表示不追加，例如：该喝水了"),
        )
        for row, (label, var, hint) in enumerate(entries):
            ttk.Label(frame, text=label).grid(row=row * 2, column=0, sticky="w", pady=(8, 0))
            ttk.Entry(frame, textvariable=var, width=40).grid(row=row * 2, column=1, sticky="ew", padx=8, pady=(8, 0))
            if hint:
                ttk.Label(frame, text=hint, foreground="#888",
                          font=("Microsoft YaHei UI", 8)).grid(row=row * 2 + 1, column=1, sticky="w", padx=8)
        frame.columnconfigure(1, weight=1)
        return frame

    def _tab_about(self, notebook) -> ttk.Frame:
        frame = ttk.Frame(notebook, padding=16)

        ttk.Label(frame, text=f"{APP_TITLE}（{APP_NAME}）",
                  font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text=f"版本 {APP_VERSION}", font=FONT_NORMAL,
                  foreground="#666").pack(anchor="w", pady=(6, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=14)

        ttk.Label(frame, text="项目主页", font=FONT_BOLD).pack(anchor="w")
        link = ttk.Label(frame, text=APP_REPO_URL, foreground="#0066cc",
                         font=("Microsoft YaHei UI", 10, "underline"), cursor="hand2")
        link.pack(anchor="w", pady=(4, 0))
        link.bind("<Button-1>", lambda _e: self.open_repo())
        ttk.Button(frame, text="打开项目主页", command=self.open_repo).pack(anchor="w", pady=(10, 0))

        ttk.Label(
            frame,
            text="按北京时间整点（或自定义时刻）语音播报当前时间，支持番茄钟提醒、\n"
                 "系统音量自动补偿、开机自启与托盘常驻。",
            justify="left", foreground="#666",
        ).pack(anchor="w", pady=(16, 0))
        return frame

    def open_repo(self) -> None:
        try:
            webbrowser.open(APP_REPO_URL)
        except Exception as exc:  # noqa: BLE001
            self.log(f"打开项目主页失败：{exc}")
            messagebox.showerror("关于", f"无法打开浏览器。\n\n{APP_REPO_URL}")

    def _build_bottom_bar(self) -> None:
        """底部固定条：自启选项、日志开关与配置文件路径始终可见。"""
        bar = ttk.Frame(self, padding=(16, 6))
        bar.pack(side="bottom", fill="x")
        self.bottom_bar = bar

        options = ttk.Frame(bar)
        options.pack(fill="x")
        ttk.Checkbutton(options, text="开机自动启动", variable=self.v_autostart,
                        command=self.toggle_autostart).pack(side="left")
        self.start_min_check = ttk.Checkbutton(options, text="开机后最小化到托盘",
                                               variable=self.v_start_min,
                                               command=self.toggle_start_minimized)
        self.start_min_check.pack(side="left", padx=12)
        ttk.Checkbutton(options, text="关闭窗口时最小化到托盘", variable=self.v_tray).pack(side="left")
        ttk.Checkbutton(options, text="显示运行日志", variable=self.v_show_log,
                        command=self.toggle_log).pack(side="right")

        info = ttk.Frame(bar)
        info.pack(fill="x", pady=(4, 0))
        self.status_label = ttk.Label(info, text=f"配置文件：{config.config_path()}",
                                      foreground="#888", font=("Microsoft YaHei UI", 8))
        self.status_label.pack(side="left")
        ttk.Button(info, text="打开配置文件", command=self.open_config).pack(side="right")

    def _build_log(self) -> None:
        self.log_frame = ttk.LabelFrame(self, text="运行日志", padding=6)
        self.log_box = tk.Text(self.log_frame, height=6, font=("Consolas", 9), state="disabled")
        self.log_box.pack(fill="both", expand=True)
        if self.v_show_log.get():
            self._layout_log()

    def _layout_log(self) -> None:
        # 排在底部条之后打包，日志区正好落在底部条上方，不参与标签页的伸缩
        self.log_frame.pack(side="bottom", fill="x", after=self.bottom_bar, padx=16, pady=(0, 6))

    def toggle_log(self) -> None:
        if self.v_show_log.get():
            self._layout_log()
        else:
            self.log_frame.pack_forget()

    def _on_wheel(self, event) -> None:
        """滚轮交给鼠标所在的标签页；文本框自身可滚动时不做拦截。"""
        if isinstance(event.widget, (tk.Text, tk.Listbox)):
            return
        for page in self.tabs:
            if page.owns(event.widget):
                page.scroll(event.delta)
                return

    @staticmethod
    def _scale_row(parent, label: str, var: tk.IntVar, low: int, high: int, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(8, 0))
        tk.Scale(parent, from_=low, to=high, orient="horizontal", variable=var, length=260,
                 showvalue=True, resolution=1).grid(row=row, column=1, sticky="w", padx=6)
        parent.columnconfigure(2, weight=1)

    # ---------------- 定时刷新与交互 ----------------

    def _tick_clock(self) -> None:
        now = timeutil.now()
        self.clock_label.configure(text=now.strftime("%H:%M:%S"))
        self.date_label.configure(
            text=f"{now:%Y 年 %m 月 %d 日}  星期{WEEKDAY_CN[now.weekday()]}（北京时间）"
        )
        self.offset_label.configure(text=f"时钟偏差 {timeutil.offset_text()}")
        self._update_next(now)
        self._update_stop_state()
        self._update_volume_state()
        self._tick_timer = self.after(500, self._tick_clock)

    def _update_next(self, now) -> None:
        if not self.v_master.get():
            self.next_label.configure(text="下一次播报：总开关已关闭，全部提醒已暂停")
            return
        if not self.v_enabled.get() and not self.v_pomo_enabled.get():
            self.next_label.configure(text="下一次播报：已全部关闭")
            return
        item = self.scheduler.next_event()
        if item is None:
            self.next_label.configure(text="下一次播报：暂无计划")
            return
        moment, kind = item
        delta = moment - now
        minutes = int(delta.total_seconds() // 60)
        if minutes >= 60:
            remain = f"{minutes // 60} 小时 {minutes % 60} 分"
        else:
            remain = f"{minutes} 分钟"
        self.next_label.configure(text=f"下一次播报：{moment:%m-%d %H:%M}（{kind}），还有 {remain}")

    def _update_stop_state(self) -> None:
        """「停止」按钮只在播报进行中可用。"""
        enabled = self.announcer.is_speaking
        if enabled != self._stop_enabled:
            self._stop_enabled = enabled
            self.stop_button.configure(state="normal" if enabled else "disabled")

    def _update_volume_state(self) -> None:
        level, muted = volume.get_state()
        if level is None:
            self.volume_label.configure(text="当前系统音量：无法读取")
        else:
            state = "已静音" if muted else f"{level}%"
            self.volume_label.configure(text=f"当前系统主音量：{state}")

    def refresh_controls(self) -> None:
        """按当前模式启用/禁用相关控件。"""
        self.master_check.configure(text=self._master_text())

        mode = self.v_mode.get()
        is_custom = mode == MODE_CUSTOM
        state_custom = "normal" if is_custom else "disabled"
        all_day = self.v_hour_all_day.get()
        # 时段范围仅在非自定义模式、且未勾选全天生效时可用
        state_range = "disabled" if (is_custom or all_day) else "normal"
        self.custom_box.configure(
            state=state_custom,
            background="#ffffff" if is_custom else "#ececec",
            foreground="#000000" if is_custom else "#888888",
        )
        self.custom_frame.configure(
            text="自定义时刻（每行一个，格式 HH:MM）"
            + ("" if is_custom else "  · 未启用")
        )
        # 时段设置板块：仅整点/半点模式可用，自定义模式时整体禁用
        state_mode_range = "disabled" if is_custom else "normal"
        self.all_day_check.configure(state=state_mode_range)
        for child in self.range_hint.winfo_children():
            child.configure(state=state_range)
        self.range_frame.configure(
            text="时段设置（整点/半点模式生效）"
            + ("  · 未启用" if is_custom else "")
        )

    def refresh_voices(self) -> None:
        from .speaker import list_voices, pick_voice_name

        voices = list_voices()
        if not voices:
            messagebox.showwarning("语音", "未检测到系统语音，播报可能无声。")
            return
        self.voice_combo.configure(values=voices)
        if self.v_voice.get() not in voices:
            self.v_voice.set(pick_voice_name(self.v_voice.get()))
        self.after(100, self.apply)

    def speak_now(self) -> None:
        self.apply()
        text = time_text(self.cfg, timeutil.now())
        self._speak_async(text)

    def speak_test(self) -> None:
        self.apply()
        text = self.v_test_text.get().strip()
        if text:
            self._speak_async(text)

    def _speak_async(self, text: str) -> None:
        self.log(f"手动播报：{text}")

        def run():
            self.announcer.announce(text, self.cfg)

        threading.Thread(target=run, name="manual-speak", daemon=True).start()

    def stop_speaking(self) -> None:
        self.announcer.cancel()
        self.log("已停止当前播报")

    def toggle_autostart(self) -> None:
        wanted = self.v_autostart.get()
        ok, err = autostart.set_enabled(wanted, minimized=self.v_start_min.get())
        self._report_autostart(
            ok, err,
            f"开机自启已{'开启' if wanted else '关闭'}",
            hint="写入注册表失败，请以普通用户权限重试。",
        )
        self._sync_autostart_widgets()

    def toggle_start_minimized(self) -> None:
        """复选框直接改写启动项内容，勾选即带 --minimized。"""
        if not self.v_autostart.get():
            return
        ok, err = autostart.enable(minimized=self.v_start_min.get())
        self._report_autostart(ok, err)
        self._sync_autostart_widgets()

    def _sync_autostart_widgets(self) -> None:
        """界面状态始终回读注册表，保证与实际启动项一致。"""
        enabled = autostart.is_enabled()
        changed = self.cfg.get("autostart") != enabled
        self.cfg["autostart"] = enabled
        self.v_autostart.set(enabled)
        self.v_start_min.set(autostart.is_minimized())
        self.start_min_check.configure(state="normal" if enabled else "disabled")
        if enabled:
            text = "开机自启：已开启（托盘静默）" if self.v_start_min.get() else "开机自启：已开启"
        else:
            text = "开机自启：已关闭"
        self.state_label.configure(text=text)
        if changed:
            config.save(self.cfg)

    def _check_autostart(self) -> None:
        """启动项指向的不是当前程序时（如程序被移动过），提示用户修正。"""
        current = autostart.current_command()
        if current and not autostart.points_to_current():
            choice = self._ask_autostart_fix(current)
            if choice == "ignore":
                self.log("已忽略启动项路径变化")
            elif choice == "update":
                # 保留原有的 --minimized 设置
                ok, err = autostart.set_enabled(True, minimized=autostart.is_minimized())
                self._report_autostart(ok, err, "开机自启已指向当前程序")
            else:
                ok, err = autostart.set_enabled(False)
                self._report_autostart(ok, err, "已删除开机自启项")
        self._sync_autostart_widgets()

    def _report_autostart(self, ok: bool, err: Optional[str], done: str = "", hint: str = "") -> None:
        if ok:
            if done:
                self.log(done)
        else:
            self.log(f"开机自启设置失败：{err}")
            messagebox.showerror("开机自启", f"{hint}\n\n{err}".strip())

    def _ask_autostart_fix(self, current: str) -> str:
        """三选一：更新 / 删除 / 忽略，返回对应动作。"""
        dialog = tk.Toplevel(self)
        dialog.title("开机自启")
        dialog.resizable(False, False)
        dialog.transient(self)
        choice = {"value": "ignore"}

        text = (
            "检测到开机自启项指向的程序已改变，可能是程序所在目录发生变化。\n\n"
            f"启动项：{current}\n"
            f"当前程序：{autostart.launch_command(autostart.is_minimized())}\n\n"
            "是否将启动项更新为指向当前程序？"
        )
        ttk.Label(dialog, text=text, justify="left", wraplength=560).pack(padx=16, pady=(16, 12))

        def choose(value: str) -> None:
            choice["value"] = value
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(padx=16, pady=(0, 14), anchor="e")
        for label, value in (("更新（推荐）", "update"), ("删除启动项", "delete"), ("忽略本次", "ignore")):
            ttk.Button(buttons, text=label, command=lambda v=value: choose(v)).pack(side="left", padx=(8, 0))

        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("ignore"))
        dialog.update_idletasks()
        x = self.winfo_rootx() + max((self.winfo_width() - dialog.winfo_width()) // 2, 0)
        y = self.winfo_rooty() + max((self.winfo_height() - dialog.winfo_height()) // 3, 0)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.wait_window(dialog)
        return choice["value"]

    def open_config(self) -> None:
        path = config.config_path()
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["explorer", os.path.normpath(config.CONFIG_DIR)])

    # ---------------- 日志 ----------------

    def log(self, message: str) -> None:
        now = timeutil.now()
        self._log_queue.put(f"[{now:%H:%M:%S}] {message}")

    def _drain_log(self) -> None:
        try:
            while True:
                message = self._log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", message + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self._log_timer = self.after(300, self._drain_log)

    def handle_event(self, event, text: str) -> None:
        if text:
            self.log(f"自动播报：{text}")

    # ---------------- 托盘与退出 ----------------

    def on_close(self) -> None:
        if self.v_tray.get() and self._ensure_tray():
            self.withdraw()
            self.log("已最小化到系统托盘，双击托盘图标可重新打开")
            return
        self.quit_app()

    def _ensure_tray(self) -> bool:
        if self._tray is not None:
            return True
        if TrayIcon is None:
            return False
        try:
            # 托盘回调运行在托盘线程，统一转发到 tkinter 主线程执行
            self._tray = TrayIcon(
                on_open=self.show_window,
                on_quit=lambda: self.after(0, self.quit_app),
            )
            self._tray.start()
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"托盘初始化失败：{exc}")
            self._tray = None
            return False

    def show_window(self) -> None:
        self.after(0, self._show_window)

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_app(self) -> None:
        for timer in (getattr(self, "_tick_timer", None), getattr(self, "_log_timer", None)):
            if timer:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.scheduler.stop()
        self.destroy()


def create(cfg: Dict[str, Any], announcer, scheduler, start_minimized: bool = False) -> App:
    app = App(cfg, announcer, scheduler, start_minimized)
    app.refresh_voices()
    app.refresh_controls()
    app.log("程序已启动，配置即时生效")
    return app

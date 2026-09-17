# 北京时间播报器（TimeAnnouncer）

[GitHub](https://github.com/zhang-brook/time-announcer) | [Gitee](https://gitee.com/zhang-brook/time-announcer)

Windows 桌面小工具：到点用中文语音大声播报北京时间，支持整点 / 整点+半点 / 自定义时刻 / 番茄钟，静音时也能自动调高音量播报后还原，带图形界面与开机自启。

<table>
  <tr>
    <td align="center">
      <img width="90%" alt="Image" src="https://github.com/user-attachments/assets/f6318db6-7cb6-4dcd-8ad8-6ab63e8a6f06" />
      <br><br>
      <img width="90%" alt="image" src="https://github.com/user-attachments/assets/a6e22338-c933-4acf-a733-ee853dfd8ed0" />
    </td>
    <td align="center">
      <img width="90%" alt="image" src="https://github.com/user-attachments/assets/65f947e4-0ae2-4406-8316-5af9bc915bcd" />
      <br><br>
      <img width="90%" alt="image" src="https://github.com/user-attachments/assets/a55a8fc8-4102-48a1-ae56-b3577e24b266" />
    </td>
  </tr>
</table>

## 环境要求

- Windows 10 / 11
- Python 3.10+（需含 tkinter，官方安装包默认自带）

## 安装与运行

```powershell
pip install -r requirements.txt
python main.py                # 显示主窗口
python main.py --minimized    # 启动后最小化到系统托盘
```

也可以双击 `启动（后台运行）.bat` 以后台方式启动（不弹黑窗）。

## 功能

- **全局提醒总开关**：主界面顶部一键暂停，关闭后整点报时与番茄钟都不再提醒（「立即播报」仍可手动使用）
- **报时模式**
  - 整点报时：可设置生效时段（默认 8 点 ~ 22 点，支持跨夜如 22 至 2）
  - 整点 + 半点报时
  - 自定义时刻：每天固定若干时间点，如 `09:00 / 12:30 / 18:45`
- **番茄钟**：专注 / 休息交替播报，可设时长与轮数（0 为无限循环），与整点报时互不冲突
- **音量处理**：静音或音量过低时自动取消静音并调高到目标音量，播报结束后自动还原
- **提示音**：可选播报前先滴一声再说话，避免安静环境下突然出声吓人
- **语音设置**：发音人、语速、音量、播报文案均可自定义
- **开机自启**：写入 `HKCU\...\Run` 注册表项，无需管理员权限
- **系统托盘**：关闭窗口或后台启动时驻留托盘，双击图标恢复窗口
- **网络校时**：后台通过 NTP 获取时钟偏差，避免系统时间不准导致报时偏差

## 配置文件

位置：`%APPDATA%\TimeAnnouncer\config.json`（界面「打开配置文件」按钮可直接定位）。
首次运行自动生成，界面上的任何改动都会即时写入该文件，无需数据库。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `master_enabled` | 全局总开关，关闭后整点/自定义报时与番茄钟都不再提醒 |
| `enabled` | 报时开关，关闭后不再整点/自定义报时（不影响番茄钟） |
| `mode` | `hourly` / `hourly_half` / `custom` |
| `hour_start` / `hour_end` | 整点报时生效时段（含端点，可跨夜） |
| `custom_times` | 自定义时刻列表，格式 `HH:MM` |
| `pomodoro` | `{enabled, work_minutes, break_minutes, rounds}` |
| `voice` | `{name, rate, volume}`，`name` 留空自动选中文语音 |
| `text` | 播报文案模板，`{h}` `{m}` 为中文时分，`{H}` `{M}` 为两位数数字 |
| `audio` | `{boost_enabled, boost_volume, restore_after, chime_enabled}`，`chime_enabled` 为播报前是否先播放提示音 |
| `autostart` / `minimize_to_tray` | 自启与托盘相关 |

## 目录结构

```
time-announcer/
├── main.py                 程序入口（单实例保护、参数解析）
├── assets/
│   └── app.ico             应用图标（托盘 / 窗口 / exe 共用）
├── core/
│   ├── config.py           配置读写（JSON，默认值补全）
│   ├── timeutil.py         北京时间与中文数字、NTP 校时
│   ├── speaker.py          SAPI 语音合成（枚举语音、播报、停止）
│   ├── volume.py           系统主音量 / 静音读写
│   ├── chime.py            播报前提示音（系统提示音 / 蜂鸣兜底）
│   ├── announcer.py        播报流程（临时调高音量 → 提示音 → 播报 → 还原）
│   ├── scheduler.py        定时调度（四种计划）
│   ├── autostart.py        开机自启（注册表）
│   ├── icon.py             图标绘制与 assets/app.ico 生成
│   ├── ui.py               tkinter 图形界面
│   └── tray.py             系统托盘图标（可选）
├── TimeAnnouncer.spec      PyInstaller 打包脚本
└── requirements.txt
```

## 应用图标

托盘图标、窗口标题栏/任务栏图标与打包出的 exe 图标共用同一份图形 `assets/app.ico`。
图标由 [core/icon.py](core/icon.py) 的 `draw()` 绘制，修改后重新生成即可，三处同时生效：

```powershell
python -m core.icon
```

## 常见问题

- **没声音**：确认系统已安装中文语音（设置 → 时间和语言 → 语音）；界面「语音与音量」页可刷新列表。
- **静音时仍未出声**：勾选「静音或音量过低时自动调高系统音量」，并把目标音量调大。
- **播报后音量没还原**：勾选「播报结束后还原原音量与静音状态」。
- **开机没启动**：界面勾选「开机自动启动」需保持程序路径不变；移动目录后请重新勾选一次。

## 打包成 exe（可选）

```powershell
pip install pyinstaller
# python -m PyInstaller --version

# docs: https://pyinstaller.org/en/latest/usage.html
python -m PyInstaller --noconfirm --clean TimeAnnouncer.spec

# 不使用 spec 时的等价命令
# python -m PyInstaller --noconfirm --onefile --windowed --name TimeAnnouncer `
#     --icon assets/app.ico --add-data "assets/app.ico;assets" main.py
```

产物在 `dist\TimeAnnouncer.exe`，可自行放到固定目录；若移动后与注册表里的启动项不一致，下次启动会弹窗询问是否更新指向。

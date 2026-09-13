@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 以后台方式启动（不显示控制台窗口），并最小化到系统托盘
start "" pythonw main.py --minimized

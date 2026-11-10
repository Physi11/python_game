@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先使用带 tkinter 的官方 Python；找不到则退回 PATH 里的 python
set PY=D:\python\python.exe
if not exist "%PY%" set PY=python

echo ==========================================
echo  自动同步：监听代码改动并自动提交推送
echo  关闭此窗口即停止监听
echo ==========================================
echo.

"%PY%" tools\auto_sync.py %*

echo.
echo 监听已结束。
pause

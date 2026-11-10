@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先使用自带 tkinter 的官方 Python；若不存在则退回 PATH 中的 python
set PY=D:\python\python.exe
if not exist "%PY%" set PY=python

"%PY%" main.py
if errorlevel 1 pause

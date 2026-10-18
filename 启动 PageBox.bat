@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
where pythonw.exe >nul 2>nul && set "PY=pythonw.exe"
if not defined PY ( where pyw.exe >nul 2>nul && set "PY=pyw.exe" )
if not defined PY ( where python.exe >nul 2>nul && set "PY=python.exe" )

if not defined PY (
  echo.
  echo   没有找到 Python。请先装一个 Python 3.9 以上版本，
  echo   安装时记得勾上 "Add python.exe to PATH"。
  echo.
  pause
  exit /b 1
)

start "" "%PY%" "%~dp0app.py" %*

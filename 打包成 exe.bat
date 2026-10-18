@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo   改完 app.py 之后跑一下这个，重新打包成 exe。
echo   需要 Python 3.9 以上，PyInstaller 已经放在 _build_tools 里了。
echo.

if not exist "_build_tools\PyInstaller" (
  echo   找不到 _build_tools，先装打包工具：
  echo       python -m pip install --target _build_tools pyinstaller
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0_build_tools"

rem PyInstaller 会把 dist\PageBox 整个重建，你正在用的工作区在里面，
rem 所以先挪出来，打完再放回去。
set "KEEP=%~dp0_数据保留"
set "HAD_DATA="
if exist "dist\PageBox\data" (
  echo   先把 dist\PageBox\data 里的工作区挪到一边...
  if exist "%KEEP%" rmdir /s /q "%KEEP%"
  robocopy "dist\PageBox\data" "%KEEP%" /E /NFL /NDL /NJH /NJS /NP >nul
  set "HAD_DATA=1"
)

echo   [1/2] 打包成文件夹版 dist\PageBox\ ...
python -m PyInstaller --noconfirm --windowed --name PageBox --icon pagebox.ico ^
  --paths vendor --collect-all tkinterdnd2 ^
  --hidden-import tkinterdnd2 --hidden-import tkinterdnd2.TkinterDnD ^
  --exclude-module numpy --exclude-module pandas --exclude-module matplotlib ^
  --exclude-module scipy --exclude-module PyQt5 --exclude-module PySide2 ^
  --exclude-module tensorflow app.py
if errorlevel 1 goto failed

if defined HAD_DATA (
  echo   把工作区放回去...
  robocopy "%KEEP%" "dist\PageBox\data" /E /NFL /NDL /NJH /NJS /NP >nul
  rmdir /s /q "%KEEP%"
)

echo.
echo   [2/2] 再打一个单文件版 dist\PageBoxPortable.exe ...
python -m PyInstaller --noconfirm --onefile --windowed --name PageBoxPortable --icon pagebox.ico ^
  --paths vendor --collect-all tkinterdnd2 ^
  --hidden-import tkinterdnd2 --hidden-import tkinterdnd2.TkinterDnD ^
  --exclude-module numpy --exclude-module pandas --exclude-module matplotlib ^
  --exclude-module scipy --exclude-module PyQt5 --exclude-module PySide2 ^
  --exclude-module tensorflow app.py
if errorlevel 1 goto failed

echo.
echo   好了。在 dist 里：
echo     PageBox\PageBox.exe          文件夹版，启动快，推荐
echo     PageBoxPortable.exe          单文件版，方便发人，启动慢两三秒
echo.
pause
exit /b 0

:failed
if defined HAD_DATA (
  echo   打包虽然失败了，先把你的工作区放回去...
  robocopy "%KEEP%" "dist\PageBox\data" /E /NFL /NDL /NJH /NJS /NP >nul
  rmdir /s /q "%KEEP%"
)
echo.
echo   打包失败了，往上翻看报错。
pause
exit /b 1

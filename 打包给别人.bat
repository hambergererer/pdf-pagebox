@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "SRC=dist\PageBox"
set "OUT=发布"
set "STAGE=%~dp0_打包临时"

if not exist "%SRC%\PageBox.exe" (
  echo.
  echo   还没打过包。先双击「打包成 exe.bat」。
  echo.
  pause
  exit /b 1
)

echo.
echo   正在整理要发出去的文件...

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
robocopy "%SRC%" "%STAGE%\PageBox" /E /XD data /XF *.log *.tmp 自检报告.txt /NFL /NDL /NJH /NJS /NP >nul

rem 你自己的工作区不能带给别人；自检报告也只跟你这台机器有关
if exist "%STAGE%\PageBox\data" rmdir /s /q "%STAGE%\PageBox\data"
if exist "%STAGE%\PageBox\自检报告.txt" del /q "%STAGE%\PageBox\自检报告.txt"

if not exist "%OUT%" mkdir "%OUT%"

echo   正在压缩...
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\PageBox' -DestinationPath '%OUT%\PageBox.zip' -Force"

if exist "dist\PageBoxPortable.exe" copy /y "dist\PageBoxPortable.exe" "%OUT%\PageBox-单文件版.exe" >nul

rmdir /s /q "%STAGE%"

echo.
echo   好了，都放在「发布」文件夹里：
echo.
echo     PageBox.zip            解压就能用，启动快，推荐发这个
echo     PageBox-单文件版.exe    一个文件直接发，启动慢两三秒
echo.
echo   对方不用装 Python。第一次运行如果 Windows 弹出
echo   "已保护你的电脑"，点「更多信息」再点「仍要运行」就行
echo   —— 那是因为这个 exe 没有花钱买数字签名。
echo.
pause

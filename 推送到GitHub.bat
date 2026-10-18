@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   正在把本地仓库推到 GitHub...
echo   地址：https://github.com/hambergererer/pdf-pagebox
echo.
echo   第一次推会弹一个登录窗口 —— 按提示登录你的 GitHub 账号就行。
echo   如果没有弹窗、直接问你要密码：GitHub 早就不收账号密码了，
echo   要填的是 Personal Access Token（Settings - Developer settings - Tokens，
echo   勾 repo 权限）。粘进去回车。
echo.

git push -u origin main

if errorlevel 1 (
  echo.
  echo   ------------------------------------------------------------
  echo   没推上去。按上面的报错看是哪一种：
  echo.
  echo   1. denied / 403  -- 没登录或 token 没权限
  echo   2. rejected      -- 远端有东西了。先跑：git pull --rebase origin main
  echo                       再重跑这个脚本
  echo   3. 超时 / 连不上 -- 网络问题，挂个代理再来
  echo   ------------------------------------------------------------
  echo.
  pause
  exit /b 1
)

echo.
echo   推上去了。打开看看：
echo   https://github.com/hambergererer/pdf-pagebox
echo.
echo   下一步可以发个 Release：仓库页面右边 Releases - Create a new release，
echo   标签填 v1.0，把「发布\PageBox.zip」拖上去。
echo.
pause

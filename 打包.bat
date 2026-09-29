@echo off
chcp 65001 >nul
rem ===========================================================================
rem  打包.bat —— 一条命令重打桌面宠物 exe
rem
rem  用法：把本文件和 LunaPet.spec / pet_launcher.py / packs / app_icon.ico
rem        放在一起，双击即可。产物在  dist\LunaPet\LunaPet.exe
rem ===========================================================================
setlocal
cd /d "%~dp0"

rem 运行环境（自带 PySide6 6.11.2 的那个解释器）
set "PY=C:\Users\mercy\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not exist "%PY%" (
    echo [x] 找不到解释器：%PY%
    exit /b 1
)

echo [1/3] 检查 PyInstaller ...
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo       未安装，正在安装 pyinstaller ...
    "%PY%" -m pip install pyinstaller || (echo [x] 安装失败 & exit /b 1)
)

echo [2/3] 开始打包（onedir 模式，约 40 秒）...
"%PY%" -m PyInstaller --noconfirm --clean "LunaPet.spec"
if errorlevel 1 (
    echo [x] 打包失败，请看上面的报错
    exit /b 1
)

echo [3/3] 打包完成
echo       产物：%cd%\dist\LunaPet\LunaPet.exe

echo.
echo 提示：想跑一次冒烟验证，执行  "%PY%" _验证exe.py
pause

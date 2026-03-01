@echo off
chcp 65001 > nul
title NetMonitor 服务器安装

echo ========================================
echo   NetMonitor 服务器安装程序
echo ========================================
echo.

:: 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址：https://www.python.org/downloads/
    pause & exit /b 1
)

echo [1/3] 安装依赖...
pip install -r server\requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause & exit /b 1
)

echo.
echo [2/3] 获取本机 IP...
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /R /C:"IPv4.*192\."') do set LOCAL_IP=%%i
set LOCAL_IP=%LOCAL_IP: =%
if "%LOCAL_IP%"=="" (
    for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr "IPv4"') do set LOCAL_IP=%%i
    set LOCAL_IP=%LOCAL_IP: =%
)
echo 本机 IP: %LOCAL_IP%

echo.
echo [3/3] 创建启动脚本...
echo @echo off > start_server.bat
echo chcp 65001 ^> nul >> start_server.bat
echo title NetMonitor 服务器 >> start_server.bat
echo cd /d "%~dp0" >> start_server.bat
echo python server\main.py >> start_server.bat
echo pause >> start_server.bat

echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo 启动服务器：双击 start_server.bat
echo Web 界面：  http://%LOCAL_IP%:8866
echo.
echo 其他电脑安装客户端时，服务器地址填：
echo   http://%LOCAL_IP%:8866
echo.
pause

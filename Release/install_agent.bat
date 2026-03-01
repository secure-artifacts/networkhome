@echo off
chcp 65001 > nul
title NetMonitor 客户端安装

echo ========================================
echo   NetMonitor 客户端安装程序 (Windows)
echo ========================================
echo.

:: 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址：https://www.python.org/downloads/
    pause & exit /b 1
)

echo [1/2] 安装依赖...
pip install -r agent\requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause & exit /b 1
)

echo.
echo [2/2] 创建启动脚本...
echo @echo off > start_agent.bat
echo chcp 65001 ^> nul >> start_agent.bat
echo title NetMonitor Agent >> start_agent.bat
echo cd /d "%~dp0" >> start_agent.bat
echo python agent\agent.py >> start_agent.bat
echo pause >> start_agent.bat

echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo 启动客户端：双击 start_agent.bat
echo 首次运行需要输入服务器地址和本机名称
echo.
pause

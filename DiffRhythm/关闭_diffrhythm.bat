@echo off
title Stop DiffRhythm Service
if not "%~1"=="" (set STOPPORT=%~1) else (set STOPPORT=7863)
echo 正在停止 DiffRhythm 服务 (端口 %STOPPORT%)...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%STOPPORT% " ^| findstr "LISTENING"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /I "diffrhythm_app.py" >nul 2>&1
    if errorlevel 1 (
        echo 跳过 PID=%%a: 端口 %STOPPORT% 被其它程序占用, 不是本项目服务, 不予结束。
    ) else (
        set FOUND=1
        echo 结束进程 PID=%%a
        taskkill /F /T /PID %%a >nul 2>&1
    )
)
if "%FOUND%"=="0" echo 未发现正在运行的服务。

ping -n 3 127.0.0.1 >nul
echo.
echo 当前显存占用:
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo [OK] 服务已关闭, 显存已随进程释放。
pause

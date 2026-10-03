@echo off
title MusicGen Service (Port 7861)
cd /d %~dp0

set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=G:\xmgousi\音乐大模型\hf_cache
rem 可选参数: 第 1 个参数为端口号, 不传则用默认端口 7861
if not "%~1"=="" (set MUSICGEN_PORT=%~1) else (set MUSICGEN_PORT=7861)
set LOG=G:\xmgousi\音乐大模型\logs\musicgen.log

echo ============================================
echo   MusicGen 文本生成音乐  端口: %MUSICGEN_PORT%
echo ============================================
rem 端口占用预检: 若端口已被其它程序监听则提示并退出, 避免启动后一直无响应
netstat -ano | findstr /C:":%MUSICGEN_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [错误] 端口 %MUSICGEN_PORT% 已被其它程序占用, 无法启动:
    netstat -ano | findstr /C:":%MUSICGEN_PORT% " | findstr "LISTENING"
    echo 请先结束占用该端口的程序, 对照上面的 PID, 再重新运行本脚本。
    pause
    exit /b 1
)

echo 正在后台启动服务, 就绪后浏览器将自动打开...

if exist "%LOG%" del "%LOG%"
start "musicgen-server" /min cmd /c "venv\Scripts\python.exe musicgen_app.py >> "%LOG%" 2>&1"

set TRYCOUNT=0
:wait
ping -n 3 127.0.0.1 >nul
curl -sf -o nul http://127.0.0.1:%MUSICGEN_PORT%/api/status
if not errorlevel 1 goto ready
rem 端口仍在监听 = 进程活着正在加载模型, 继续等
netstat -ano | findstr /C:":%MUSICGEN_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto wait
rem 端口未监听 = 服务进程已退出(常见于系统内存不足被终止), 自动重启最多 3 次
set /a TRYCOUNT+=1
if %TRYCOUNT% geq 9 goto fail
echo [!] 服务进程已退出(第 %TRYCOUNT% 次), 疑似系统内存不足, 30 秒后自动重启...
ping -n 31 127.0.0.1 >nul
start "musicgen-server" /min cmd /c "venv\Scripts\python.exe musicgen_app.py >> "%LOG%" 2>&1"
goto wait

:ready

start "" http://127.0.0.1:%MUSICGEN_PORT%
echo.
echo [OK] 服务已就绪, 浏览器已打开: http://127.0.0.1:%MUSICGEN_PORT%
echo   日志: %LOG%
echo   首次生成会先加载模型(约 1 分钟), 请耐心等待。
echo   关闭服务请运行: 关闭_musicgen.bat
echo.
pause

:fail
echo [错误] 服务多次启动失败, 请查看日志: %LOG%
echo 建议: 关闭其它占用内存的大模型程序(如 F5-TTS/llama/KoboldCpp 等)后重试。
pause
exit /b 1

@echo off
cd /d %~dp0
set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=G:\xmgousi\音乐大模型\hf_cache
set MUSICGEN_PORT=17861
start "mg-server" /min cmd /c "venv\Scripts\python.exe musicgen_app.py >> G:\xmgousi\音乐大模型\logs\musicgen.log 2>&1"
exit /b 0

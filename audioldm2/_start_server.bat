@echo off
cd /d %~dp0
set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=G:\xmgousi\音乐大模型\hf_cache
set AUDIOLDM2_PORT=7862
venv\Scripts\python.exe audioldm2_app.py >> G:\xmgousi\音乐大模型\logs\audioldm2.log 2>&1

@echo off
cd /d %~dp0
venv\Scripts\python.exe 测试结果\run_tests.py > 测试结果\test_run.log 2>&1
exit /b %errorlevel%

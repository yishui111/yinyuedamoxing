#!/bin/bash
# MusicGen 测试编排: 候风(等内存宽裕) -> 启动服务 -> 预热加载 -> 跑套件(带重试)
cd "G:\xmgousi\音乐大模型\audiocraft" || exit 1
LOG="G:\xmgousi\音乐大模型\logs\musicgen.log"
BASE="http://127.0.0.1:17861"

free_commit_gb() {
  wmic OS get FreeVirtualMemory /format:list 2>/dev/null | grep FreeVirtualMemory | cut -d= -f2 | tr -d '\r' | awk '{print int($1/1048576)}'
}

wait_calm() {
  local ok=0
  while [ $ok -lt 2 ]; do
    fc=$(free_commit_gb)
    if [ "$fc" -ge 18 ]; then ok=$((ok+1)); else ok=0; fi
    echo "[wait_calm] FreeCommit=${fc}GB calm_streak=$ok/2"
    sleep 20
  done
}

start_server() {
  cmd //c _start_server.bat
}

wait_ready() {
  for i in $(seq 1 90); do
    sleep 10
    if curl -sf -m 3 "$BASE/api/status" >/dev/null 2>&1; then echo "[ready] after ~$((i*10))s"; return 0; fi
  done
  return 1
}

for round in 1 2 3 4 5; do
  echo "########## ROUND $round $(date +%H:%M:%S) ##########"
  # 若服务已在跑先关掉, 保证干净状态
  cmd //c "关闭_musicgen.bat 17861" < /dev/null > /dev/null 2>&1
  wait_calm
  echo "[round $round] starting server..."
  start_server
  if ! wait_ready; then echo "[round $round] server never became ready"; continue; fi
  # 预热: 触发一次模型加载(最脆弱的窗口, 单独控制)
  echo "[round $round] warmup load..."
  curl -sf -m 2400 -X POST "$BASE/api/generate" -H "Content-Type: application/json" \
       -d '{"prompt":"soft warmup tone","duration":5}' > /tmp/warmup.json 2>&1
  rc=$?
  echo "[round $round] warmup rc=$rc $(head -c 200 /tmp/warmup.json)"
  if [ $rc -ne 0 ]; then continue; fi
  # 正式套件, 最多 2 次
  for att in 1 2; do
    echo "[round $round] suite attempt $att..."
    cmd //c "set MUSICGEN_PORT=17861&& venv\Scripts\python.exe 测试结果\run_tests.py > 测试结果\test_run.log 2>&1"
    rc=$?
    echo "[round $round] suite attempt $att EXIT=$rc"
    if [ $rc -eq 0 ]; then echo "SUCCESS"; exit 0; fi
    sleep 30
    # 套件失败可能杀死了服务, 重新走外层流程
    curl -sf -m 3 "$BASE/api/status" >/dev/null 2>&1 || break
  done
done
echo "ALL ROUNDS FAILED"
exit 1

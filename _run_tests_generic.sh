#!/bin/bash
# 通用测试编排: 候风(等内存宽裕) -> 启动服务 -> 预热加载 -> 跑套件(带重试)
# 用法: bash _run_tests_generic.sh <folder> <closebat> <port> <warmup_json> [portenv]
FOLDER="$1"; CLOSEBAT="$2"; PORT="$3"; WARMUP="$4"; PORTENV="$5"; THRESH="${6:-18}"
BASE="http://127.0.0.1:$PORT"
ROOT="G:\\xmgousi\\音乐大模型"
cd "$ROOT/$FOLDER" || exit 1

free_commit_gb() {
  wmic OS get FreeVirtualMemory /format:list 2>/dev/null | grep FreeVirtualMemory | cut -d= -f2 | tr -d '\r' | awk '{print int($1/1048576)}'
}

wait_calm() {
  local ok=0
  while [ $ok -lt 2 ]; do
    fc=$(free_commit_gb)
    if [ "$fc" -ge "$THRESH" ]; then ok=$((ok+1)); else ok=0; fi
    echo "[wait_calm] FreeCommit=${fc}GB calm_streak=$ok/2 (threshold=$THRESH)"
    sleep 20
  done
}

wait_ready() {
  for i in $(seq 1 60); do
    sleep 10
    if curl -sf -m 3 "$BASE/api/status" >/dev/null 2>&1; then echo "[ready] after ~$((i*10))s"; return 0; fi
  done
  return 1
}

for round in 1 2 3 4 5 6 7 8; do
  echo "########## ROUND $round $(date +%H:%M:%S) ##########"
  cmd //c "$CLOSEBAT $PORT" < /dev/null > /dev/null 2>&1
  wait_calm
  echo "[round $round] starting server..."
  cmd //c _start_server.bat
  if ! wait_ready; then echo "[round $round] server never became ready"; continue; fi
  echo "[round $round] warmup..."
  curl -sf -m 7200 -X POST "$BASE/api/generate" -H "Content-Type: application/json" -d "$WARMUP" > /tmp/warmup.json 2>&1
  rc=$?
  echo "[round $round] warmup rc=$rc $(head -c 150 /tmp/warmup.json)"
  if [ $rc -ne 0 ]; then continue; fi
  for att in 1 2; do
    echo "[round $round] suite attempt $att..."
    if [ -n "$PORTENV" ]; then
      cmd //c "set $PORTENV&& venv\\Scripts\\python.exe 测试结果\\run_tests.py > 测试结果\\test_run.log 2>&1"
    else
      cmd //c "venv\\Scripts\\python.exe 测试结果\\run_tests.py > 测试结果\\test_run.log 2>&1"
    fi
    rc=$?
    echo "[round $round] suite attempt $att EXIT=$rc"
    if [ $rc -eq 0 ]; then echo "SUCCESS"; exit 0; fi
    sleep 30
    curl -sf -m 3 "$BASE/api/status" >/dev/null 2>&1 || break
  done
done
echo "ALL ROUNDS FAILED"
exit 1

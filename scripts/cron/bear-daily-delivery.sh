#!/bin/bash
# 熊熊博物館每日配送 — no_agent 模式 script
#
# 為什麼用 no_agent（不經過 agent）：
#   2026-11-02 / 11-03 連續兩天配送失敗，都是 cron agent 在「執行前查證」階段
#   耗盡工具呼叫次數上限，導致背景程序被連帶殺掉（11/02 命令根本沒跑、
#   11/03 跑到第 2 隻被砍）。no_agent 由排程器直接跑本 script，
#   沒有工具呼叫上限、不會有「查證過度」，配送必定執行到底。
#
# 排程：10 4 * * 1-5（週一至週五，週末不配送）
#
# stdout 會被原樣送進 Discord thread，所以只輸出精簡報告；
# 完整 log 在 /home/fjj04/my-bear-museum/vocabulary/logs/<日期>.log

set -uo pipefail

PROJECT_DIR="/home/fjj04/my-bear-museum"
VENV_PY="/home/fjj04/.hermes/hermes-agent/venv/bin/python"
LOG_DIR="${PROJECT_DIR}/vocabulary/logs"
TIMEOUT=1800   # 6 隻實測約 6-8 分鐘；驗圖閘門若升級（T87/T88）可再拉高

cd "${PROJECT_DIR}" || { echo "❌ 無法進入 ${PROJECT_DIR}"; exit 1; }

# 取得今日日期（台北時區）
TODAY="$(TZ=Asia/Taipei date +%F)"
LOG_FILE="${LOG_DIR}/${TODAY}.log"

# --- 週末跳過（cron 排程已限定 1-5，這是雙重保險）---
DOW="$(TZ=Asia/Taipei date +%u)"   # 1=週一 ... 7=週日
if [ "$DOW" -ge 6 ]; then
  echo "⏭️ 今天是週${DOW}（週末不配送）"
  exit 0
fi

# --- 檢查今天是否已經配送過（避免重複）---
if [ -d "${PROJECT_DIR}/bears/${TODAY}" ] && [ -n "$(ls -A "${PROJECT_DIR}/bears/${TODAY}" 2>/dev/null | grep -v '^thumbs$' | head -1)" ]; then
  EXISTING=$(ls "${PROJECT_DIR}/bears/${TODAY}"/*.png 2>/dev/null | wc -l)
  echo "⏭️ ${TODAY} 已有 ${EXISTING} 張圖，跳過重複配送"
  exit 0
fi

# --- 執行配送 ---
echo "🐻 熊熊博物館每日配送 ${TODAY} 開始…"
START_TS=$(date +%s)

timeout "${TIMEOUT}" "${VENV_PY}" "${PROJECT_DIR}/vocabulary/daily-delivery.py" \
  --comfy-count 6 --minimax-count 0 \
  > /tmp/bear-daily-delivery.out 2>&1
EXIT_CODE=$?

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

# --- 產出精簡報告 ---
if [ "$EXIT_CODE" -eq 124 ]; then
  echo "❌ 配送逾時（${TIMEOUT}s 上限），未完成。log: ${LOG_FILE}"
  exit 1
fi

if [ "$EXIT_CODE" -ne 0 ]; then
  echo "❌ 配送失敗（exit ${EXIT_CODE}），耗時 ${ELAPSED}s"
  echo "--- 錯誤摘要 ---"
  grep -iE "✗|錯誤|失敗|error|Traceback" /tmp/bear-daily-delivery.out 2>/dev/null | tail -8
  echo "--- 完整 log: ${LOG_FILE} ---"
  exit 1
fi

# --- 統計結果 ---
COUNT=$(ls "${PROJECT_DIR}/bears/${TODAY}"/*.png 2>/dev/null | wc -l | tr -d ' ')
SHAPES=$(grep -m1 "造型:" "${LOG_FILE}" 2>/dev/null | sed 's/.*造型: //')
POSES=$(grep -m1 "姿勢:" "${LOG_FILE}" 2>/dev/null | sed 's/.*姿勢: //')
STYLES=$(grep -m1 "風格:" "${LOG_FILE}" 2>/dev/null | sed 's/.*風格: //')
FALLBACK_COUNT=$(grep -c "prompt (fallback)" "${LOG_FILE}" 2>/dev/null || true)
FALLBACK_COUNT="${FALLBACK_COUNT:-0}"

# --- 驗證部署 ---
HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://kumaweb.pages.dev/bears.json" 2>/dev/null)
ONLINE=$(curl -s --max-time 15 "https://kumaweb.pages.dev/bears.json" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)['bears']))" 2>/dev/null || echo "?")

echo "✅ 配送完成 ${COUNT} 隻（耗時 ${ELAPSED}s）"
echo "📚 線上館藏: ${ONLINE} 隻（bears.json HTTP ${HTTP}）"
[ -n "$STYLES" ] && echo "🎨 風格: ${STYLES}"
[ -n "$SHAPES" ] && echo "🧸 造型: ${SHAPES}"
[ -n "$POSES" ]  && echo "🎭 姿勢: ${POSES}"
if [ "$FALLBACK_COUNT" != "0" ]; then
  echo "⚠️ 有 ${FALLBACK_COUNT} 次 prompt fallback（該批圖不受四隻腳規則保證）"
fi
echo "📄 log: ${LOG_FILE}"

exit 0

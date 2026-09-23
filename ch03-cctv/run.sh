#!/usr/bin/env bash
# run.sh — CCTV → 시맨틱 RDF 파이프라인 오케스트레이터
#
# Usage:
#   ./run.sh setup            # .venv 생성 + 의존성 설치
#   ./run.sh csv [CSV] [OUT]   # CSV → GeoSPARQL TTL  (기본: cctv/OpenDataCCTV.csv → cctv/cctv.ttl)
#   ./run.sh llm [SENSOR] [TIME] [SHOT_DIR]
#                             # 단일 단계: 5장 스냅샷 → 비전 모델 → SOSA TTL
#   ./run.sh llm2 [SENSOR] [TIME] [SHOT_DIR]
#                             # 두 단계: 5장 스냅샷 → 영문 설명 → SOSA TTL
#   ./run.sh fuseki           # Fuseki 기동 (in-memory, 업데이트 가능, 데이터셋 /fc)
#   ./run.sh load             # cctv.ttl + result.ttl 를 Fuseki에 적재
#   ./run.sh stream           # Fuseki(localhost:3030)에 스트림 URL INSERT
#   ./run.sh ui               # Streamlit UI 실행 (이미지→자연어→온톨로지 시각화)
#   ./run.sh all              # setup + csv + llm 전체 실행
#
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
FUSEKI_HOME="${FUSEKI_HOME:-fuseki}"
FUSEKI_URL="${FUSEKI_URL:-http://localhost:3030}"

log() { printf '\033[1;36m[run]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[err]\033[0m %s\n' "$*" >&2; }

setup() {
  log "Python venv 생성: $VENV"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  log "의존성 설치 (requests, rdflib)"
  "$PIP" install -q --upgrade pip
  "$PIP" install -q -r llm/requirements.txt
  log "완료. 인터프리터: $PY"
}

ensure_venv() {
  [ -x "$PY" ] || { err "venv 없음. 먼저 './run.sh setup' 실행"; exit 1; }
}

ensure_ollama() {
  if ! curl -s -m 3 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    log "Ollama 미동작 → 'ollama serve' 시작"
    command -v ollama >/dev/null || { err "ollama 미설치 (https://ollama.com)"; exit 1; }
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    for _ in $(seq 1 15); do
      sleep 1
      curl -s -m 2 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
    done
  fi
  curl -s -m 3 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 || { err "Ollama 시작 실패"; exit 1; }
  for m in "$@"; do
    if ! ollama list 2>/dev/null | grep -q "^$m"; then
      log "모델 다운로드: $m"
      ollama pull "$m"
    fi
  done
}

cmd_csv() {
  ensure_venv
  local csv="${1:-cctv/OpenDataCCTV.csv}" out="${2:-cctv/cctv.ttl}"
  log "CSV → TTL: $csv → $out"
  "$PY" cctv/csv_to_cctv_ttl.py "$csv" -o "$out"
  "$PY" -c "from rdflib import Graph; g=Graph(); g.parse('$out'); print('[run] 검증 OK -', len(g), 'triples')"
}

cmd_llm() {
  ensure_venv
  ensure_ollama qwen3.8:27b-mlx
  local sensor="${1:-http://k.fc/onto/cctv#L010009}"
  local time="${2:-2025-10-17T14:30:00Z}"
  local dir="${3:-llm/shots}"
  log "이미지 → 온톨로지 TTL (qwen3.8:27b-mlx, 단일 단계), sensor=$sensor time=$time"
  "$PY" llm/image_to_sosa_ttl.py \
    "$dir/shot_01.jpg" "$dir/shot_02.jpg" "$dir/shot_03.jpg" \
    "$dir/shot_04.jpg" "$dir/shot_05.jpg" \
    --sensor "$sensor" --time "$time" --out llm/result.ttl
  "$PY" -c "from rdflib import Graph; g=Graph(); g.parse('llm/result.ttl'); print('[run] 검증 OK -', len(g), 'triples')"
}

cmd_llm2() {
  ensure_venv
  ensure_ollama qwen3.8:27b-mlx
  local sensor="${1:-http://k.fc/onto/cctv#L010009}"
  local time="${2:-2025-10-17T14:30:00Z}"
  local dir="${3:-llm/shots}"
  log "1) 이미지 → 설명 (qwen3.8:27b-mlx)"
  "$PY" llm/cctv_describe_en.py \
    "$dir/shot_01.jpg" "$dir/shot_02.jpg" "$dir/shot_03.jpg" \
    "$dir/shot_04.jpg" "$dir/shot_05.jpg" > llm/result_en.txt
  cat llm/result_en.txt
  log "2) 설명 → SOSA TTL (qwen3.8:27b-mlx), sensor=$sensor time=$time"
  "$PY" llm/text_to_sosa_ttl.py \
    --text-file llm/result_en.txt --sensor "$sensor" --time "$time" --out llm/result.ttl
  "$PY" -c "from rdflib import Graph; g=Graph(); g.parse('llm/result.ttl'); print('[run] 검증 OK -', len(g), 'triples')"
}

ensure_fuseki() {
  if ! curl -s -m 3 "$FUSEKI_URL/\$/ping" >/dev/null 2>&1; then
    [ -x "$FUSEKI_HOME/fuseki-server" ] || { err "Fuseki 없음: $FUSEKI_HOME (다운로드 후 재시도)"; exit 1; }
    log "Fuseki 기동 → /fc (in-memory, update)"
    nohup "$FUSEKI_HOME/fuseki-server" --update --mem /fc >/tmp/fuseki.log 2>&1 &
    for _ in $(seq 1 20); do
      sleep 1
      curl -s -m 2 "$FUSEKI_URL/\$/ping" >/dev/null 2>&1 && break
    done
  fi
  curl -s -m 3 "$FUSEKI_URL/\$/ping" >/dev/null 2>&1 || { err "Fuseki 시작 실패 (/tmp/fuseki.log 확인)"; exit 1; }
  log "Fuseki 동작 중: $FUSEKI_URL"
}

cmd_load() {
  ensure_fuseki
  for ttl in cctv/cctv.ttl llm/result.ttl; do
    [ -f "$ttl" ] || { err "$ttl 없음 (먼저 csv/llm 실행)"; continue; }
    log "적재: $ttl"
    curl -s -X POST -H 'Content-Type: text/turtle' --data-binary @"$ttl" \
      "$FUSEKI_URL/fc/data" -w "  HTTP %{http_code}\n" -o /dev/null
  done
}

cmd_stream() {
  ensure_fuseki
  log "Fuseki에 스트림 URL INSERT"
  sh cctv/insert_stream.sh
}

cmd_ui() {
  ensure_venv
  ensure_ollama
  log "Streamlit UI → http://localhost:8501"
  exec "$VENV/bin/streamlit" run app.py
}

case "${1:-}" in
  setup)  setup ;;
  csv)    shift; cmd_csv "$@" ;;
  llm)    shift; cmd_llm "$@" ;;
  llm2)   shift; cmd_llm2 "$@" ;;
  fuseki) ensure_fuseki ;;
  load)   cmd_load ;;
  stream) cmd_stream ;;
  ui)     cmd_ui ;;
  all)    setup; cmd_csv; cmd_llm ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac

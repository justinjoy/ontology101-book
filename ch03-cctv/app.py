#!/usr/bin/env python3
# app.py — CCTV 스냅샷 → 온톨로지 추출 시각화 (Streamlit)
#
# 실행:
#   ./.venv/bin/streamlit run app.py
#
# 두 가지 파이프라인 제공:
#   단일 단계: [이미지] → 구조화 JSON → SOSA TTL
#   두 단계:   [이미지] → 자연어 → 구조화 JSON → SOSA TTL
#   모든 변환 단계는 동일 모델(qwen3.8:27b-mlx)을 쓰고, 단계 차이는 프롬프트에서 온다.
#              두 단계는 자연어 기술과 온톨로지 변환을 각각의 버튼으로 나누어 지시한다.
#              영문 기술 아래에 한국어 번역을 함께 보여주되, 온톨로지 변환 입력은 영문 원문만 쓴다.
import re
import sys
from pathlib import Path

import requests
import streamlit as st

ROOT = Path(__file__).parent
LLM = ROOT / "llm"
SHOTS = LLM / "shots"
sys.path.insert(0, str(LLM))

# 기존 스크립트의 프롬프트/함수 재사용 (단일 출처 유지)
import image_to_sosa_ttl as vlm          # PROMPT, MODEL, HOST, to_b64, parse_json
import cctv_describe_en as desc          # PROMPT_EN, MODEL
import text_to_sosa_ttl as onto          # PROMPT, MODEL, call_llm, to_ttl, norm_enum

st.set_page_config(page_title="CCTV → 온톨로지", page_icon="🛰️", layout="wide")

MODE_ONE = "단일 단계 (이미지 → 구조화)"
MODE_TWO = "두 단계 (기술 → 구조화)"

# 한국어 번역은 화면 표시 전용이다. 온톨로지 변환에는 영문 원문만 넘긴다.
TRANSLATE_PROMPT = (
    "다음은 CCTV 영상에 대한 영문 상황 설명이다. 자연스러운 한국어로 번역하라.\n"
    "내용을 요약하거나 덧붙이지 말고, 번역문만 출력하라.\n\n<<<TEXT>>>"
)
THINK_RE = re.compile(r"<think>.*?</think>", re.S)   # 추론형 모델의 사고 블록 제거


# ---------------------------------------------------------------- helpers
def ollama_up(host: str) -> bool:
    try:
        return requests.get(f"{host}/api/tags", timeout=3).ok
    except requests.RequestException:
        return False


def extract_from_images(host: str, model: str, image_paths) -> dict:
    """단일 단계: 이미지 5장 → 비전 모델 → 구조화 JSON."""
    payload = {
        "model": model,
        "prompt": vlm.PROMPT,
        "images": [vlm.to_b64(p) for p in image_paths],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return vlm.parse_json(r.json().get("response", "").strip())


def describe_images(host: str, model: str, image_paths, prompt: str) -> str:
    """두 단계 1/2: 이미지 5장 → 비전 모델 → 영문 자연어 기술."""
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [vlm.to_b64(p) for p in image_paths],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def translate_ko(host: str, model: str, text: str) -> str:
    """영문 기술 → 한국어 번역 (표시 전용)."""
    payload = {
        "model": model,
        "prompt": TRANSLATE_PROMPT.replace("<<<TEXT>>>", text.strip()),
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return THINK_RE.sub("", r.json().get("response", "")).strip()


def extract_json(host: str, model: str, text: str) -> dict:
    """두 단계 2/2: 자연어 → 텍스트 모델 → 구조화 JSON (휴리스틱 폴백 포함)."""
    onto.OLLAMA_HOST = f"{host}/api/generate"
    onto.MODEL = model
    return onto.call_llm(text)


def save_text(path: Path, text: str) -> None:
    """내용이 바뀐 경우에만 기록 (rerun마다 같은 파일을 다시 쓰지 않도록)."""
    if not (path.exists() and path.read_text(encoding="utf-8") == text):
        path.write_text(text, encoding="utf-8")


def reset_results() -> None:
    """단계 결과 초기화 — 앞 단계를 다시 돌리면 뒤 단계 결과는 무효."""
    st.session_state.description = None
    st.session_state.description_ko = None
    st.session_state.data = None


# ---------------------------------------------------------------- sidebar
st.sidebar.header("⚙️ 설정")
mode = st.sidebar.radio("파이프라인 모드", [MODE_ONE, MODE_TWO])
host = st.sidebar.text_input("Ollama Host", value=vlm.HOST)
if mode == MODE_ONE:
    vision_model = st.sidebar.text_input("Vision 모델", value=vlm.MODEL)
else:
    vision_model = st.sidebar.text_input("Vision 모델", value=desc.MODEL)
    text_model = st.sidebar.text_input("Text 모델", value=onto.MODEL)
sensor = st.sidebar.text_input("Sensor IRI", value="http://k.fc/onto/cctv#L010009")
obs_time = st.sidebar.text_input("관측 시각 (ISO8601)", value="2025-10-17T14:30:00Z")
save_files = st.sidebar.checkbox("결과를 llm/result_* 에 저장", value=True)

if ollama_up(host):
    st.sidebar.success(f"Ollama 연결됨 · {host}")
else:
    st.sidebar.error(f"Ollama 미연결 · {host}\n`ollama serve` 실행 필요")


# ---------------------------------------------------------------- state
# 버튼을 누를 때마다 스크립트가 재실행되므로 단계 결과는 세션에 보관한다.
st.session_state.setdefault("description", None)
st.session_state.setdefault("description_ko", None)
st.session_state.setdefault("data", None)
st.session_state.setdefault("mode_prev", mode)
if st.session_state.mode_prev != mode:      # 모드를 바꾸면 이전 결과는 무효
    st.session_state.mode_prev = mode
    reset_results()


# ---------------------------------------------------------------- header + images
st.title("🛰️ CCTV 스냅샷 → 온톨로지")
if mode == MODE_ONE:
    st.caption("이미지에서 비전 모델로 SOSA 온톨로지를 바로 추출하는 단일 단계 파이프라인")
else:
    st.caption("이미지를 자연어로 기술하고, 그 자연어에서 SOSA 온톨로지를 추출하는 두 단계 파이프라인 "
               "— 각 단계를 버튼으로 따로 지시합니다")

st.subheader("1️⃣ 캡처 이미지")
image_paths = sorted(SHOTS.glob("shot_*.jpg"))
if not image_paths:
    st.warning(f"이미지를 찾을 수 없습니다: {SHOTS}/shot_*.jpg")
else:
    cols = st.columns(len(image_paths))
    for col, p in zip(cols, image_paths):
        col.image(str(p), caption=p.name, width="stretch")

st.divider()


# ---------------------------------------------------------------- pipeline
if mode == MODE_ONE:
    # 2) 이미지 → 구조화 JSON (단일 단계)
    st.subheader("2️⃣ 온톨로지 추출 — 이미지 → 구조화")
    if st.button("▶️ 파이프라인 시작", type="primary", width="stretch",
                 disabled=not image_paths):
        reset_results()
        with st.status("이미지에서 속성을 직접 추출하는 중…", expanded=True) as s:
            try:
                st.session_state.data = extract_from_images(host, vision_model, image_paths)
                s.update(label="온톨로지 추출 완료 ✅", state="complete")
            except requests.RequestException as e:
                s.update(label="온톨로지 추출 실패 ❌", state="error")
                st.error(f"Ollama 호출 실패: {e}")
                st.stop()
        st.balloons()
else:
    # 2) 이미지 → 자연어 기술 (첫 번째 지시)
    st.subheader("2️⃣ 자연어 기술")
    if st.button("📝 자연어 기술 시작", type="primary", width="stretch",
                 disabled=not image_paths):
        reset_results()
        with st.status("이미지를 분석해 자연어로 기술하는 중…", expanded=True) as s:
            try:
                st.session_state.description = describe_images(
                    host, vision_model, image_paths, desc.PROMPT_EN)
                s.update(label="자연어 기술 완료 ✅", state="complete")
            except requests.RequestException as e:
                s.update(label="자연어 기술 실패 ❌", state="error")
                st.error(f"Ollama 호출 실패: {e}")
                st.stop()
        with st.status("한국어로 번역하는 중…", expanded=False) as s:
            try:
                st.session_state.description_ko = translate_ko(
                    host, text_model, st.session_state.description)
                s.update(label="한국어 번역 완료 ✅", state="complete")
            except requests.RequestException as e:
                # 번역은 표시 전용이므로 실패해도 온톨로지 변환은 그대로 진행한다.
                s.update(label="한국어 번역 실패 ⚠️", state="error")
                st.warning(f"한국어 번역 실패 (영문 원문으로 계속 진행): {e}")

    description = st.session_state.description
    if description:
        st.markdown("**🇺🇸 영문 기술** — 온톨로지 변환에 사용되는 원문")
        st.write(description)

        description_ko = st.session_state.description_ko
        st.markdown("**🇰🇷 한국어 번역** — 표시 전용, 온톨로지 변환에는 쓰이지 않음")
        if description_ko:
            st.write(description_ko)
        else:
            st.caption("⚠️ 한국어 번역 없음 (영문 원문으로 진행)")

        if save_files:
            saved = ["llm/result_en.txt"]
            save_text(LLM / "result_en.txt", description)
            if description_ko:
                save_text(LLM / "result_ko.txt", description_ko)
                saved.append("llm/result_ko.txt")
            st.caption("저장됨: " + " · ".join(saved))

        # 3) 자연어 → 구조화 JSON (두 번째 지시 — 명시적으로 눌러야 시작)
        st.subheader("3️⃣ 온톨로지 추출 — 구조화")
        if st.button("🧩 온톨로지 변환 시작", type="primary", width="stretch"):
            st.session_state.data = None
            # 입력은 영문 원문(description)이다. 한국어 번역본은 넘기지 않는다.
            with st.status("자연어에서 속성을 추출하는 중…", expanded=True) as s:
                try:
                    st.session_state.data = extract_json(host, text_model, description)
                    s.update(label="구조화 추출 완료 ✅", state="complete")
                except requests.RequestException as e:
                    s.update(label="구조화 추출 실패 ❌", state="error")
                    st.error(f"Ollama 호출 실패: {e}")
                    st.stop()
            st.balloons()
    else:
        st.info("자연어 기술을 먼저 실행하면 아래에 **온톨로지 변환** 버튼이 나타납니다.")


# ---------------------------------------------------------------- result
data = st.session_state.data
if data:
    c1, c2, c3 = st.columns(3)
    c1.metric("☁️ 날씨 (Weather)", data.get("weather", "?"))
    c2.metric("🚶 혼잡도 (Congestion)", data.get("pedestrian_congestion", "?"))
    c3.metric("🚗 교통량 (Traffic)", data.get("traffic_volume", "?"))
    st.json(data)

    # 마지막) SOSA TTL
    step_no = "3️⃣" if mode == MODE_ONE else "4️⃣"
    st.subheader(f"{step_no} 온톨로지 TTL (SOSA Observation)")
    ttl = onto.to_ttl(data, sensor, obs_time)
    st.code(ttl, language="turtle")
    st.download_button("⬇️ result.ttl 다운로드", ttl, file_name="result.ttl", mime="text/turtle")
    if save_files:
        save_text(LLM / "result.ttl", ttl)
        st.caption("저장됨: llm/result.ttl")

# CCTV → 시맨틱 RDF 파이프라인

전국 OpenData CCTV 위치 데이터와 CCTV 스냅샷 영상을 **RDF 지식그래프(TTL)** 로 변환하는 파이프라인입니다.
좌표는 GeoSPARQL, 영상 분석 결과(날씨·혼잡도·교통량)는 SOSA/SSN 온톨로지로 모델링합니다.

영상 분석은 두 가지 파이프라인을 제공합니다:

- **단일 단계** — 비전 모델이 이미지에서 온톨로지 속성을 바로 추출
- **두 단계** — 이미지를 자연어로 기술한 뒤, 그 자연어에서 속성을 추출

두 파이프라인의 모든 변환 단계는 같은 모델 `qwen3.8:27b-mlx`(vision·tools·thinking)을 사용하며,
단계 간 차이는 모델이 아니라 프롬프트에서 옵니다.

## 구성

```
cctv/
  OpenDataCCTV.csv      입력: 전국 CCTV 위치 (13,246건)
  csv_to_cctv_ttl.py    CSV → GeoSPARQL TTL 변환기 (표준 라이브러리만 사용)
  cctv.ttl              출력: 위치 그래프 (79,482 triples)
  insert_stream.sh      Fuseki 트리플스토어에 스트림 URL INSERT (SPARQL Update)
llm/
  shots/                입력: 시퀀스 CCTV 스냅샷 5장
  image_to_sosa_ttl.py  [단일 단계] 이미지 5장 → 비전 모델 → JSON → SOSA Observation TTL
  cctv_describe_en.py   [두 단계 1/2] 이미지 5장 → 비전 모델 → 영문 상황 설명
  text_to_sosa_ttl.py   [두 단계 2/2] 영문 설명 → 텍스트 추출 → JSON → SOSA Observation TTL
  result_en.txt         출력: 영문 설명 (두 단계 모드)
  result.ttl            출력: 관측 그래프 (Congestion/TrafficVolume/WeatherCondition)
  requirements.txt      Python 의존성
app.py                  Streamlit UI (이미지→온톨로지 시각화, 단일/두 단계 모드 선택)
run.sh                  전체 오케스트레이터
```

## 파이프라인 흐름

```
CSV ──csv_to_cctv_ttl──▶ cctv.ttl (위치/GeoSPARQL) ──────────────────────┐
                                                                         ├─▶ Fuseki 트리플스토어
[단일 단계] shots/*.jpg ──image_to_sosa──────────────▶ result.ttl ───────┤
[두 단계]   shots/*.jpg ─describe─▶ 영문 설명 ─text_to_sosa─▶ result.ttl (관측/SOSA)
```

## 사전 요구사항

- Python 3.9+
- [Ollama](https://ollama.com) 0.32.12+ + 모델 (LLM 단계용, 자동 pull)
  - 전 단계 공통: `qwen3.8:27b-mlx` (약 18 GB)
- Java 17+ — 번들된 Apache Jena **Fuseki 6.1.0** (`fuseki/`) 구동용 (트리플스토어 단계용)

## 빠른 시작

```bash
./run.sh setup     # .venv 생성 + 의존성 설치
./run.sh csv       # CSV → cctv/cctv.ttl  (Ollama 불필요)
./run.sh llm       # [단일 단계] 스냅샷 → result.ttl  (Ollama 필요, 모델 자동 pull)
./run.sh llm2      # [두 단계] 스냅샷 → result_en.txt → result.ttl
./run.sh all       # setup + csv + llm(단일 단계)

# 개별 인자 지정
./run.sh csv  path/to/input.csv  out.ttl
./run.sh llm  "http://k.fc/onto/cctv#L010009"  "2025-10-17T14:30:00Z"  llm/shots
./run.sh llm2 "http://k.fc/onto/cctv#L010009"  "2025-10-17T14:30:00Z"  llm/shots
```

각 단계는 생성한 TTL을 `rdflib`로 파싱 검증합니다.

## Streamlit UI

이미지 → 온톨로지 추출의 순차 흐름을 화면에서 확인합니다.

```bash
./run.sh ui     # http://localhost:8501  (Ollama 자동 기동)
```

사이드바의 **파이프라인 모드**에서 단일 단계 / 두 단계를 선택합니다.

화면 구성 (단일 단계):
1. **캡처 이미지** — `llm/shots/`의 스냅샷 5장을 그리드로 표시
2. **`▶️ 파이프라인 시작`** 버튼 → 아래 단계가 순차 실행
3. **온톨로지 추출** — 이미지에서 바로 뽑은 날씨/혼잡도/교통량 (메트릭 + JSON)
4. **SOSA TTL** — 최종 관측 그래프 (다운로드 가능, `llm/result.ttl` 저장)

두 단계 모드에서는 온톨로지 추출 전에 **자연어 기술**(영문 설명) 단계가 추가됩니다.
영문 기술 아래에는 한국어 번역이 함께 표시되며(표시 전용 — 온톨로지 변환에는 영문 원문만 사용),
각각 `llm/result_en.txt`, `llm/result_ko.txt`로 저장됩니다.

두 단계 모드의 각 단계는 별도 버튼(**📝 자연어 기술 시작**, **🧩 온톨로지 변환 시작**)으로 따로 지시합니다.

사이드바에서 Ollama Host·모델·Sensor IRI·관측 시각을 변경할 수 있습니다.

## CSV 컬럼 매핑

`csv_to_cctv_ttl.py`는 헤더명을 자동 인식합니다(대소문자/공백/밑줄 무시):

| 의미 | 허용 컬럼명 |
|------|-------------|
| id   | `cctvid`, `id`, `camid`, `camera_id` |
| name | `cctvname`, `name`, `label`, `title`, `cctv_nm` |
| lon  | `xcoord`, `lon`, `longitude`, `x`, `lng` |
| lat  | `ycoord`, `lat`, `latitude`, `y` |

## Fuseki 트리플스토어

Apache Jena Fuseki 6.1.0이 `fuseki/`에 번들되어 있습니다.

```bash
./run.sh fuseki    # 기동: in-memory, update 가능, 데이터셋 /fc (http://localhost:3030)
./run.sh load      # cctv.ttl + result.ttl 적재
./run.sh stream    # 스트림 URL INSERT (insert_stream.sh)
```

적재 후 SPARQL 질의 예시 — 센서 L010009의 스트림 URL과 관측값 조인:

```bash
curl -s http://localhost:3030/fc/query -H 'Accept: application/sparql-results+json' \
  --data-urlencode 'query=
PREFIX cctv: <http://k.fc/onto/cctv#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>
SELECT ?stream ?prop ?result WHERE {
  OPTIONAL { cctv:L010009 cctv:hasStreamUrl ?stream }
  OPTIONAL { ?obs sosa:madeBySensor cctv:L010009 ;
                  sosa:observedProperty ?prop ; sosa:hasResult ?result } }'
```

웹 UI: <http://localhost:3030> · 영구 저장이 필요하면 `--mem /fc` 대신 `--update --loc=run/fc /fc` 사용.

## 온톨로지 네임스페이스

| prefix | IRI |
|--------|-----|
| `cctv` | `http://k.fc/onto/cctv#` |
| `geo`  | `http://www.opengis.net/ont/geosparql#` |
| `sosa` | `http://www.w3.org/ns/sosa/` |
| `dct`  | `http://purl.org/dc/terms/` |

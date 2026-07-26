# PF 사업장 애프터케어 대시보드

공개 데이터만으로 부동산 PF(프로젝트 파이낸싱) 경공매 사업장의 **감정가·최저입찰가
경로를 시계열로 추적**하고, 실무자가 **점검이 필요한 위험 사업장을 스크리닝**할 수
있는 Streamlit 대시보드입니다.

- 대상: 전국은행연합회 공개 경공매 대상 PF 사업장 **798곳 × 17개월**(2025-01~2026-06)
- 변수: 전수 통계 검정으로 확정한 **62열 클린 패널** (원천 129열 → 근거 기반 축약)
- 통계: 패널 3층 분해(between/within/macro) + FDR 보정 전수 검정 → [docs/PHASE1_findings.md](docs/PHASE1_findings.md)

> 본 저장소의 '사업장'은 전부 공개된 경공매 대상이며 특정 기관의 보유 자산이
> 아닙니다. 모든 데이터는 공개 출처에서 수집했습니다(출처: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)).

## 빠른 시작

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## 구조

```
streamlit_app.py          # 대시보드 (개요 · 가격 시계열 · 위험 스크리닝 · 사내 결합 준비)
data/
  panel_clean.csv         # 확정 패널 4,732행 × 62열 (사업장×월×물건라인)
  site_master.csv         # 사업장 1행 요약 798곳 (주소·유형·처분결과·스크리닝 원료)
  source/                 # 패널 재생성용 원천 스냅샷 (5개 CSV)
  varrel/                 # Phase 1 전수 통계 산출물 (검정 CSV 7종 + 실행 코드)
pipeline/
  variable_catalog.json   # 변수 사전: 134개 항목 전수 keep/drop 판정과 사유
  make_catalog.py         # 판정 변경 시 카탈로그 재생성
  build_panel.py          # 카탈로그 → 패널 재빌드 (+ 사내 데이터 결합 훅)
docs/
  PHASE1_findings.md      # 통계 보고서 (방법·결과·한계·변수 확정 근거)
  GOAL.md                 # 프로젝트 5단계 목표
  INTERNAL_DATA_SPEC.md   # 사내 데이터 결합 스키마 규약
  DATA_SOURCES.md         # 수집·활용 데이터 목록
  CONTEST_SUBMISSION.md   # AI 공모전 제출 자료 초안
```

## 위험 스크리닝 로직

규칙 기반·설명 가능 스코어(가중치 조정 가능). 각 규칙은 Phase 1 통계 근거를 가집니다:
가격 소진(최저/감정 < 0.5) · 유찰 누적(≥5회) · 장기 체류(≥12개월) · 저감 반복(≥2회) ·
시장 대비 고가 유지(초과할인 > +10%p) · 감정 괴리(배수 > 5) · 지역 지가 하락 ·
수요 부재 유형(산업시설). 근거는 앱 내 '판단 규칙과 근거'와 findings 문서 §5 참조.

## 사내 데이터 확장 (Placeholder)

비공개 사내 데이터는 `docs/INTERNAL_DATA_SPEC.md` 스키마(`site_id` 또는 `address` +
선택 `month_key` + 값 컬럼)로 준비하면:

```bash
python pipeline/build_panel.py --internal 사내데이터.csv
```

값 컬럼은 자동으로 `int_` 접두사가 붙어 공개 변수와 격리됩니다. 앱의 '사내 데이터
결합(준비)' 탭에서 스키마 검증을 미리 확인할 수 있습니다.

## Streamlit Community Cloud 배포

1. 이 저장소를 GitHub에 push
2. [share.streamlit.io](https://share.streamlit.io) → **Create app** → 이 저장소 선택,
   entry point `streamlit_app.py`
3. 배포 후 **Settings → Sharing → Public** 확인 (링크 접근 허용)

앱은 저장소 내 CSV만 읽으므로 시크릿·외부 API 키가 필요 없습니다.

## 패널 재생성·통계 재실행

```bash
python pipeline/build_panel.py                 # data/source/*.csv → panel_clean/site_master
pip install scipy statsmodels lifelines        # 통계 재실행 시에만
python data/varrel/run_stats.py                # 전수 검정 재실행 (경로 상수 수정 필요)
```

## 라이선스·고지

- 코드: MIT
- 데이터: 각 공개 출처의 이용약관을 따릅니다. 본 저장소는 정보 제공 목적이며
  투자 자문이 아닙니다.

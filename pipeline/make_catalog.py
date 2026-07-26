# -*- coding: utf-8 -*-
"""variable_catalog.json 생성기.

Phase 1 전수 통계(docs/PHASE1_findings.md, data/varrel/*)에 근거한
129열 keep/drop 판정을 코드로 고정한다. 판정 변경 시 이 파일을 수정하고
재실행 → build_panel.py 가 카탈로그를 읽어 패널을 다시 만든다.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source" / "analysis_master.csv"

KEEP: dict[str, tuple[str, str]] = {}  # col -> (분류, 사유)

def _add(cols, cat, reason):
    for c in cols:
        KEEP[c] = (cat, reason)

_add(["site_id", "line_id", "month_key", "ym", "region", "sido", "sgg",
      "lawd_cd", "biz_class", "land_area_m2", "bldg_area_m2", "permit_yn",
      "constr_status", "trust", "hub_status", "lon", "lat"],
     "키·메타", "식별·필터·지도화 필수")
_add(["appraisal_mn", "min_bid_mn", "discount_ratio", "round_no", "n_rounds_m"],
     "가격 경로", "핵심 결과변수(감정가·최저가·비율·회차)")
_add(["exited", "reactivated", "excess_pp_med",
      "appr_vs_rtms_dae_3m", "appr_unit_land_mn_m2", "minbid_unit_land_mn_m2",
      "stcns_delay_days", "months_permit_idle", "kfb_understated",
      "pms_after_exit", "stcns_after_exit"],
     "결과·상태", "이탈/정상화/감정배수/착공지연 — [C][S] 유의 또는 스크리닝 사용")
_add(["base_rate", "spread_AA_KTB", "spread_BBB_KTB", "bank_corp_loan_rate",
      "base_rate_chg_12m"],
     "금리·신용", "[M] 스프레드~저감 차분 유의 · 기준금리는 이론 필수 · 대출금리 대표 1")
_add(["cci_matched", "cci_yoy_pct"],
     "공사비", "업종 매칭 지수 + YoY 대표 (6분류 원계열은 총지수와 ρ>0.92)")
_add(["land_chg_pct", "land_chg_cum12_pct", "apt_idx_yoy_pct",
      "unsold_total", "unsold_pct_completed",
      "vac_office", "yield_office", "rentidx_office"],
     "지역 부동산", "지가누적 Cox HR 1.34(p=2.6e-7) · 아파트YoY [W] 약신호 · 미분양/공실 이론 필수")
_add(["rtms_land_dae_unit_3m", "rtms_land_dae_n_3m", "rtms_apt_n_3m",
      "rtms_apt_n_yoy_pct", "rtms_fac_n_yoy_pct", "rtms_nrg_n_yoy_pct",
      "rtms_land_n_yoy_pct"],
     "실거래", "감정배수 분모·거래량 YoY(산업 수요 신호) — 3m 풀링 대표만")
_add(["ah_under_ratio", "kiscon_amt_priv_yoy_pct", "hug_sago_n"],
     "수요·공급 흐름", "미달비율(주거 수요)·민간계약 YoY 대표·HUG 사고이력")

DROP_REASON = {
    "bank_loan_rate_all": "bank_corp_loan_rate와 ρ>0.95 중복",
    "bank_facility_loan_rate": "bank_corp_loan_rate와 ρ>0.9 중복",
    "nonbank_corp_loan_rate": "대표 대출금리와 중복",
    "corp_bond_AA3y": "spread_AA_KTB(+base_rate)로 재구성 가능",
    "corp_bond_BBB3y": "spread_BBB_KTB로 재구성 가능",
    "ktb_3y": "base_rate·스프레드와 ρ>0.9",
    "cd_91d": "base_rate와 ρ>0.95",
    "cci_total": "cci_matched·cci_yoy_pct로 대체(ρ>0.92)",
    "cci_bldg": "cci_total과 ρ>0.95", "cci_resi": "cci_total과 ρ>0.95",
    "cci_nonresi": "cci_total과 ρ>0.95", "cci_plant": "cci_total과 ρ>0.9",
    "cci_civil": "cci_total과 ρ>0.95",
    "natl_ffilled": "내부 플래그", "cci_matched_flag": "내부 플래그",
    "house_idx": "apt_idx 계열과 중복·주택종합은 아파트에 후행",
    "house_idx_yoy_pct": "apt_idx_yoy_pct와 중복",
    "apt_idx": "수준값 — YoY만 사용(수준은 지역 고정효과와 혼동)",
    "house_idx_src": "내부 플래그", "apt_idx_src": "내부 플래그",
    "vac_midlarge": "vac_office와 동행", "rentidx_midlarge": "rentidx_office와 동행",
    "yield_midlarge": "yield_office와 동행",
    "capret_office": "yield_office와 중복", "capret_midlarge": "yield 계열 중복",
    "rent_yq_used": "내부 키",
    "rtms_land_n": "3m 풀링으로 대체", "rtms_land_med_unit": "3m 풀링으로 대체",
    "rtms_land_n_3m": "'대' 지목 계열로 대체", "rtms_land_unit_3m": "'대' 지목 계열로 대체",
    "rtms_land_dae_n": "3m 풀링으로 대체", "rtms_land_dae_med_unit": "3m 풀링으로 대체",
    "rtms_nrg_n": "YoY만 사용", "rtms_nrg_med_unit": "커버리지·해석력 낮음",
    "rtms_nrg_n_3m": "YoY만 사용", "rtms_nrg_unit_3m": "커버리지 낮음",
    "rtms_apt_n": "3m 풀링으로 대체", "rtms_apt_med_unit": "지수(apt_idx_yoy)와 중복",
    "rtms_apt_unit_3m": "지수와 중복",
    "rtms_fac_n": "YoY만 사용", "rtms_fac_med_unit": "희소(단가 92%는 3m 풀링도 0건 지역)",
    "rtms_fac_n_3m": "YoY만 사용", "rtms_fac_unit_3m": "희소",
    "unsold_completed": "unsold_total·pct로 재구성 가능",
    "minbid_vs_rtms_dae_3m": "appr_vs와 discount_ratio로 재구성 가능",
    "appr_vs_rtms_all_3m": "'대' 지목 기준이 정본(전체 지목은 구성 잡음)",
    "minbid_vs_rtms_all_3m": "동상",
    "sido_s": "sido와 중복", "biz5": "파생 편의 컬럼(빌더에서 재생성)",
    "hug_sago_sgg_flag": "hug_sago_n>0과 동치",
    "hug_sago_last_yr": "2020년 이전 공개분만 — 시의성 없음",
    "hug_sago_amt_mn": "hug_sago_n과 ρ 높음·결측 다수",
    "ah_n_pblanc": "kiscon 계열과 ρ 0.89 — 활동 축 대표는 kiscon 유지",
    "ah_supply_sum": "ah_under_ratio 대비 추가 정보 없음",
    "ah_rate_med": "ah_under_ratio와 중복(역방향)",
    "ah_sale_unit_med": "커버리지 낮음",
    "kiscon_cnt_pub": "amt_priv_yoy 대표로 축약", "kiscon_cnt_indiv": "동상",
    "kiscon_cnt_priv": "동상", "kiscon_cnt_all": "동상",
    "kiscon_amt_pub": "동상", "kiscon_amt_indiv": "동상",
    "kiscon_amt_priv": "수준값 — YoY만 사용", "kiscon_amt_all": "동상",
    "kiscon_cnt_priv_yoy_pct": "amt YoY와 중복",
    "ap_pms_day": "날짜형 — stcns_delay_days·months_permit_idle로 대체",
    "ap_stcns_day": "동상", "ap_useapr_day": "동상", "br_useapr_day": "동상",
    "exit_month": "site_master로 이동(월 패널에는 exited로 충분)",
    "line_match_method": "내부 계보", "line_ambiguous": "내부 계보",
    "yq": "ym으로 충분",
}

def main():
    cols = list(pd.read_csv(SRC, nrows=1).columns)
    rows = []
    for c in cols:
        if c in KEEP:
            cat, reason = KEEP[c]
            rows.append(dict(name=c, source="analysis_master", decision="keep",
                             category=cat, reason=reason))
        else:
            rows.append(dict(name=c, source="analysis_master", decision="drop",
                             category="탈락",
                             reason=DROP_REASON.get(c, "결과변수와 유의 관계 없음")))
    # 파생·외부 결합 컬럼 선언 (빌더가 생성)
    rows += [
        dict(name="biz_type", source="kfb_sites_master", decision="keep",
             category="키·메타", reason="세부 유형 필터(아파트/오피스텔/물류센터/공장 등)"),
        dict(name="ev_bid_cut", source="kfb_events(derived)", decision="keep",
             category="사건", reason="당월 최저가 인하 발생(suspect 제외)"),
        dict(name="ev_reappraisal", source="kfb_events(derived)", decision="keep",
             category="사건", reason="당월 재감정 발생"),
        dict(name="ev_bid_reset", source="kfb_events(derived)", decision="keep",
             category="사건", reason="당월 가격 리셋 발생"),
        # ↓ 사내 데이터 확장 슬롯 — INTERNAL_DATA_SPEC.md 스키마로 결합
        dict(name="int_*", source="internal(placeholder)", decision="reserved",
             category="사내 확장", reason="사내 여신/관리 데이터 결합 시 int_ 접두로 자동 편입"),
    ]
    out = ROOT / "pipeline" / "variable_catalog.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    kept = [r for r in rows if r["decision"] == "keep"]
    print(f"catalog: {len(rows)} entries, keep {len(kept)}")

if __name__ == "__main__":
    main()

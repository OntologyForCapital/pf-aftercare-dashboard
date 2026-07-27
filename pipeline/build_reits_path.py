# -*- coding: utf-8 -*-
"""리츠(정상 자산) 정본 평가경로 시계열 구축.

원천: ORIG/data/processed/reits_property_values.csv (물건 1,206개 x 기간, 12,731행)
산출:
  DASH/data/location/reits_value_path.csv  - 물건 x 기간 패널(파생 포함)
  DASH/data/location/reits_group_path.csv  - 권역 x 유형 x 연도 집계

핵심 원칙
---------
* book_value 변화는 감가상각·CAPEX 혼입 -> '평가' 변화가 아님(bv_chg는 참고 지표).
* 평가 신호는 (1) reval_land/bldg 변동(재평가 이벤트) (2) impair_acc 증가(손상 이벤트).
* 기간 축 실측: gi=회계 기수(반기 결산 리츠 다수), qu=기수 내 분기(1<2<3<결산기).
  물건별 시계열 순서는 (gi_num, qu_rank)로 정의(연도 걸침 기수도 안전).
* 자릿수 이상: 일부 원천 파일이 백만원이 아닌 원 단위(1e6배) 또는 천원 단위(1e3배)로
  기록 -> 시계열 기준값 대비 배율 탐지 후 행 단위 보정(scale_factor 컬럼에 기록).
"""
import re
import numpy as np
import pandas as pd

ORIG = "/Users/kdh/Desktop/Pilot/Real_estate_after_care_claude"
DASH = "/Users/kdh/Desktop/Pilot/pf-aftercare-dashboard"
SRC = f"{ORIG}/data/processed/reits_property_values.csv"
OUT_PANEL = f"{DASH}/data/location/reits_value_path.csv"
OUT_GROUP = f"{DASH}/data/location/reits_group_path.csv"
LOC_FILE = f"{DASH}/data/location/reits_location.csv"

MONEY_COLS = [
    "acq_land_mn", "acq_bldg_mn", "capex_land_mn", "capex_bldg_mn",
    "reval_land_mn", "reval_bldg_mn", "dep_acc_mn", "impair_acc_mn",
    "book_value_mn",
]
QU_RANK = {"1분기": 1, "2분기": 2, "3분기": 3, "결산기": 4}
EVENT_THRESH_MN = 1.0  # 1백만원 초과 변동만 이벤트로 인정(부동소수 노이즈 차단)

# ---------------------------------------------------------------- sido / region
SIDO_PATTERNS = [
    (r"서울(특별시|시)?", "서울"), (r"부산(광역시|시)?", "부산"),
    (r"대구(광역시|시)?", "대구"), (r"인천(광역시|시)?", "인천"),
    (r"광주광역시", "광주"), (r"대전(광역시|시)?", "대전"),
    (r"울산(광역시|시)?", "울산"), (r"세종(특별자치시|시)?", "세종"),
    (r"경기도?", "경기"), (r"강원(특별자치도|도)?", "강원"),
    (r"충청북도|충북", "충북"), (r"충청남도|충남", "충남"),
    (r"전라북도|전북특별자치도|전북", "전북"), (r"전라남도|전남", "전남"),
    (r"경상북도|경북", "경북"), (r"경상남도|경남", "경남"),
    (r"제주(특별자치도|도특별자치도|도|시)?", "제주"),
]
# 시도명이 생략된 주소용 키워드(실측된 미해석 문자열 기반)
CITY_HINTS = [
    (r"김포|파주|화성|동탄|남양주|다산동|성남|수원|고양|시흥|안성|평택|부천|안양|용인|하남|과천|의왕|군포|광명|구리|오산|이천시|양주|의정부|포천|양평|여주", "경기"),
    (r"행정중심복합도시|행복도시", "세종"),
    (r"창원|김해|양산|거제|진주|함안", "경남"),
    (r"경산|경주|포항|구미", "경북"),
    (r"천안|아산", "충남"),
    (r"효천", "광주"),  # 광주 효천1지구
    (r"제물포", "인천"),
    (r"마곡|성수", "서울"),
    (r"서초구|강남구|송파구|강동구|관악구|동작구|영등포구|금천구|구로구|양천구|강서구|마포구|서대문구|은평구|노원구|도봉구|강북구|성북구|중랑구|동대문구|광진구|성동구|용산구|중구 |종로구", "서울"),
]
CAPITAL = {"서울", "경기", "인천"}


def parse_sido(text):
    if not isinstance(text, str):
        return np.nan
    s = text.strip()
    for pat, sido in SIDO_PATTERNS:
        if re.match(pat, s):
            return sido
    for pat, sido in SIDO_PATTERNS:  # 문자열 중간 등장 허용
        if re.search(pat, s):
            return sido
    for pat, sido in CITY_HINTS:
        if re.search(pat, s):
            return sido
    return np.nan


# ---------------------------------------------------------------- type mapping
def map_type(t):
    if not isinstance(t, str):
        return "기타"
    if t.startswith("주택"):
        return "주거"
    return {"오피스": "업무", "리테일": "상업", "물류": "산업", "호텔": "숙박"}.get(t, "기타")


# ---------------------------------------------------------------- scale fixing
def fix_scale(df):
    """단위 오기(원/천원 단위 기록) 값을 컬럼 단위로 보정.

    혼합 단위 행(예: acq는 원 단위, bv는 백만원 단위가 한 행에 공존)이 실재하므로
    행 일괄 배율이 아니라 '값 단위'로 판정한다.
      1) 비율 판정: 시계열 내 해당 컬럼의 정상 대역([1, 5e6]백만원) 중앙값 대비
         |값| 배율이 [3e5, 3e6] -> 1e6, [300, 3000] -> 1e3
      2) 절대값 가드: 보정 후에도 |값| > 1e7백만원(10조원)은 실물 불가능
         -> |값|/1e6(우선) 또는 /1e3이 [0.1, 5e6]에 들어오면 해당 배율 적용
    scale_factor 컬럼에는 행 내 최대 적용 배율을 기록한다.
    """
    row_fac = pd.Series(1.0, index=df.index)
    n_fixed_vals = 0
    for c in MONEY_COLS:
        v = df[c]
        a = v.abs()
        ref = (a.where((a >= 1) & (a <= 5e6))
                .groupby(df["prop_uid"]).transform("median"))
        r = a / ref
        fac = pd.Series(1.0, index=df.index)
        fac[(r >= 3e5) & (r <= 3e6)] = 1e6
        fac[(r >= 300) & (r <= 3000)] = 1e3
        # 절대값 가드
        big = (a / fac > 1e7) & a.notna()
        fac[big & (a / 1e6).between(0.1, 5e6)] = 1e6
        fac[big & ~(a / 1e6).between(0.1, 5e6) & (a / 1e3).between(0.1, 5e6)] = 1e3
        df[c] = v / fac
        n_fixed_vals += int((fac > 1).sum())
        row_fac = np.maximum(row_fac, fac)
    df["scale_factor"] = row_fac
    return df, n_fixed_vals


# ---------------------------------------------------------------- main
def main():
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    df["gi_num"] = df["gi"].astype(str).str.extract(r"(\d+)").astype(float)
    df["qu_rank"] = df["qu"].map(QU_RANK)
    # 엑셀 CR 아티팩트(_x000D_)·개행 정리
    df["property"] = (df["property"].astype(str)
                      .str.replace("_x000D_", " ", regex=False)
                      .str.replace(r"\s+", " ", regex=True).str.strip())
    df["location"] = (df["location"].astype(str)
                      .str.replace("_x000D_", " ", regex=False)
                      .str.replace(r"\s+", " ", regex=True).str.strip()
                      .replace("nan", np.nan))
    # 합계·참조오류 행 제외(물건이 아님), 무명 물건은 표기만 정리
    junk = df["property"].str.fullmatch(r"합\s?계|소계|총계|계|#REF!")
    n_junk = int(junk.sum())
    df = df[~junk].copy()
    df.loc[df["property"] == "nan", "property"] = "(무명)"
    df["prop_uid"] = df["reits"].str.strip() + "|" + df["property"]

    # --- 중복 제거: 동일 (물건, 기수, 분기)에 복수 행 -> bv 비결측 우선, 후행(idx 큰) 행 유지
    n0 = len(df)
    df = (df.sort_values(["prop_uid", "gi_num", "qu_rank",
                          "book_value_mn", "idx"], na_position="first")
            .drop_duplicates(subset=["prop_uid", "gi_num", "qu_rank"], keep="last"))
    n_dedup = n0 - len(df)

    # --- 자릿수 보정 (컬럼 단위 배율 탐지)
    df, n_scale_fixed = fix_scale(df)

    # --- 회계 구조: 연간 기수 증가 속도로 결산 주기 추정(연 1회=연간, 2회=반기, 4회=분기)
    # 양끝 연도 기준 기울기(연중 부분 관측 편향이 연도별 차분 중앙값보다 작음)
    ymax = df.groupby(["reits", "year"])["gi_num"].max().reset_index()
    ymax = ymax.sort_values(["reits", "year"])
    ends = ymax.groupby("reits").agg(g0=("gi_num", "first"), g1=("gi_num", "last"),
                                     y0=("year", "first"), y1=("year", "last"))
    slope = ((ends["g1"] - ends["g0"]) / (ends["y1"] - ends["y0"])).replace(
        [np.inf, -np.inf], np.nan)
    n_gi_year = df.groupby(["reits", "year"])["gi_num"].nunique().groupby("reits").max()
    # 2분기/3분기 라벨은 연간 결산 리츠에서만 등장(반기/분기 리츠는 1분기·결산기만 보고)
    has23 = df["qu"].isin(["2분기", "3분기"]).groupby(df["reits"]).any()

    def classify(r):
        s, n2, h = slope.get(r, np.nan), n_gi_year.get(r, 1), has23.get(r, False)
        if np.isfinite(s):
            if s >= 3:
                return 4
            if s >= 1.4:  # 부분 관측 연도 탓에 반기 리츠 기울기가 1.5까지 내려옴
                return 2
            return 1 if h else 2
        # 관측 1개년뿐인 리츠: 해당 연도 기수 개수·라벨로 추정
        if n2 >= 3:
            return 4
        if n2 == 2:
            return 2
        return 1 if h else 2

    gi_per_year = pd.Series({r: classify(r) for r in df["reits"].unique()})
    df["gi_per_year"] = df["reits"].map(gi_per_year)

    # --- 절대 분기 격자 추정: abs_q = base + (gi-1)*L + offset(qu)
    L = (4 // df["gi_per_year"]).astype(int)  # 기수당 분기 수(연간4/반기2/분기1)
    off_semi = df["qu"].map({"1분기": 1, "2분기": 2, "3분기": 2, "결산기": 2})
    offset = np.select(
        [df["gi_per_year"] == 1, df["gi_per_year"] == 2],
        [df["qu_rank"], off_semi], default=1)  # 분기결산 리츠는 기=1분기 -> offset 1
    struct = (df["gi_num"] - 1) * L + offset
    anchor = df["year"] * 4 + 2.5 - struct
    base = anchor.groupby(df["reits"]).transform("median")
    # 주의: np.round는 은행가 반올림이라 base가 x.5일 때 인접 기간이 같은 분기로
    # 붕괴함 -> half-up(floor(x+0.5))으로 격자 단조성 보존
    df["abs_q_est"] = np.floor(base + struct + 0.5).astype("Int64")  # 서기 0년 기준 분기 인덱스
    df["cal_year_est"] = (df["abs_q_est"] - 1) // 4
    df["cal_q_est"] = (df["abs_q_est"] - 1) % 4 + 1

    # --- 물건별 시계열 정렬 + 파생
    df = df.sort_values(["prop_uid", "gi_num", "qu_rank"]).reset_index(drop=True)
    g = df.groupby("prop_uid")
    df["period_seq"] = g.cumcount() + 1
    df["n_periods"] = g["prop_uid"].transform("size")
    df["gap_quarters"] = g["abs_q_est"].diff().astype("Float64")
    df["gap_months"] = df["gap_quarters"] * 3

    # book value 변화율(감가·CAPEX 혼입 -> 평가 변화 아님)
    prev_bv = g["book_value_mn"].shift()
    df["bv_prev_mn"] = prev_bv
    df["bv_chg_pct"] = np.where(
        (prev_bv > 0) & df["book_value_mn"].notna(),
        (df["book_value_mn"] / prev_bv - 1) * 100, np.nan)

    # 평가 이벤트 판정 가능 전이: 양쪽 기간 모두 bv가 보고된(온전히 파싱된) 행일 것.
    # bv 결측 행은 결산 파일 부분 파싱이 많아 reval/impair 결측이 '미기재'와 섞여
    # fillna(0) 시 가짜 이벤트(값 출몰 플래핑)를 만든다 -> 게이트로 차단.
    bv_ok = df["book_value_mn"].notna()
    df["eval_pair_ok"] = (bv_ok & bv_ok.groupby(df["prop_uid"]).shift()
                          ).fillna(False).astype(int)

    # 재평가 이벤트: reval 합계(결측=재평가 미적용으로 0 처리)의 기간 간 변동
    reval = df[["reval_land_mn", "reval_bldg_mn"]].fillna(0).sum(axis=1)
    df["reval_total_mn"] = reval
    df["d_reval_mn"] = g["reval_total_mn"].diff()
    ok = df["eval_pair_ok"] == 1
    df["reval_event"] = ((df["d_reval_mn"].abs() > EVENT_THRESH_MN) & ok).astype(int)
    df["reval_down_event"] = ((df["d_reval_mn"] < -EVENT_THRESH_MN) & ok).astype(int)

    # 손상 이벤트: impair_acc(결측=손상 없음으로 0 처리) 증가
    df["impair_filled_mn"] = df["impair_acc_mn"].fillna(0)
    df["d_impair_mn"] = g["impair_filled_mn"].diff()
    df["impair_event"] = ((df["d_impair_mn"] > EVENT_THRESH_MN) & ok).astype(int)

    # 첫 기간은 전이가 없음
    first = df["period_seq"] == 1
    df.loc[first, ["d_reval_mn", "d_impair_mn"]] = np.nan
    df["has_transition"] = (~first).astype(int)

    # --- 지역 부착: location 파싱 -> 물건 내 최빈값 전파 -> 지오코딩 파일 주소 폴백
    df["sido"] = df["location"].map(parse_sido)
    modal = (df.dropna(subset=["sido"]).groupby("prop_uid")["sido"]
               .agg(lambda s: s.mode().iat[0]))
    df["sido"] = df["sido"].fillna(df["prop_uid"].map(modal))
    lo = pd.read_csv(LOC_FILE, encoding="utf-8-sig")
    lo["addr"] = lo["pid"].astype(str).str.split("|").str[-1]
    lo["sido_lo"] = lo["addr"].map(parse_sido)
    lo_map = (lo.dropna(subset=["sido_lo"]).drop_duplicates("property")
                .set_index("property")["sido_lo"])
    df["sido"] = df["sido"].fillna(df["property"].map(lo_map))
    # 최종 폴백: 물건명 자체에서 지역 추출(예: '천안시 성정동 ...', '경산GS물류센터')
    df["sido"] = df["sido"].fillna(df["property"].map(parse_sido))
    df["region"] = np.where(df["sido"].isin(CAPITAL), "수도권", "지방")
    df.loc[df["sido"].isna(), "region"] = np.nan

    # --- 유형 매핑
    df["type_pf"] = df["invest_target"].map(map_type)

    # --- 패널 저장
    panel_cols = [
        "prop_uid", "reits", "property", "year", "gi", "qu", "gi_num", "qu_rank",
        "gi_per_year", "cal_year_est", "cal_q_est", "abs_q_est",
        "period_seq", "n_periods", "gap_quarters", "gap_months",
        "invest_target", "type_pf", "location", "sido", "region",
        "book_value_mn", "bv_prev_mn", "bv_chg_pct", "scale_factor",
        "reval_land_mn", "reval_bldg_mn", "reval_total_mn", "d_reval_mn",
        "reval_event", "reval_down_event",
        "impair_acc_mn", "impair_filled_mn", "d_impair_mn", "impair_event",
        "eval_pair_ok",
        "dep_acc_mn", "capex_land_mn", "capex_bldg_mn",
        "acq_land_mn", "acq_bldg_mn", "lease_rate_pct",
        "has_transition", "src",
    ]
    df[panel_cols].to_csv(OUT_PANEL, index=False, encoding="utf-8-sig")

    # --- 연도말 bv(관측 마지막 값, bv>0) 기반 YoY
    ylast = (df[df["book_value_mn"] > 0]
             .sort_values(["prop_uid", "gi_num", "qu_rank"])
             .groupby(["prop_uid", "year"], as_index=False)
             .agg(bv_end=("book_value_mn", "last"),
                  region=("region", "last"), type_pf=("type_pf", "last")))
    ylast = ylast.sort_values(["prop_uid", "year"])
    gy = ylast.groupby("prop_uid")
    ok = gy["year"].diff() == 1
    ylast["bv_yoy_pct"] = np.where(ok, (ylast["bv_end"] / gy["bv_end"].shift() - 1) * 100,
                                   np.nan)

    # --- 그룹 집계: 권역 x 유형 x 연도
    tr = df[df["has_transition"] == 1].copy()
    tr["months_eval"] = tr["gap_months"].where(tr["eval_pair_ok"] == 1)
    agg = (tr.groupby(["region", "type_pf", "year"], dropna=False)
             .agg(n_prop=("prop_uid", "nunique"),
                  n_transitions=("has_transition", "sum"),
                  n_eval_pairs=("eval_pair_ok", "sum"),
                  months_obs_sum=("gap_months", "sum"),
                  months_eval_sum=("months_eval", "sum"),
                  reval_events=("reval_event", "sum"),
                  reval_down_events=("reval_down_event", "sum"),
                  impair_events=("impair_event", "sum"))
             .reset_index())
    yoy = (ylast.dropna(subset=["bv_yoy_pct"])
                .groupby(["region", "type_pf", "year"], dropna=False)
                .agg(n_prop_yoy=("prop_uid", "nunique"),
                     bv_yoy_med_pct=("bv_yoy_pct", "median"))
                .reset_index())
    grp = agg.merge(yoy, on=["region", "type_pf", "year"], how="outer")
    for num, den, out in [("reval_events", "n_eval_pairs", "reval_event_rate_pct"),
                          ("reval_down_events", "n_eval_pairs", "reval_down_rate_pct"),
                          ("impair_events", "n_eval_pairs", "impair_event_rate_pct")]:
        grp[out] = grp[num] / grp[den] * 100
    grp["downval_events"] = grp["reval_down_events"] + grp["impair_events"]
    grp["downval_rate_per_month_pct"] = grp["downval_events"] / grp["months_eval_sum"] * 100
    grp = grp.sort_values(["region", "type_pf", "year"])
    grp.to_csv(OUT_GROUP, index=False, encoding="utf-8-sig")

    # --- 콘솔 리포트
    print(f"panel rows={len(df)} (합계/오류행 {n_junk} + dedup {n_dedup} 제거), "
          f"props={df['prop_uid'].nunique()}")
    print(f"scale fixed values={n_scale_fixed}, rows={int((df['scale_factor']>1).sum())} "
          f"(1e3/1e6 단위 오기 보정)")
    print(f"sido missing={df['sido'].isna().sum()} rows "
          f"({df.loc[df['sido'].isna(), 'prop_uid'].nunique()} props)")
    print(f"region mix: {df.drop_duplicates('prop_uid')['region'].value_counts(dropna=False).to_dict()}")
    print(f"type mix: {df.drop_duplicates('prop_uid')['type_pf'].value_counts().to_dict()}")
    print(f"gap_months dist: {df['gap_months'].describe().round(2).to_dict()}")
    n_tr = int(tr["has_transition"].sum())
    n_ok = int(tr["eval_pair_ok"].sum())
    months = tr["months_eval"].sum()
    print(f"transitions: {n_tr} total, eval-eligible {n_ok} "
          f"(양측 bv 보고), eval months={months:.0f}")
    for name, col in [("reval_event", "reval_event"), ("reval_down", "reval_down_event"),
                      ("impair", "impair_event")]:
        n = int(tr[col].sum())
        print(f"{name}: {n} events / {n_ok} eval-transitions = {n/n_ok*100:.3f}%/기간, "
              f"per-month = {n/months*100:.4f}%/월")
    print("saved:", OUT_PANEL)
    print("saved:", OUT_GROUP)


if __name__ == "__main__":
    main()

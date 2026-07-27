# -*- coding: utf-8 -*-
"""사업장 인근(같은 읍면동) 규제변경 이벤트 테이블 구축.

원천: 토지이음 도시계획 조서 최신 스냅샷 1세트(스냅샷 diff 금지 — 고시일이 레코드 안에 있음).
  - 용도지구: UPIS_004/TN_SPCFC_WTNNC.csv + KLIP_004/KP_SPCA_DSWE.csv
  - 용도구역: UPIS_004/TN_USGAR_WTNNC.csv + KLIP_004/KP_USAR_DSWE.csv
  - 지구단위: UPIS_005/TN_DSTPLAN_WTNNC.csv + KLIP_005/KP_DSPL_DSWE.csv

레시피(ORIG/자산탐침결과.md '재탐침' 절 검증치 기반):
  - UPIS 계열: 쉼표→∮·개행→∩ 치환 + 따옴표 깨짐 → QUOTE_NONE 필수, ∮ 복원.
  - KLIP 계열: 정상 quoting → QUOTE_NONE 금지(행 17% 증발).
  - 이벤트 = 결정유형 신설/변경/폐지/정정/실효(기정 PMA0002 제외),
    고시일 = D_NOTICE_CODE/dcsn_ntfc_cd 안의 'NTC'+8자리(1960~2026 유효만).
  - UPIS↔KLIP 레코드코드 중복 → dedup(UPIS 우선).
  - 시군구 스코핑: 레코드코드 앞 5자리 vs 사이트 허용 코드집합
    (sgg_code_table 이름 매칭 ∪ lawd_cd ∪ 구체계 환산 ∪ 시도급 폴백).
  - L3 매칭: 사이트 주소의 읍면동리 토큰이 LOCATION_NAME 공백제거 문자열에 포함.

산출:
  - DASH/data/location/site_regulation_events.csv (2024-01~2026-06)
  - DASH/data/location/regulation_events_month.csv (월×권역 집계)
  - stdout: 매칭 통계 + 간단 사건연구(카이제곱/Fisher)
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------- 경로
DASH = Path(__file__).resolve().parents[1]
ORIG = Path("/Users/kdh/Desktop/Pilot/Real_estate_after_care_claude")
EUM = ORIG / "토지이음"
OUT_DIR = DASH / "data" / "location"

WINDOW_START = "20240101"  # 패널기간(2025-01~2026-06) + 직전 12개월
WINDOW_END = "20260630"
PANEL_START, PANEL_END = "2025-01", "2026-06"

# 결정유형 코드(UPIS 표준 PMA): 기정(PMA0002)은 이벤트 아님 → 제외
EVENT_TYPE = {
    "PMA0001": "신설",
    "PMA0003": "변경",
    "PMA0004": "폐지",
    "PMA0005": "정정",
    "PMA0006": "실효",
}

# 신체계 시도 접두 → 구체계 접두(레코드코드가 구체계 혼재이므로 환산 필요)
OLD_SIDO_PREFIX = {"51": ["42"], "52": ["45"], "12": ["46", "29"]}
# 행정구역 통합 이전 코드(레코드코드에 잔존 — 실측 확인): 시군구명 → 구코드
MERGED_LEGACY = {
    "청주시": ["43710"],           # 청원군(2014 통합)
    "창원시": ["48160", "48170"],  # 마산시·진해시(2010 통합)
    "세종특별자치시": ["44710"],   # 연기군(2012)
    "세종시": ["44710"],
}
# 전남광주통합특별시(신 12xxx)의 구체계 코드 — 이름 기반 수기 매핑
OLD_JEONNAM_GWANGJU = {
    "목포시": "46110", "여수시": "46130", "순천시": "46150", "나주시": "46170",
    "광양시": "46230", "담양군": "46710", "곡성군": "46720", "구례군": "46730",
    "고흥군": "46770", "보성군": "46780", "화순군": "46790", "장흥군": "46800",
    "강진군": "46810", "해남군": "46820", "영암군": "46830", "무안군": "46840",
    "함평군": "46860", "영광군": "46870", "장성군": "46880", "완도군": "46890",
    "진도군": "46900", "신안군": "46910",
    "동구": "29110", "서구": "29140", "남구": "29155", "북구": "29170",
    "광산구": "29200",
}

SIDO_SHORT_TO_TABLE = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "광주": "전남광주통합특별시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
    "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전남광주통합특별시",
    "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
}


# ---------------------------------------------------------------- 스냅샷 탐색
def latest_snapshot(prefix: str, need_sub: str) -> Path:
    """이름의 날짜가 가장 최신이면서 need_sub(예: 'UPIS_004')를 포함한 폴더.

    macOS는 파일명을 NFD로 저장하므로 NFC로 정규화해 비교한다.
    """
    import unicodedata

    cands = []
    for p in EUM.iterdir():
        name = unicodedata.normalize("NFC", p.name)
        if not (name.startswith(prefix) and name.endswith("전국")):
            continue
        m = re.search(r"_(\d{8})_", name)
        if not m or not p.is_dir():
            continue
        if any(c.name.startswith(need_sub) for c in p.iterdir()):
            cands.append((m.group(1), p))
    if not cands:
        raise FileNotFoundError(f"{prefix} snapshot with {need_sub} not found")
    return max(cands)[1]


def sub_csv(folder: Path, sub_prefix: str, fname: str) -> Path:
    sub = next(c for c in sorted(folder.iterdir()) if c.name.startswith(sub_prefix))
    return sub / fname


# ---------------------------------------------------------------- 조서 파서
def read_upis(path: Path, cols: dict[str, str]) -> pd.DataFrame:
    """UPIS: 쉼표→∮·개행→∩ 치환 + 따옴표 깨짐 → QUOTE_NONE 필수."""
    df = pd.read_csv(
        path, encoding="cp949", quoting=csv.QUOTE_NONE, sep=",",
        engine="python", on_bad_lines="skip", dtype=str,
    )
    df = df[list(cols)].rename(columns=cols)
    for c in df.columns:
        df[c] = (
            df[c].str.strip('"').str.replace("∮", ",", regex=False)
            .str.replace("∩", " ", regex=False)
        )
    return df


def read_klip(path: Path, cols: dict[str, str]) -> pd.DataFrame:
    """KLIP: 정상 quoting CSV — QUOTE_NONE 쓰면 행 손실되므로 일반 파싱."""
    df = pd.read_csv(
        path, encoding="cp949", engine="python", on_bad_lines="skip", dtype=str,
    )
    return df[list(cols)].rename(columns=cols)


def load_events() -> pd.DataFrame:
    snap004 = latest_snapshot("용도지역정보(도시계획)", "UPIS_004")
    snap005 = latest_snapshot("지구단위계획구역", "UPIS_005")
    print(f"[snapshot] 004: {snap004.name} / 005: {snap005.name}")

    upis_cols = {
        "RECORD_CODE": "record_code", "RECORD_TYPE": "type_code",
        "LOCATION_NAME": "location", "D_NOTICE_CODE": "notice_code",
    }
    klip_cols = {
        "wevd_cd": "record_code", "wevd_ty_stcd": "type_code",
        "lc_nm": "location", "dcsn_ntfc_cd": "notice_code",
    }
    sources = [
        ("용도지구", "upis", sub_csv(snap004, "UPIS_004", "TN_SPCFC_WTNNC.csv")),
        ("용도구역", "upis", sub_csv(snap004, "UPIS_004", "TN_USGAR_WTNNC.csv")),
        ("지구단위", "upis", sub_csv(snap005, "UPIS_005", "TN_DSTPLAN_WTNNC.csv")),
        ("용도지구", "klip", sub_csv(snap004, "KLIP_004", "KP_SPCA_DSWE.csv")),
        ("용도구역", "klip", sub_csv(snap004, "KLIP_004", "KP_USAR_DSWE.csv")),
        ("지구단위", "klip", sub_csv(snap005, "KLIP_005", "KP_DSPL_DSWE.csv")),
    ]
    frames = []
    for kind, sys_, path in sources:
        df = read_upis(path, upis_cols) if sys_ == "upis" else read_klip(path, klip_cols)
        df["table_kind"] = kind
        df["source"] = sys_
        frames.append(df)
        print(f"  {path.name}: {len(df):,} rows")
    ev = pd.concat(frames, ignore_index=True)

    # 이벤트 정의: 결정유형(기정 제외) × 고시일 유효 × 위치 텍스트 존재
    ev["event_type"] = ev["type_code"].map(EVENT_TYPE)
    ev = ev.dropna(subset=["event_type", "record_code", "location"])
    ev["notice_date"] = ev["notice_code"].str.extract(r"NTC(\d{8})", expand=False)
    ev = ev.dropna(subset=["notice_date"])
    dt = pd.to_datetime(ev["notice_date"], format="%Y%m%d", errors="coerce")
    ev = ev[dt.notna() & (dt.dt.year >= 1960) & (dt.dt.year <= 2026)].copy()

    # UPIS↔KLIP 이관 중복 → 레코드코드 dedup(UPIS 우선)
    ev["src_rank"] = (ev["source"] == "klip").astype(int)
    ev = (
        ev.sort_values(["record_code", "src_rank"])
        .drop_duplicates("record_code", keep="first")
        .drop(columns=["src_rank", "type_code", "notice_code"])
    )
    ev["sgg5"] = ev["record_code"].str[:5]
    ev = ev[ev["sgg5"].str.fullmatch(r"\d{5}")]
    ev["loc_comp"] = ev["location"].str.replace(r"\s+", "", regex=True)
    ev["event_month"] = ev["notice_date"].str[:4] + "-" + ev["notice_date"].str[4:6]
    return ev


# ---------------------------------------------------------------- 사이트 준비
def norm_sgg(s: str) -> str:
    return re.sub(r"\s+", "", str(s))


def build_sites() -> pd.DataFrame:
    master = pd.read_csv(
        ORIG / "data/processed/kfb_sites_master.csv", dtype=str, encoding="utf-8-sig"
    )[["site_id", "address", "sido", "region"]]
    geo = pd.read_csv(ORIG / "data/processed/site_geo_keys.csv", dtype=str)
    sites = master.merge(
        geo[["site_id", "sido_s", "sgg", "lawd_cd"]], on="site_id", how="left"
    )

    table = pd.read_csv(ORIG / "data/external/sgg_code_table.csv", dtype=str)
    table["sig_norm"] = table["sig_kor_nm"].map(norm_sgg)

    allowed_list, tokens_list = [], []
    for _, r in sites.iterrows():
        allowed: set[str] = set()
        # ① 코드표 이름 매칭 (사이트 sido·sgg명 ↔ sido_nm·sig_kor_nm)
        sido_tab = SIDO_SHORT_TO_TABLE.get(str(r["sido_s"]))
        sgg = norm_sgg(r["sgg"]) if pd.notna(r["sgg"]) else ""
        if sido_tab and sgg:
            sub = table[table["sido_nm"] == sido_tab]
            hit = sub[
                (sub["sig_norm"] == sgg)
                | sub["sig_norm"].str.startswith(sgg)
                | sub["sig_norm"].str.endswith(sgg)
            ]
            allowed.update(hit["sig_cd"])
            # 전남광주통합(신 12xxx)은 구체계 코드를 이름으로 환산
            for nm in hit["sig_norm"]:
                for key, old in OLD_JEONNAM_GWANGJU.items():
                    if sido_tab == "전남광주통합특별시" and (nm == key or nm.endswith(key)):
                        allowed.add(old)
        # ② 사이트 lawd_cd(신체계)
        if pd.notna(r["lawd_cd"]):
            allowed.add(str(r["lawd_cd"]))
        # ③ 강원(51↔42)·전북(52↔45)은 접미 보존 → 접두 환산
        for code in list(allowed):
            for old_p in OLD_SIDO_PREFIX.get(code[:2], []):
                if old_p in ("42", "45"):
                    allowed.add(old_p + code[2:])
        # ③-2 구(區) 분리 이전 시 단위 코드(실측: 조서는 44131이 아니라 44130 사용)
        for code in list(allowed):
            allowed.add(code[:4] + "0")
        # ③-3 행정구역 통합 이전 코드(청원·마산·진해·연기)
        if sgg in MERGED_LEGACY:
            allowed.update(MERGED_LEGACY[sgg])
        # ④ 시도급 폴백(뒤 000) — 신·구 접두 모두
        for code in list(allowed):
            allowed.add(code[:2] + "000")
        for p2 in {c[:2] for c in allowed}:
            for old_p in OLD_SIDO_PREFIX.get(p2, []):
                allowed.add(old_p + "000")
        allowed_list.append(allowed)
        tokens_list.append(extract_tokens(r["address"]))
    sites["allowed"] = allowed_list
    sites["tokens"] = tokens_list
    return sites


def extract_tokens(addr) -> list[str]:
    """주소에서 읍면동리(·가) 토큰 추출. 예: '신흥동3가'(+파생 '신흥동'), '보성리'."""
    if not isinstance(addr, str):
        return []
    toks: list[str] = []
    parts = re.split(r"\s+", addr)
    prev = ""
    for raw in parts:
        p = raw.strip("()").rstrip(",")
        m = re.fullmatch(r"([가-힣0-9]+)(읍|면|동|리|가)", p)
        if m:
            core = m.group(1)
            if re.fullmatch(r"\d+", core) and m.group(2) == "가":
                # '상락동 1가' 꼴 → 직전 동 토큰과 결합
                if prev.endswith("동"):
                    toks.append(prev + p)
            elif re.search(r"[가-힣]", core) and len(p) >= 2:
                toks.append(p)
                mb = re.fullmatch(r"(.+동)\d+가", p)  # '신흥동3가' → '신흥동' 파생
                if mb:
                    toks.append(mb.group(1))
        prev = p
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---------------------------------------------------------------- L3 매칭
def match_sites(ev_win: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    by_sgg = {k: g for k, g in ev_win.groupby("sgg5")}
    rows = []
    for _, s in sites.iterrows():
        if not s["tokens"] or not s["allowed"]:
            continue
        cands = [by_sgg[c] for c in s["allowed"] if c in by_sgg]
        if not cands:
            continue
        cand = pd.concat(cands)
        pat = "|".join(re.escape(t) for t in s["tokens"])
        hit = cand[cand["loc_comp"].str.contains(pat, regex=True, na=False)]
        for _, e in hit.iterrows():
            rows.append((
                s["site_id"], e["event_month"], e["notice_date"],
                e["table_kind"], e["event_type"], e["record_code"],
            ))
    out = pd.DataFrame(rows, columns=[
        "site_id", "event_month", "notice_date",
        "table_kind", "event_type", "record_code",
    ])
    return out.drop_duplicates().sort_values(
        ["site_id", "notice_date", "record_code"]
    ).reset_index(drop=True)


# ---------------------------------------------------------------- 사건연구
def month_idx(mk: pd.Series) -> pd.Series:
    y = mk.str[:4].astype(int)
    m = mk.str[5:7].astype(int)
    return y * 12 + m


def event_study(site_events: pd.DataFrame) -> None:
    from scipy.stats import chi2_contingency, fisher_exact

    panel = pd.read_csv(
        DASH / "data" / "panel_clean.csv", dtype=str,
        usecols=["site_id", "month_key", "region"],
    ).drop_duplicates(["site_id", "month_key"])
    panel["midx"] = month_idx(panel["month_key"])

    reg = site_events[
        (site_events["event_month"] >= "2024-10")  # 패널 첫 달 -3개월이면 충분
    ][["site_id", "event_month"]].drop_duplicates()
    reg["midx"] = month_idx(reg["event_month"])
    reg_set = set(zip(reg["site_id"], reg["midx"]))

    def has_recent(row, lo, hi):
        return any((row["site_id"], row["midx"] - k) in reg_set for k in range(lo, hi + 1))

    panel["reg_0_3"] = panel.apply(lambda r: has_recent(r, 0, 3), axis=1)
    panel["reg_0_0"] = panel.apply(lambda r: has_recent(r, 0, 0), axis=1)
    panel["reg_1_3"] = panel.apply(lambda r: has_recent(r, 1, 3), axis=1)

    kfb = pd.read_csv(
        ORIG / "data/processed/kfb_events.csv", dtype=str, encoding="utf-8-sig"
    )
    kfb = kfb[kfb["suspect"].isna()]  # suspect 결측 행만 정상
    for out_ev in ["bid_cut", "reappraisal"]:
        occ = set(zip(
            kfb.loc[kfb["event"] == out_ev, "site_id"],
            month_idx(kfb.loc[kfb["event"] == out_ev, "month_key"]),
        ))
        panel[f"y_{out_ev}"] = [
            (s, m) in occ for s, m in zip(panel["site_id"], panel["midx"])
        ]

    print("\n[사건연구] 사이트×월 그레인, 패널", panel["month_key"].min(), "~",
          panel["month_key"].max(), f"(n={len(panel):,})")
    for flag in ["reg_0_3", "reg_0_0", "reg_1_3"]:
        n1 = int(panel[flag].sum())
        print(f"  플래그 {flag}: 노출 셀 {n1:,} ({n1/len(panel):.1%})")
        for out_ev in ["bid_cut", "reappraisal"]:
            ct = pd.crosstab(panel[flag], panel[f"y_{out_ev}"])
            ct = ct.reindex(index=[False, True], columns=[False, True], fill_value=0)
            a, b = ct.loc[True, True], ct.loc[True, False]
            c, d = ct.loc[False, True], ct.loc[False, False]
            r1 = a / (a + b) if a + b else float("nan")
            r0 = c / (c + d) if c + d else float("nan")
            chi2, p_chi, _, exp = chi2_contingency(ct.values)
            odds, p_f = fisher_exact(ct.values)
            use_fisher = exp.min() < 5
            print(
                f"    {out_ev:12s}: 노출 {r1:.3%} ({a}/{a+b}) vs 비노출 {r0:.3%} ({c}/{c+d})"
                f" | chi2 p={p_chi:.4f}, Fisher p={p_f:.4f}"
                f" (OR={odds:.2f}"
                f"{', 기대빈도<5→Fisher 권장' if use_fisher else ''})"
            )


# ---------------------------------------------------------------- main
def main() -> None:
    ev = load_events()
    print(f"[events] dedup 후 전체 이벤트 조서 {len(ev):,}건 "
          f"(고시일 {ev['notice_date'].min()}~{ev['notice_date'].max()})")

    ev_win = ev[(ev["notice_date"] >= WINDOW_START) & (ev["notice_date"] <= WINDOW_END)]
    print(f"[events] 윈도(2024-01~2026-06) 전국 {len(ev_win):,}건")

    sites = build_sites()
    n_tok = int(sites["tokens"].map(bool).sum())
    print(f"[sites] 정본 {len(sites)}곳, 읍면동리 토큰 추출 성공 {n_tok}곳")

    site_events = match_sites(ev_win, sites)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    f1 = OUT_DIR / "site_regulation_events.csv"
    site_events.to_csv(f1, index=False, encoding="utf-8-sig")

    in_panel = site_events[
        (site_events["event_month"] >= PANEL_START)
        & (site_events["event_month"] <= PANEL_END)
    ]
    print(f"[match] 윈도 사이트-이벤트 쌍 {len(site_events):,}건 / "
          f"사이트 {site_events['site_id'].nunique()}곳")
    print(f"[match] 패널기간(2025-01~2026-06) {len(in_panel):,}건 / "
          f"사이트 {in_panel['site_id'].nunique()}곳 "
          f"(선행 검증치 약 2,700건·420곳과 대조)")
    print("[match] 테이블군:", in_panel["table_kind"].value_counts().to_dict())
    print("[match] 유형:", in_panel["event_type"].value_counts().to_dict())

    # 월×권역 집계(대시보드 마커용)
    agg = site_events.merge(
        sites[["site_id", "region"]], on="site_id", how="left"
    )
    monthly = (
        agg.groupby(["event_month", "region"])
        .agg(
            n_events=("record_code", "size"),
            n_unique_records=("record_code", "nunique"),
            n_sites=("site_id", "nunique"),
        )
        .reset_index()
        .sort_values(["event_month", "region"])
    )
    f2 = OUT_DIR / "regulation_events_month.csv"
    monthly.to_csv(f2, index=False, encoding="utf-8-sig")
    print(f"[out] {f1}\n[out] {f2}")

    event_study(site_events)


if __name__ == "__main__":
    main()

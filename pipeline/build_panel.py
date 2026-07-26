# -*- coding: utf-8 -*-
"""클린 패널 빌더 — variable_catalog.json 기반, 사내 데이터 확장 훅 포함.

사용:
    python pipeline/build_panel.py                      # data/panel_clean.csv 등 생성
    python pipeline/build_panel.py --internal my.csv    # 사내 데이터 결합(스키마 검증)

산출:
    data/panel_clean.csv   사업장×월×라인 패널 (카탈로그 keep 컬럼 + 사건 플래그)
    data/site_master.csv   사업장 1행 요약 (주소·유형·처분결과·체류·스크리닝 원료)
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source"
OUT = ROOT / "data"

BOOLISH = ["exited", "reactivated", "kfb_understated"]


def load_catalog() -> pd.DataFrame:
    cat = pd.DataFrame(json.loads((ROOT / "pipeline" / "variable_catalog.json").read_text()))
    return cat


def build_panel(cat: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(SRC / "analysis_master.csv")
    for c in BOOLISH:
        if c in df and df[c].dtype == object:
            df[c] = df[c].map({True: 1, False: 0, "True": 1, "False": 0})
        elif c in df and df[c].dtype == bool:
            df[c] = df[c].astype(int)
    for c in ["pms_after_exit", "stcns_after_exit"]:  # yyyymmdd → 발생 플래그
        if c in df:
            df[c] = df[c].notna().astype(int)

    keep = [r["name"] for _, r in cat.iterrows()
            if r["decision"] == "keep" and r["source"] == "analysis_master"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise SystemExit(f"카탈로그 keep 컬럼이 원본에 없음: {missing}")
    panel = df[keep].copy()

    # 세부 유형(biz_type) 결합 — 사업장 단위
    master = pd.read_csv(SRC / "kfb_sites_master.csv",
                         usecols=["site_id", "biz_type"])
    panel = panel.merge(master, on="site_id", how="left")

    # 사건 플래그 결합 (suspect 제외 정본 규칙, site×month×line 그레인)
    ev = pd.read_csv(SRC / "kfb_events.csv")
    ev = ev[ev["suspect"].isna()]
    for e, col in [("bid_cut", "ev_bid_cut"), ("reappraisal", "ev_reappraisal"),
                   ("bid_reset", "ev_bid_reset")]:
        k = (ev[ev["event"] == e][["site_id", "month_key", "line_id"]]
             .drop_duplicates().assign(**{col: 1}))
        panel = panel.merge(k, on=["site_id", "month_key", "line_id"], how="left")
        panel[col] = panel[col].fillna(0).astype(int)

    # 불변식: 그레인 유일성
    dup = panel.duplicated(["site_id", "month_key", "line_id"]).sum()
    if dup:
        raise SystemExit(f"그레인 위반: site×month×line 중복 {dup}행")
    return panel


def build_site_master(panel: pd.DataFrame) -> pd.DataFrame:
    master = pd.read_csv(SRC / "kfb_sites_master.csv")
    disp = pd.read_csv(SRC / "site_disposal_summary.csv")[
        ["site_id", "outcome", "sale_price_mn", "sale_dt", "sale_to_appraisal_pct",
         "n_rounds_observed", "n_fail"]]
    g = panel.sort_values("month_key").groupby("site_id")
    agg = g.agg(
        n_months=("month_key", "nunique"),
        first_month=("month_key", "min"), last_month=("month_key", "max"),
        appraisal_first=("appraisal_mn", "first"), appraisal_last=("appraisal_mn", "last"),
        min_bid_first=("min_bid_mn", "first"), min_bid_last=("min_bid_mn", "last"),
        discount_last=("discount_ratio", "last"),
        max_round=("round_no", "max"),
        n_bid_cut=("ev_bid_cut", "sum"), n_reappraisal=("ev_reappraisal", "sum"),
        exited=("exited", "max"), reactivated=("reactivated", "max"),
        excess_pp=("excess_pp_med", "median"),
        appr_vs_rtms=("appr_vs_rtms_dae_3m", "median"),
        land_chg_cum12_last=("land_chg_cum12_pct", "last"),
        region=("region", "first"), sido=("sido", "first"), sgg=("sgg", "first"),
        biz_class=("biz_class", "first"), biz_type=("biz_type", "first"),
        lon=("lon", "first"), lat=("lat", "first"),
    ).reset_index()
    agg["minbid_drop_pct"] = np.where(
        agg["min_bid_first"] > 0,
        (agg["min_bid_last"] / agg["min_bid_first"] - 1) * 100, np.nan)
    sm = agg.merge(master[["site_id", "address"]], on="site_id", how="left")
    sm = sm.merge(disp, on="site_id", how="left")
    return sm


def merge_internal(panel: pd.DataFrame, path: str) -> pd.DataFrame:
    """사내 데이터 결합 훅 (Phase 2 placeholder — docs/INTERNAL_DATA_SPEC.md 참조).

    요구 스키마: site_id 또는 address 중 1개 + month_key(YYYY-MM, 선택) +
    임의 수치/범주 컬럼. 결합 컬럼은 int_ 접두사로 강제해 공개 변수와 격리.
    """
    it = pd.read_csv(path)
    if "site_id" not in it.columns and "address" not in it.columns:
        raise SystemExit("사내 데이터에 site_id 또는 address 컬럼 필요")
    if "address" in it.columns and "site_id" not in it.columns:
        addr = pd.read_csv(SRC / "kfb_sites_master.csv",
                           usecols=["site_id", "address", "addr_norm"])
        it["_a"] = it["address"].str.replace(r"\s+", "", regex=True)
        addr["_a"] = addr["address"].str.replace(r"\s+", "", regex=True)
        it = it.merge(addr[["_a", "site_id"]], on="_a", how="left").drop(columns="_a")
        unmatched = it["site_id"].isna().sum()
        if unmatched:
            print(f"⚠ 주소 미매칭 {unmatched}행 — addr_norm 정규화 규칙 적용 필요")
    val_cols = [c for c in it.columns
                if c not in ("site_id", "address", "month_key")]
    it = it.rename(columns={c: f"int_{c}" for c in val_cols if not c.startswith("int_")})
    on = ["site_id", "month_key"] if "month_key" in it.columns else ["site_id"]
    return panel.merge(it.drop(columns=[c for c in ("address",) if c in it]),
                       on=on, how="left")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--internal", help="사내 데이터 CSV 경로(선택)")
    args = ap.parse_args()

    cat = load_catalog()
    panel = build_panel(cat)
    if args.internal:
        panel = merge_internal(panel, args.internal)
    sm = build_site_master(panel)

    panel.to_csv(OUT / "panel_clean.csv", index=False)
    sm.to_csv(OUT / "site_master.csv", index=False)
    print(f"panel_clean: {panel.shape[0]}행 × {panel.shape[1]}열 | "
          f"site_master: {sm.shape[0]}곳 × {sm.shape[1]}열")
    print(f"사건 플래그 합계: bid_cut {panel.ev_bid_cut.sum()}, "
          f"reappraisal {panel.ev_reappraisal.sum()}, reset {panel.ev_bid_reset.sum()}")


if __name__ == "__main__":
    main()

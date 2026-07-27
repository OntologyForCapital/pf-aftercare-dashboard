# -*- coding: utf-8 -*-
"""리츠(정상 자산) vs PF 공개 사업장(부실) 입지 대조.

같은 참조점(OSM IC 노드·도시 44곳)으로 두 집단의 IC거리·도시거리를 계산해
유형 매칭 비교: 물류(리츠) vs 산업시설(PF) 등. 검정은 Mann-Whitney + KS.
실행: python pipeline/compare_location_reits.py
산출: data/location/reits_location_metrics.csv + 콘솔 비교표
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import build_location as BL  # 같은 참조점·하버사인 재사용

ROOT = Path(__file__).resolve().parents[1]


def attach_metrics(df: pd.DataFrame) -> pd.DataFrame:
    ic = pd.read_csv(ROOT / "data" / "location" / "ic_nodes_osm.csv")
    ic.columns = ["lat", "lon", "name"]
    ic = ic[(ic["lon"] < 129.8) & (ic["lat"] > 33.0)]
    s_lat = df["lat"].values[:, None]
    s_lon = df["lon"].values[:, None]
    d_ic = BL.haversine_km(s_lat, s_lon, ic["lat"].values[None, :], ic["lon"].values[None, :])
    df["dist_ic_km"] = d_ic.min(axis=1).round(2)
    cdf = pd.DataFrame(BL.CITIES, columns=["city", "clat", "clon", "pop_10k", "metro"])
    d_city = BL.haversine_km(s_lat, s_lon, cdf["clat"].values[None, :], cdf["clon"].values[None, :])
    df["dist_city_km"] = d_city.min(axis=1).round(2)
    m = cdf["metro"].values == 1
    df["dist_metro_km"] = d_city[:, m].min(axis=1).round(2)
    return df


def compare(a, b, la, lb, var):
    a, b = a[var].dropna(), b[var].dropna()
    if len(a) < 8 or len(b) < 8:
        return None
    U, p_mw = stats.mannwhitneyu(a, b)
    _, p_ks = stats.ks_2samp(a, b)
    return dict(var=var, grp_a=la, n_a=len(a), med_a=round(a.median(), 2),
                grp_b=lb, n_b=len(b), med_b=round(b.median(), 2),
                p_mannwhitney=round(p_mw, 5), p_ks=round(p_ks, 5))


def main():
    re_ = pd.read_csv(ROOT / "data" / "location" / "reits_location.csv")
    re_ = attach_metrics(re_)
    re_.to_csv(ROOT / "data" / "location" / "reits_location_metrics.csv", index=False)

    pf = pd.read_csv(ROOT / "data" / "site_location.csv").merge(
        pd.read_csv(ROOT / "data" / "site_master.csv",
                    usecols=["site_id", "biz_class"]), on="site_id")

    pairs = [
        ("물류(리츠)", re_[re_.invest_target == "물류"],
         "산업시설(PF)", pf[pf.biz_class == "산업시설"]),
        ("주택(리츠)", re_[re_.invest_target.str.startswith("주택", na=False)],
         "주거시설(PF)", pf[pf.biz_class == "주거시설"]),
        ("오피스(리츠)", re_[re_.invest_target == "오피스"],
         "업무시설(PF)", pf[pf.biz_class == "업무시설"]),
        ("리테일(리츠)", re_[re_.invest_target == "리테일"],
         "상업시설(PF)", pf[pf.biz_class == "상업시설"]),
        ("전체(리츠)", re_, "전체(PF)", pf),
    ]
    rows = []
    for la, a, lb, b in pairs:
        for var in ["dist_ic_km", "dist_city_km", "dist_metro_km"]:
            r = compare(a, b, la, lb, var)
            if r:
                rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "location" / "reits_pf_location_tests.csv", index=False)
    print(out.to_string(index=False))
    # 개발사업(리츠 내 PF성 물건) 민감도
    dev = re_[re_.kind == "개발사업"]
    if len(dev) >= 8:
        r = compare(dev, re_[re_.kind == "일반"], "리츠 개발사업", "리츠 일반", "dist_ic_km")
        print("\n민감도:", r)


if __name__ == "__main__":
    main()

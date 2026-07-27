# -*- coding: utf-8 -*-
"""리츠(정상) vs 경공매 PF(부실) 자산 특성 전면 대조 — §6-2·공모전 자료 근거.

축: 지리 위계 / 자산 규모·가액 / 완공 상태 / 유형 구성 / 물류 한정 비교.
실행: python pipeline/compare_asset_traits.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT.parent / "Real_estate_after_care_claude"


def num(s):
    return pd.to_numeric(s, errors="coerce")


def main():
    re_m = pd.read_csv(ROOT / "data" / "location" / "reits_location_metrics.csv")
    re_p = pd.read_csv(ROOT / "data" / "location" / "reits_value_path.csv")
    src = pd.read_csv(ORIG / "data" / "processed" / "reits_property_values.csv")
    panel = pd.read_csv(ROOT / "data" / "panel_clean.csv",
                        usecols=["site_id", "land_area_m2", "bldg_area_m2"])
    pf = (pd.read_csv(ROOT / "data" / "site_master.csv")
          .merge(pd.read_csv(ROOT / "data" / "site_location.csv"),
                 on="site_id", how="left")
          .merge(panel.groupby("site_id").first(), on="site_id", how="left"))
    last = re_p.groupby("prop_uid").last()

    rows = []

    def add(axis, metric, r, p, note=""):
        rows.append(dict(axis=axis, metric=metric, reits=r, pf=p, note=note))

    add("구성", "수도권 비중 %", round((last["region"] == "수도권").mean() * 100, 1),
        round((pf["region"] == "수도권").mean() * 100, 1))
    add("지리 위계", "광역시 거리 km(중앙)", re_m["dist_metro_km"].median(),
        pf["dist_metro_km"].median())
    add("지리 위계", "광역시 15km 이내 %", round((re_m["dist_metro_km"] <= 15).mean() * 100),
        round((pf["dist_metro_km"] <= 15).mean() * 100))
    add("지리 위계", "도시(25만+) 거리 km(중앙)", re_m["dist_city_km"].median(),
        pf["dist_city_km"].median(), "거의 무차이 — 위계가 갈림")
    add("지리 위계", "고속도로 IC 거리 km(중앙)", re_m["dist_ic_km"].median(),
        pf["dist_ic_km"].median())
    bv = num(last["book_value_mn"]); bv = bv[bv > 0]
    add("규모", "자산가액 억원(중앙)", round(bv.median() / 100),
        round(num(pf["appraisal_last"]).median() / 100), "리츠=장부가, PF=감정가")
    la = num(src.groupby("property")["land_area_m2"].max()); la = la[la > 0]
    pla = num(pf["land_area_m2"]); pla = pla[pla > 0]
    add("규모", "토지면적 ㎡(중앙)", round(la.median()), round(pla.median()))
    gfa = num(src.groupby("property")["gfa_m2"].max()).fillna(0)
    bld = num(pf["bldg_area_m2"]).fillna(0)
    add("완공 상태", "건물 연면적 기재 %", round((gfa > 0).mean() * 100),
        round((bld > 0).mean() * 100), "완공 임대자산 vs 개발단계")
    pf["biz5"] = pf["biz_class"].where(
        pf["biz_class"].isin(["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설"]), "기타")
    rt = last["type_pf"].value_counts(normalize=True).mul(100).round(1)
    pt = pf["biz5"].str.replace("시설", "").value_counts(normalize=True).mul(100).round(1)
    for t in ["주거", "업무", "상업", "산업", "숙박"]:
        add("유형 구성", f"{t} %", rt.get(t, 0.0), pt.get(t, 0.0),
            "구성은 유사 — 유형이 부실을 가르지 않음")

    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "location" / "reits_pf_traits.csv", index=False)
    print(out.to_string(index=False))
    # 물류 한정(검정은 reits_pf_location_tests.csv 참조)
    t = pd.read_csv(ROOT / "data" / "location" / "reits_pf_location_tests.csv")
    print("\n[물류 한정 검정]")
    print(t[t.grp_a == "물류(리츠)"].to_string(index=False))


if __name__ == "__main__":
    main()

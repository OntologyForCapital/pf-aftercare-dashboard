# -*- coding: utf-8 -*-
"""입지 변수 빌더 — 사업장별 고속도로 IC 거리·최근접 도시 산출.

입력:
  data/location/ic_nodes_osm.csv  OSM motorway_junction 노드 (Overpass, ODbL)
  data/site_master.csv            사업장 좌표(lon/lat — VWorld·카카오 해상)
출력:
  data/site_location.csv          site_id, dist_ic_km, ic_name,
                                  dist_metro_km, metro_name, dist_city_km, city_name

주의: 전부 하버사인 직선거리(km). 도로 주행거리가 아니므로 수준보다 상대 비교용.
도시 좌표는 시청 기준 근사(±수 km), 인구는 등급 분류용 근사치(2025년 전후, 만 명).
실행: python pipeline/build_location.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# (이름, lat, lon, 인구만, 광역여부)
CITIES = [
    ("서울", 37.5665, 126.9780, 933, 1), ("부산", 35.1796, 129.0756, 329, 1),
    ("인천", 37.4563, 126.7052, 301, 1), ("대구", 35.8714, 128.6014, 236, 1),
    ("대전", 36.3504, 127.3845, 144, 1), ("광주", 35.1595, 126.8526, 141, 1),
    ("울산", 35.5384, 129.3114, 110, 1), ("세종", 36.4800, 127.2890, 39, 1),
    ("수원", 37.2636, 127.0286, 119, 0), ("용인", 37.2411, 127.1776, 108, 0),
    ("고양", 37.6584, 126.8320, 107, 0), ("창원", 35.2280, 128.6811, 100, 0),
    ("성남", 37.4200, 127.1265, 92, 0), ("화성", 37.1995, 126.8315, 95, 0),
    ("청주", 36.6424, 127.4890, 85, 0), ("부천", 37.5034, 126.7660, 77, 0),
    ("남양주", 37.6360, 127.2165, 73, 0), ("천안", 36.8151, 127.1139, 66, 0),
    ("전주", 35.8242, 127.1480, 64, 0), ("안산", 37.3219, 126.8309, 63, 0),
    ("평택", 36.9921, 127.1127, 59, 0), ("안양", 37.3943, 126.9568, 55, 0),
    ("김해", 35.2285, 128.8894, 53, 0), ("시흥", 37.3800, 126.8029, 52, 0),
    ("파주", 37.7599, 126.7800, 50, 0), ("포항", 36.0190, 129.3435, 49, 0),
    ("제주", 33.4996, 126.5312, 49, 0), ("김포", 37.6153, 126.7156, 48, 0),
    ("의정부", 37.7381, 127.0337, 46, 0), ("구미", 36.1195, 128.3446, 41, 0),
    ("원주", 37.3422, 127.9202, 36, 0), ("양산", 35.3350, 129.0372, 35, 0),
    ("아산", 36.7898, 127.0018, 35, 0), ("진주", 35.1800, 128.1076, 34, 0),
    ("춘천", 37.8813, 127.7300, 29, 0), ("경산", 35.8251, 128.7414, 28, 0),
    ("순천", 34.9507, 127.4872, 28, 0), ("익산", 35.9483, 126.9576, 27, 0),
    ("여수", 34.7604, 127.6622, 27, 0), ("경주", 35.8562, 129.2247, 25, 0),
    ("거제", 34.8806, 128.6211, 24, 0), ("목포", 34.8118, 126.3922, 21, 0),
    ("강릉", 37.7519, 128.8761, 21, 0), ("충주", 36.9910, 127.9259, 21, 0),
]


def haversine_km(lat1, lon1, lat2, lon2):
    """벡터화 하버사인. lat1/lon1: (n,1), lat2/lon2: (1,m) → (n,m) km."""
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def main():
    ic = pd.read_csv(ROOT / "data" / "location" / "ic_nodes_osm.csv")
    ic.columns = ["lat", "lon", "name"]
    # 한국 영역 필터 (bbox에 걸린 일본 규슈 제거 — 국내 고속도로 최동단 ~129.45)
    ic = ic[(ic["lon"] < 129.6) & (ic["lat"] > 33.0)].reset_index(drop=True)
    ic["name"] = ic["name"].fillna("")

    sm = pd.read_csv(ROOT / "data" / "site_master.csv",
                     usecols=["site_id", "lon", "lat"])
    sites = sm.dropna(subset=["lon", "lat"]).reset_index(drop=True)

    s_lat = sites["lat"].values[:, None]
    s_lon = sites["lon"].values[:, None]

    # IC 거리: dist_ic_km = 무명 노드 포함 최근접(진입 접근성) /
    # ic_name·dist_named_ic_km = '이름 있는' 노드 기준 짝 (두 컬럼이 같은 노드를 가리킴)
    d_ic = haversine_km(s_lat, s_lon, ic["lat"].values[None, :], ic["lon"].values[None, :])
    sites["dist_ic_km"] = d_ic.min(axis=1).round(2)
    named = ic["name"].values != ""
    d_named = d_ic[:, named]
    sites["ic_name"] = ic.loc[named, "name"].values[d_named.argmin(axis=1)]
    sites["dist_named_ic_km"] = d_named.min(axis=1).round(2)

    cdf = pd.DataFrame(CITIES, columns=["city", "clat", "clon", "pop_10k", "metro"])
    d_city = haversine_km(s_lat, s_lon, cdf["clat"].values[None, :], cdf["clon"].values[None, :])
    j = d_city.argmin(axis=1)
    sites["dist_city_km"] = d_city.min(axis=1).round(2)
    sites["city_name"] = cdf["city"].values[j]
    sites["city_pop_10k"] = cdf["pop_10k"].values[j]
    m = cdf["metro"].values == 1
    d_metro = d_city[:, m]
    jm = d_metro.argmin(axis=1)
    sites["dist_metro_km"] = d_metro.min(axis=1).round(2)
    sites["metro_name"] = cdf.loc[m, "city"].values[jm]

    out = sites[["site_id", "dist_ic_km", "ic_name", "dist_named_ic_km",
                 "dist_city_km", "city_name",
                 "city_pop_10k", "dist_metro_km", "metro_name"]]
    out.to_csv(ROOT / "data" / "site_location.csv", index=False)
    print(f"site_location: {len(out)}곳 / site_master {len(sm)}곳 "
          f"(좌표 결측 {sm['lon'].isna().sum()}곳 제외)")
    print(f"IC 노드(한국): {len(ic)}개 | dist_ic_km 중앙 {out.dist_ic_km.median():.1f} "
          f"p90 {out.dist_ic_km.quantile(.9):.1f}")
    print(f"dist_city_km 중앙 {out.dist_city_km.median():.1f} | "
          f"dist_metro_km 중앙 {out.dist_metro_km.median():.1f}")


if __name__ == "__main__":
    main()

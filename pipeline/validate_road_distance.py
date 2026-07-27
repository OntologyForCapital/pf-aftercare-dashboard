# -*- coding: utf-8 -*-
"""직선거리 IC 접근성의 실주행거리 검증.

표본 사업장·리츠 물건에서 최근접 IC까지 ①직선(하버사인) ②실주행(카카오모빌리티
길찾기, 실패 시 OSRM 데모 서버) 거리를 비교해 직선거리 프록시의 타당성을 측정.
실행: python pipeline/validate_road_distance.py
산출: data/location/road_distance_validation.csv + 콘솔 요약
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT.parent / "Real_estate_after_care_claude"

import sys
sys.path.insert(0, str(ROOT / "pipeline"))
from build_location import haversine_km  # noqa: E402


def load_key():
    env = {}
    for line in (ORIG / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env.get("KAKAO_REST_API_KEY", "")


def kakao_drive_km(sess, key, o, d):
    try:
        r = sess.get("https://apis-navi.kakaomobility.com/v1/directions",
                     params={"origin": f"{o[0]},{o[1]}", "destination": f"{d[0]},{d[1]}",
                             "summary": "true"},
                     headers={"Authorization": f"KakaoAK {key}"}, timeout=15)
        if r.status_code != 200:
            return None, r.status_code
        routes = r.json().get("routes") or []
        if routes and routes[0].get("result_code") == 0:
            return routes[0]["summary"]["distance"] / 1000, 200
        return None, 200
    except Exception:
        return None, -1


def osrm_drive_km(sess, o, d):
    try:
        r = sess.get(f"https://router.project-osrm.org/route/v1/driving/"
                     f"{o[0]},{o[1]};{d[0]},{d[1]}",
                     params={"overview": "false"}, timeout=20)
        j = r.json()
        if j.get("code") == "Ok":
            return j["routes"][0]["distance"] / 1000
    except Exception:
        pass
    return None


def main():
    rng = np.random.default_rng(20260728)
    ic = pd.read_csv(ROOT / "data" / "location" / "ic_nodes_osm.csv")
    ic.columns = ["lat", "lon", "name"]
    ic = ic[(ic["lon"] < 129.6) & (ic["lat"] > 33.0)].reset_index(drop=True)

    pf = (pd.read_csv(ROOT / "data" / "site_master.csv")
          .merge(pd.read_csv(ROOT / "data" / "site_location.csv"), on="site_id"))
    pf = pf.dropna(subset=["lon", "lat"])
    pf["grp"] = np.where(pf["biz_class"] == "산업시설", "PF산업", "PF기타")
    re_ = pd.read_csv(ROOT / "data" / "location" / "reits_location_metrics.csv")
    re_["grp"] = np.where(re_["invest_target"] == "물류", "리츠물류", "리츠기타")

    samples = []
    for df, g, n in [(pf[pf.grp == "PF산업"], "PF산업", 20),
                     (pf[pf.grp == "PF기타"], "PF기타", 15),
                     (re_[re_.grp == "리츠물류"], "리츠물류", 20),
                     (re_[re_.grp == "리츠기타"], "리츠기타", 15)]:
        take = df.sample(min(n, len(df)), random_state=rng.integers(1e9))
        for _, r in take.iterrows():
            samples.append(dict(grp=g, lon=r["lon"], lat=r["lat"],
                                straight_km=r["dist_ic_km"]))

    key = load_key()
    sess = requests.Session()
    use_kakao = bool(key)
    rows = []
    for s in samples:
        d_ic = haversine_km(np.array([[s["lat"]]]), np.array([[s["lon"]]]),
                            ic["lat"].values[None, :], ic["lon"].values[None, :])[0]
        # 직선 최근접 후보 3곳(서로 2km 이상 떨어진 노드만 — 같은 IC 중복 배제)
        order = np.argsort(d_ic)
        cands, seen = [], []
        for j in order:
            if any(haversine_km(np.array([[ic.loc[j, "lat"]]]), np.array([[ic.loc[j, "lon"]]]),
                                np.array([[ic.loc[k, "lat"]]]), np.array([[ic.loc[k, "lon"]]]))[0][0] < 2
                   for k in seen):
                continue
            cands.append(int(j)); seen.append(int(j))
            if len(cands) == 3:
                break
        org = (s["lon"], s["lat"])
        best, best_j, engine = None, None, None
        for j in cands:
            dest = (ic.loc[j, "lon"], ic.loc[j, "lat"])
            drive = None
            if use_kakao:
                drive, code = kakao_drive_km(sess, key, org, dest)
                if code in (401, 403):
                    use_kakao = False
                time.sleep(0.2)
            if drive is None:
                drive = osrm_drive_km(sess, org, dest)
                if drive is not None and engine is None:
                    engine = "osrm"
                time.sleep(0.5)
            elif engine is None:
                engine = "kakao"
            if drive is not None and (best is None or drive < best):
                best, best_j = drive, j
        rows.append({**s, "ic_name_nearest": ic.loc[best_j, "name"] if best_j is not None else "",
                     "drive_km": best, "engine": engine})

    out = pd.DataFrame(rows).dropna(subset=["drive_km"])
    out.to_csv(ROOT / "data" / "location" / "road_distance_validation.csv", index=False)
    from scipy import stats
    r_p = stats.pearsonr(out["straight_km"], out["drive_km"])
    r_s = stats.spearmanr(out["straight_km"], out["drive_km"])
    ratio = (out["drive_km"] / out["straight_km"].clip(lower=0.05))
    print(f"표본 {len(out)} (엔진: {out.engine.value_counts().to_dict()})")
    print(f"직선 vs 주행: Pearson r={r_p[0]:.3f} · Spearman rho={r_s[0]:.3f}")
    print(f"주행/직선 배율: 중앙 {ratio.median():.2f} (IQR {ratio.quantile(.25):.2f}~{ratio.quantile(.75):.2f})")
    print("\n그룹별 (중앙):")
    print(out.groupby("grp")[["straight_km", "drive_km"]].median().round(2).to_string())
    lg = out[out.grp.isin(["리츠물류", "PF산업"])]
    if lg.grp.nunique() == 2:
        a = lg[lg.grp == "리츠물류"]["drive_km"]; b = lg[lg.grp == "PF산업"]["drive_km"]
        U, p = stats.mannwhitneyu(a, b)
        print(f"\n물류 한정 실주행 IC거리: 리츠 {a.median():.1f} vs PF {b.median():.1f}km (MW p={p:.3f})")


if __name__ == "__main__":
    main()

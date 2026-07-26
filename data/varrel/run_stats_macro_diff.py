# -*- coding: utf-8 -*-
"""[M]층 보강 — 거시(전국×월) 변수 vs 월별 결과지표의 수준·1차 차분 상관.

PHASE1_findings.md §2[M]의 차분 수치 산출 코드(재현성 확보용, 재검증 반영).
주의: 차분 p는 무보정 raw p이며, 2025-09 결측으로 차분 1개는 2개월 간격이다.

실행: python data/varrel/run_stats_macro_diff.py → 19_corr_macro_month_diff.csv
"""
from pathlib import Path

import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
df = pd.read_csv(REPO / "data" / "source" / "analysis_master.csv")

m = df.groupby("month_key").agg(
    med_discount=("discount_ratio", "median"),
    n_listed=("site_id", "nunique"),
).join(df.groupby("month_key")[
    ["base_rate", "spread_AA_KTB", "spread_BBB_KTB", "ktb_3y",
     "corp_bond_BBB3y", "cci_yoy_pct", "base_rate_chg_12m"]].first())

rows = []
for macro in ["base_rate", "spread_AA_KTB", "spread_BBB_KTB", "ktb_3y",
              "corp_bond_BBB3y", "cci_yoy_pct", "base_rate_chg_12m"]:
    for out in ["med_discount", "n_listed"]:
        lv_r, lv_p = stats.spearmanr(m[macro], m[out])
        d = m[[macro, out]].diff().dropna()
        fd_r, fd_p = stats.spearmanr(d[macro], d[out])
        rows.append(dict(macro_var=macro, outcome=out, n_months=len(m),
                         level_rho=round(lv_r, 4), level_p=round(lv_p, 6),
                         diff_rho=round(fd_r, 4), diff_p_raw=round(fd_p, 6),
                         note="2025-09 결측: 차분 1개는 2개월 간격"))

out = pd.DataFrame(rows)
out.to_csv(Path(__file__).parent / "19_corr_macro_month_diff.csv", index=False)
print(out.to_string(index=False))

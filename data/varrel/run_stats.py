# -*- coding: utf-8 -*-
"""
탐색적 변수 관계 전수 통계 (2026-07-27, 세션 ad-hoc — 파이프라인 정본 아님)

입력: data/processed/analysis_master.csv (798곳 × 17개월 × line, 4,732행 × 129열)
      + kfb_events.csv / site_disposal_summary.csv / site_round_excess.csv

패널 구조를 존중하는 3층 분해:
  [B] between-site  : 사업장별 평균으로 축약 → 횡단면 상관 (N≈798, 독립 단위)
  [W] within-site   : 사업장 평균 제거(demean) → 시간 변동 상관.
                      p값은 site 클러스터 부트스트랩(사이트 재표집)으로 산출
  [M] macro-month   : 전국 단일 시계열 변수는 월 그레인으로 축약 (유효 N=17!)
그 외:
  [C] 범주형: biz_class/region/constr_status × 결과변수 — Kruskal-Wallis, chi², Cramér's V
  [S] 생존: 유형/지역/규모 × 체류기간 — logrank + Cox
  [E] 사건: bid_cut/reappraisal/reset 발생 여부 × 선행 시장변수
모든 검정군에 BH-FDR (q) 부여.
"""
import json
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")
rng = np.random.default_rng(20260727)

from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
ROOT = str(_REPO)
OUT = str(_REPO / "data" / "varrel")

df = pd.read_csv(f"{ROOT}/data/source/analysis_master.csv")
ev = pd.read_csv(f"{ROOT}/data/source/kfb_events.csv")
disp = pd.read_csv(f"{ROOT}/data/source/site_disposal_summary.csv")
exc = pd.read_csv(f"{ROOT}/data/source/site_round_excess.csv")

# object로 저장된 불리언(True/False+NaN) 강제 숫자화
for c in ["reactivated", "kfb_understated", "hug_sago_sgg_flag"]:
    if df[c].dtype == object:
        df[c] = df[c].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0})
# 날짜(yyyymmdd) 컬럼은 발생 여부 플래그로 치환
for c in ["pms_after_exit", "stcns_after_exit"]:
    df[c] = df[c].notna().astype(float)

# ---------------------------------------------------------------- 변수 분류
ID_COLS = {"site_id", "line_id", "ym", "yq", "lawd_cd", "rent_yq_used",
           "exit_month", "lon", "lat"}
FLAG_COLS = {"natl_ffilled", "cci_matched", "line_ambiguous"}

num_cols = [c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c])]
num_cols = [c for c in num_cols if c not in ID_COLS | FLAG_COLS]
for c in num_cols:
    if pd.api.types.is_bool_dtype(df[c]):
        df[c] = df[c].astype(float)

# 그레인 자동 판별: 전국(월내 상수) / 사업장 상수 / 양방향 변동
grain = {}
g_month = df.groupby("month_key")
g_site = df.groupby("site_id")
for c in num_cols:
    nun_in_month = g_month[c].nunique(dropna=True).max()
    nun_in_site = g_site[c].nunique(dropna=True).max()
    if nun_in_month <= 1:
        grain[c] = "national_month"     # 월별 전국 단일값 (유효 N=17)
    elif nun_in_site <= 1:
        grain[c] = "site_const"         # 사업장 상수 (횡단면 전용)
    else:
        grain[c] = "site_month"

# 블록(계열) 지정 — 같은 블록 내 상관은 기계적/자명한 것으로 별도 표기
BLOCKS = {
    "rates": ["base_rate", "bank_loan_rate_all", "bank_corp_loan_rate",
              "bank_facility_loan_rate", "nonbank_corp_loan_rate",
              "corp_bond_AA3y", "corp_bond_BBB3y", "ktb_3y", "cd_91d",
              "spread_BBB_KTB", "spread_AA_KTB", "base_rate_chg_12m"],
    "cci": ["cci_total", "cci_bldg", "cci_resi", "cci_nonresi", "cci_plant",
            "cci_civil", "cci_yoy_pct"],
    "land_house": ["land_chg_pct", "land_chg_cum12_pct", "house_idx",
                   "house_idx_yoy_pct", "apt_idx", "apt_idx_yoy_pct"],
    "commercial": ["vac_office", "vac_midlarge", "rentidx_office",
                   "rentidx_midlarge", "yield_office", "yield_midlarge",
                   "capret_office", "capret_midlarge"],
    "rtms_land": ["rtms_land_n", "rtms_land_med_unit", "rtms_land_n_3m",
                  "rtms_land_unit_3m", "rtms_land_dae_n", "rtms_land_dae_med_unit",
                  "rtms_land_dae_n_3m", "rtms_land_dae_unit_3m", "rtms_land_n_yoy_pct"],
    "rtms_nrg": ["rtms_nrg_n", "rtms_nrg_med_unit", "rtms_nrg_n_3m",
                 "rtms_nrg_unit_3m", "rtms_nrg_n_yoy_pct"],
    "rtms_apt": ["rtms_apt_n", "rtms_apt_med_unit", "rtms_apt_n_3m",
                 "rtms_apt_unit_3m", "rtms_apt_n_yoy_pct"],
    "rtms_fac": ["rtms_fac_n", "rtms_fac_med_unit", "rtms_fac_n_3m",
                 "rtms_fac_unit_3m", "rtms_fac_n_yoy_pct"],
    "unsold": ["unsold_total", "unsold_completed", "unsold_pct_completed"],
    "valuation": ["appr_unit_land_mn_m2", "minbid_unit_land_mn_m2",
                  "appr_vs_rtms_dae_3m", "minbid_vs_rtms_dae_3m",
                  "appr_vs_rtms_all_3m", "minbid_vs_rtms_all_3m"],
    "site_price": ["appraisal_mn", "min_bid_mn", "discount_ratio", "round_no",
                   "n_rounds_m", "land_area_m2", "bldg_area_m2"],
    "hub": ["ap_pms_day", "ap_stcns_day", "ap_useapr_day", "br_useapr_day",
            "stcns_delay_days", "months_permit_idle"],
    "exit": ["exited", "reactivated", "pms_after_exit", "stcns_after_exit",
             "kfb_understated"],
    "excess": ["excess_pp_med"],
    "hug": ["hug_sago_sgg_flag", "hug_sago_n", "hug_sago_last_yr", "hug_sago_amt_mn"],
    "applyhome": ["ah_n_pblanc", "ah_supply_sum", "ah_under_ratio", "ah_rate_med",
                  "ah_sale_unit_med"],
    "kiscon": ["kiscon_cnt_pub", "kiscon_cnt_indiv", "kiscon_cnt_priv",
               "kiscon_cnt_all", "kiscon_amt_pub", "kiscon_amt_indiv",
               "kiscon_amt_priv", "kiscon_amt_all", "kiscon_cnt_priv_yoy_pct",
               "kiscon_amt_priv_yoy_pct"],
}
block_of = {}
for b, cols in BLOCKS.items():
    for c in cols:
        block_of[c] = b
for c in num_cols:
    block_of.setdefault(c, "misc")

pd.DataFrame({
    "variable": num_cols,
    "grain": [grain[c] for c in num_cols],
    "block": [block_of[c] for c in num_cols],
    "n_nonnull": [int(df[c].notna().sum()) for c in num_cols],
    "pct_missing": [round(100 * df[c].isna().mean(), 1) for c in num_cols],
}).to_csv(f"{OUT}/00_variable_inventory.csv", index=False)


def corr_table(data, cols, min_n, method_ps=True):
    """모든 쌍 Pearson+Spearman. list of dict."""
    rows = []
    arr = {c: data[c].values for c in cols}
    for i, a in enumerate(cols):
        for b_ in cols[i + 1:]:
            x, y = arr[a], arr[b_]
            m = ~(np.isnan(x) | np.isnan(y))
            n = int(m.sum())
            if n < min_n:
                continue
            xs, ys = x[m], y[m]
            if np.std(xs) == 0 or np.std(ys) == 0:
                continue
            pr, pp = stats.pearsonr(xs, ys)
            sr, sp = stats.spearmanr(xs, ys)
            rows.append(dict(var1=a, var2=b_, n=n, pearson_r=pr, pearson_p=pp,
                             spearman_r=sr, spearman_p=sp,
                             same_block=(block_of[a] == block_of[b_]),
                             block1=block_of[a], block2=block_of[b_]))
    return rows


def add_fdr(t, pcol="spearman_p"):
    if len(t) == 0:
        return t
    t = t.copy()
    t["q_fdr"] = multipletests(t[pcol].fillna(1.0), method="fdr_bh")[1]
    return t

# ---------------------------------------------------------------- [B] between-site
site_level = df.groupby("site_id")[num_cols].mean()
b_cols = [c for c in num_cols if site_level[c].notna().sum() >= 30]
tb = pd.DataFrame(corr_table(site_level.reset_index(), b_cols, min_n=30))
tb = add_fdr(tb)
tb.sort_values("q_fdr").to_csv(f"{OUT}/10_corr_between_site.csv", index=False)

# ---------------------------------------------------------------- [W] within-site
w_cols = [c for c in num_cols if grain[c] == "site_month"]
dm = df[["site_id"] + w_cols].copy()
dm[w_cols] = dm[w_cols] - dm.groupby("site_id")[w_cols].transform("mean")
# 변동이 실제로 있는 행만 의미 있음
tw = pd.DataFrame(corr_table(dm, w_cols, min_n=200))
if len(tw):
    # site-cluster bootstrap p (사이트 단위 재표집 500회) — 상위 후보만 (계산량 관리)
    tw["abs_r"] = tw["spearman_r"].abs()
    cand = tw[(~tw.same_block) & (tw.abs_r >= 0.05)].index
    sites = df["site_id"].values
    uniq_sites = df["site_id"].unique()
    site_rows = {s: np.where(sites == s)[0] for s in uniq_sites}
    boot_p = {}
    for idx in cand:
        a, b_ = tw.loc[idx, "var1"], tw.loc[idx, "var2"]
        x, y = dm[a].values, dm[b_].values
        m = ~(np.isnan(x) | np.isnan(y))
        obs = stats.spearmanr(x[m], y[m])[0]
        vals = []
        for _ in range(500):
            pick = rng.choice(uniq_sites, size=len(uniq_sites), replace=True)
            ii = np.concatenate([site_rows[s] for s in pick])
            xm, ym = x[ii], y[ii]
            mm = ~(np.isnan(xm) | np.isnan(ym))
            if mm.sum() < 50:
                continue
            vals.append(stats.spearmanr(xm[mm], ym[mm])[0])
        vals = np.array(vals)
        se = vals.std()
        boot_p[idx] = 2 * (1 - stats.norm.cdf(abs(obs) / se)) if se > 0 else np.nan
    tw["cluster_boot_p"] = pd.Series(boot_p)
    tw = add_fdr(tw)
    # cluster p 있는 것만 별도 FDR
    has = tw["cluster_boot_p"].notna()
    tw.loc[has, "q_cluster_fdr"] = multipletests(
        tw.loc[has, "cluster_boot_p"], method="fdr_bh")[1]
tw.sort_values("spearman_p").to_csv(f"{OUT}/11_corr_within_site.csv", index=False)

# ---------------------------------------------------------------- [M] macro-month
natl = [c for c in num_cols if grain[c] == "national_month"]
month_agg = df.groupby("month_key").agg(
    med_discount=("discount_ratio", "median"),
    mean_round=("round_no", "mean"),
    n_listed=("site_id", "nunique"),
    med_excess=("excess_pp_med", "median"),
)
ev_ok = ev[ev.suspect.isna()]
ev_m = ev_ok.groupby(["month_key", "event"]).size().unstack(fill_value=0)
risk = df.groupby("month_key")["site_id"].nunique()
for e in ["bid_cut", "reappraisal", "bid_reset"]:
    if e in ev_m:
        month_agg[f"rate_{e}"] = (ev_m[e] / risk * 100).reindex(month_agg.index)
natl_m = df.groupby("month_key")[natl].first()
M = natl_m.join(month_agg)
m_rows = []
for a in natl:
    for b_ in month_agg.columns:
        x, y = M[a].values, M[b_].values
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 10:
            continue
        if np.std(x[m]) == 0 or np.std(y[m]) == 0:
            continue
        sr, sp = stats.spearmanr(x[m], y[m])
        m_rows.append(dict(macro_var=a, outcome=b_, n_months=int(m.sum()),
                           spearman_r=sr, spearman_p=sp))
tm = add_fdr(pd.DataFrame(m_rows))
tm.sort_values("spearman_p").to_csv(f"{OUT}/12_corr_macro_month.csv", index=False)

# ---------------------------------------------------------------- [C] 범주형
df["biz5"] = df["biz_class"].where(
    df["biz_class"].isin(["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설"]))
site_cat = df.sort_values("month_key").groupby("site_id").agg(
    biz5=("biz5", "first"), region=("region", "first"), sido=("sido", "first"),
    constr=("constr_status", "first"))
site_all = site_level.join(site_cat)

c_rows = []
OUTCOMES_SITE = ["discount_ratio", "round_no", "exited", "reactivated",
                 "excess_pp_med", "stcns_delay_days", "months_permit_idle",
                 "appr_vs_rtms_dae_3m", "appraisal_mn", "n_rounds_m",
                 "kfb_understated"]
for cat in ["biz5", "region", "sido"]:
    for oc in OUTCOMES_SITE:
        sub = site_all[[cat, oc]].dropna()
        gs = [g[oc].values for _, g in sub.groupby(cat) if len(g) >= 8]
        if len(gs) < 2:
            continue
        H, p = stats.kruskal(*gs)
        meds = sub.groupby(cat)[oc].median().round(4).to_dict()
        c_rows.append(dict(test="kruskal", cat=cat, outcome=oc,
                           n=len(sub), stat=H, p=p, group_medians=json.dumps(meds, ensure_ascii=False)))
# 범주×범주
disp_site = disp.set_index("site_id")
site_all2 = site_all.join(disp_site[["outcome"]])
for a, b_ in [("biz5", "region"), ("biz5", "outcome"), ("region", "outcome")]:
    sub = site_all2[[a, b_]].dropna()
    ct = pd.crosstab(sub[a], sub[b_])
    ct = ct.loc[ct.sum(1) >= 8, ct.sum(0) >= 8]
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        continue
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    n = ct.values.sum()
    cramer = np.sqrt(chi2 / (n * (min(ct.shape) - 1)))
    c_rows.append(dict(test="chi2", cat=a, outcome=b_, n=int(n), stat=chi2, p=p,
                       group_medians=f"CramersV={cramer:.3f}"))
tc = add_fdr(pd.DataFrame(c_rows), pcol="p")
tc.sort_values("p").to_csv(f"{OUT}/13_categorical_tests.csv", index=False)

# ---------------------------------------------------------------- [S] 생존
from lifelines import CoxPHFitter
from lifelines.statistics import multivariate_logrank_test

surv = df.groupby("site_id").agg(
    first=("month_key", "min"), last=("month_key", "max"),
    exited=("exited", "max"), biz5=("biz5", "first"), region=("region", "first"),
    appraisal=("appraisal_mn", "mean"), land=("land_area_m2", "mean"),
    land_chg=("land_chg_cum12_pct", "mean"), unsold=("unsold_pct_completed", "mean"),
)
pm = pd.PeriodIndex(surv["last"], freq="M") - pd.PeriodIndex(surv["first"], freq="M")
surv["dur"] = [x.n + 1 for x in pm]
surv["event"] = surv["exited"].astype(int)
s_rows = []
for cat in ["biz5", "region"]:
    sub = surv.dropna(subset=[cat])
    res = multivariate_logrank_test(sub["dur"], sub[cat], sub["event"])
    s_rows.append(dict(test=f"logrank_{cat}", n=len(sub), stat=res.test_statistic,
                       p=res.p_value, note=""))
cox_df = surv.dropna(subset=["biz5"]).copy()
cox_df["log_appr"] = np.log1p(cox_df["appraisal"])
cox_df["capital"] = (cox_df["region"] == "수도권").astype(int)
dums = pd.get_dummies(cox_df["biz5"], prefix="t").drop(columns=["t_주거시설"])
X = pd.concat([cox_df[["dur", "event", "log_appr", "capital",
                       "land_chg", "unsold"]], dums], axis=1).dropna()
cph = CoxPHFitter()
cph.fit(X, "dur", "event")
cox_sum = cph.summary[["coef", "exp(coef)", "p"]].reset_index()
cox_sum.columns = ["covariate", "coef", "HR", "p"]
cox_sum.to_csv(f"{OUT}/15_cox_exit.csv", index=False)
for _, r in cox_sum.iterrows():
    s_rows.append(dict(test="cox_exit", n=len(X), stat=r["HR"], p=r["p"],
                       note=r["covariate"]))
ts = add_fdr(pd.DataFrame(s_rows), pcol="p")
ts.to_csv(f"{OUT}/14_survival_tests.csv", index=False)

# ---------------------------------------------------------------- [E] 사건 발생 ~ 선행 시장변수
ev_key = ev_ok[["site_id", "month_key", "event"]].drop_duplicates()
panel = df.copy()
panel["ymp"] = pd.PeriodIndex(panel["month_key"], freq="M")
for e in ["bid_cut", "reappraisal", "bid_reset"]:
    k = ev_key[ev_key.event == e].assign(flag=1).drop_duplicates(["site_id", "month_key"])
    panel = panel.merge(k[["site_id", "month_key", "flag"]].rename(columns={"flag": f"ev_{e}"}),
                        on=["site_id", "month_key"], how="left")
    panel[f"ev_{e}"] = panel[f"ev_{e}"].fillna(0)

DRIVERS = ["base_rate", "spread_BBB_KTB", "cci_yoy_pct", "land_chg_pct",
           "land_chg_cum12_pct", "apt_idx_yoy_pct", "unsold_total",
           "unsold_pct_completed", "rtms_apt_n_yoy_pct", "rtms_land_n_yoy_pct",
           "rtms_fac_n_yoy_pct", "vac_office", "ah_under_ratio",
           "kiscon_amt_priv_yoy_pct", "round_no", "discount_ratio",
           "appr_vs_rtms_dae_3m", "excess_pp_med", "months_permit_idle"]
e_rows = []
for e in ["bid_cut", "reappraisal", "bid_reset"]:
    yv = panel[f"ev_{e}"].values
    for d in DRIVERS:
        x = panel[d].values
        m = ~np.isnan(x)
        if m.sum() < 300 or yv[m].sum() < 8:
            continue
        x1, x0 = x[m][yv[m] == 1], x[m][yv[m] == 0]
        if len(x1) < 8:
            continue
        U, p = stats.mannwhitneyu(x1, x0, alternative="two-sided")
        # rank-biserial effect size
        rb = 1 - 2 * U / (len(x1) * len(x0))
        e_rows.append(dict(event=e, driver=d, n_event=len(x1), n_none=len(x0),
                           med_event=np.median(x1), med_none=np.median(x0),
                           rank_biserial=rb, p=p))
te = add_fdr(pd.DataFrame(e_rows), pcol="p")
te.sort_values("p").to_csv(f"{OUT}/16_event_vs_drivers.csv", index=False)

# ---------------------------------------------------------------- 초과할인 상세 (회차 그레인)
x_rows = []
exc2 = exc.dropna(subset=["excess_pp"])
for cat in ["usage_mid", "region_p"]:
    gs = [g["excess_pp"].values for _, g in exc2.groupby(cat) if len(g) >= 30]
    if len(gs) >= 2:
        H, p = stats.kruskal(*gs)
        meds = exc2.groupby(cat)["excess_pp"].median().round(2).to_dict()
        x_rows.append(dict(test="kruskal", var=cat, n=len(exc2), stat=H, p=p,
                           detail=json.dumps(meds, ensure_ascii=False)))
for v in ["round_no", "ym"]:
    sr, sp = stats.spearmanr(exc2[v], exc2["excess_pp"])
    x_rows.append(dict(test="spearman", var=v, n=len(exc2), stat=sr, p=sp, detail=""))
tx = add_fdr(pd.DataFrame(x_rows), pcol="p")
tx.to_csv(f"{OUT}/17_excess_discount_tests.csv", index=False)

# ---------------------------------------------------------------- 낙찰 소표본 (기술통계만)
sold = disp[disp.outcome == "낙찰"]
sold_desc = sold[["sale_to_appraisal_pct", "sale_to_minbid_pct", "n_rounds_observed"]].describe()
sold_desc.to_csv(f"{OUT}/18_sold_smallsample_desc.csv")

# ---------------------------------------------------------------- 요약 JSON
def top(t, k, cond):
    tt = t[cond(t)] if len(t) else t
    return tt.head(k).to_dict("records")

summary = {
    "n_rows": len(df), "n_sites": int(df.site_id.nunique()),
    "n_months": int(df.month_key.nunique()),
    "n_numeric_vars": len(num_cols),
    "grain_counts": pd.Series(grain).value_counts().to_dict(),
    "n_pairs_between": len(tb), "n_pairs_within": len(tw),
    "between_sig_crossblock": int(((tb.q_fdr < .05) & (~tb.same_block) & (tb.spearman_r.abs() >= .3)).sum()) if len(tb) else 0,
    "top_between": top(tb.assign(a=tb.spearman_r.abs()).sort_values("a", ascending=False),
                       40, lambda t: (t.q_fdr < .05) & (~t.same_block) & (t.a >= .3)),
    "top_within_clustersafe": top(tw.sort_values("cluster_boot_p"), 30,
                                  lambda t: (t.get("q_cluster_fdr", pd.Series(dtype=float)) < .05) & (~t.same_block)) if len(tw) else [],
    "macro_month_sig": top(tm.sort_values("spearman_p"), 20, lambda t: t.q_fdr < .10),
    "categorical_sig": top(tc.sort_values("p"), 25, lambda t: t.q_fdr < .05),
    "survival": ts.to_dict("records"),
    "event_drivers_sig": top(te.sort_values("p"), 25, lambda t: t.q_fdr < .05),
    "excess_tests": tx.to_dict("records"),
}
with open(f"{OUT}/summary.json", "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
print("DONE",
      "| between pairs:", len(tb),
      "| within pairs:", len(tw),
      "| macro tests:", len(tm),
      "| cat tests:", len(tc),
      "| event tests:", len(te))

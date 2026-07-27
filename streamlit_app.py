# -*- coding: utf-8 -*-
"""PF 사업장 애프터케어 대시보드.

공개 데이터(은행연합회 경공매 공시 + 시장변수)로 구축한 PF 사업장 가격 경로
패널(798곳 × 17개월)을 탐색하고, 점검이 필요한 사업장을 스크리닝한다.

실행:  streamlit run streamlit_app.py
데이터: data/panel_clean.csv · data/site_master.csv (pipeline/build_panel.py 산출)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent

# ── 팔레트 (검증된 기본 카테고리 순서 — 유형별 색은 엔티티 고정, 순환 금지) ──
C = {
    "주거시설": "#2a78d6",  # blue
    "상업시설": "#eb6834",  # orange
    "산업시설": "#1baf7a",  # aqua
    "업무시설": "#eda100",  # yellow
    "숙박시설": "#e87ba4",  # magenta
    "기타": "#898781",      # muted
}
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; SURFACE = "#fcfcfb"
STATUS = {"good": "#0ca30c", "warning": "#fab219",
          "serious": "#ec835a", "critical": "#d03b3b"}
S_APPRAISAL = "#2a78d6"   # 감정가 = slot1
S_MINBID = "#eb6834"      # 최저입찰가 = slot2

st.set_page_config(page_title="PF 애프터케어 대시보드", page_icon="📉",
                   layout="wide")


def biz5(s: pd.Series) -> pd.Series:
    main = ["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설"]
    return s.where(s.isin(main), "기타")


@st.cache_data
def load():
    panel = pd.read_csv(ROOT / "data" / "panel_clean.csv")
    sites = pd.read_csv(ROOT / "data" / "site_master.csv")
    loc_path = ROOT / "data" / "site_location.csv"
    if loc_path.exists():
        sites = sites.merge(pd.read_csv(loc_path), on="site_id", how="left")
    panel["biz5"] = biz5(panel["biz_class"])
    sites["biz5"] = biz5(sites["biz_class"])
    sites["sale_dt"] = pd.to_datetime(sites["sale_dt"], errors="coerce")
    for c in ["discount_last", "max_round", "n_months", "n_bid_cut",
              "excess_pp", "appr_vs_rtms", "land_chg_cum12_last",
              "minbid_drop_pct", "appraisal_first", "appraisal_last",
              "exited", "reactivated", "sale_price_mn", "sale_to_appraisal_pct"]:
        sites[c] = pd.to_numeric(sites[c], errors="coerce")
    return panel, sites


def chart_layout(fig, ytitle="", height=380):
    fig.update_layout(
        template="none", height=height,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif",
                  color=INK2, size=13),
        margin=dict(l=55, r=10, t=30, b=50),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0, font=dict(color=INK2)),
        xaxis=dict(showgrid=False, linecolor="#c3c2b7", tickfont=dict(color=MUTED)),
        yaxis=dict(title=ytitle, gridcolor=GRID, zerolinecolor=GRID,
                   tickfont=dict(color=MUTED)),
    )
    return fig


panel, sites = load()

st.title("PF 사업장 애프터케어 대시보드")
st.caption("공개 데이터 기반 · 사업장 798곳 × 2025-01~2026-06 · "
           "감정가·최저입찰가 경로와 위험 스크리닝 (본 화면의 '사업장'은 전부 "
           "은행연합회 공개 경공매 대상이며 특정 기관의 보유 자산이 아닙니다)")

# ─────────────────────────────── 사이드바 필터
with st.sidebar:
    st.header("필터")
    reg = st.multiselect("권역", sorted(sites["region"].dropna().unique()))
    sido_opts = sorted(sites.loc[sites["region"].isin(reg) if reg else slice(None),
                                 "sido"].dropna().unique()) \
        if reg else sorted(sites["sido"].dropna().unique())
    sido = st.multiselect("시도", sido_opts)
    b5 = st.multiselect("유형(대분류)",
                        ["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설", "기타"])
    bt_pool = sites.loc[sites["biz5"].isin(b5) if b5 else slice(None), "biz_type"]
    bt_opts = sorted(bt_pool.dropna().unique())
    if "bt_filter" in st.session_state:  # 대분류 변경 시 유효 선택만 보존
        st.session_state["bt_filter"] = [
            v for v in st.session_state["bt_filter"] if v in bt_opts]
    bt = st.multiselect("세부 유형", bt_opts, key="bt_filter",
                        help="예: 11-아파트, 31-오피스텔, 66-물류센터, 62-아파트형공장 "
                             "(냉동/냉장 창고 구분은 원천 데이터에 없어 '물류센터'로 통합)")
    amin, amax = st.slider(
        "감정가 범위 (억원)", 0, 5000, (0, 5000), step=50,
        help="최초 관측 감정가 기준")

mask = pd.Series(True, index=sites.index)
if reg:
    mask &= sites["region"].isin(reg)
if sido:
    mask &= sites["sido"].isin(sido)
if b5:
    mask &= sites["biz5"].isin(b5)
if bt:
    mask &= sites["biz_type"].isin(bt)
hi = np.inf if amax >= 5000 else amax * 100  # 슬라이더 상한 = 무제한
mask &= sites["appraisal_first"].fillna(0).between(amin * 100, hi)
f_sites = sites[mask]
f_panel = panel[panel["site_id"].isin(f_sites["site_id"])]

if f_sites.empty:
    st.warning("조건에 맞는 사업장이 없습니다. 필터를 완화해 주세요.")
    st.stop()

RISK_DEFAULTS = {"가격 소진": 20, "유찰 누적": 15, "장기 체류": 15, "저감 반복": 10,
                 "고가 유지": 15, "감정 괴리": 10, "지가 하락": 10, "산업시설": 5}


def risk_scores(s: pd.DataFrame, w: dict):
    """규칙 기반 위험 스코어 (스크리닝 탭·지도 공용)."""
    rules = pd.DataFrame({
        "가격 소진": (s["discount_last"] < 0.5),
        "유찰 누적": (s["max_round"] >= 5),
        "장기 체류": (s["n_months"] >= 12),
        "저감 반복": (s["n_bid_cut"] >= 2),
        "고가 유지": (s["excess_pp"] > 10),
        "감정 괴리": (s["appr_vs_rtms"] > 5),
        "지가 하락": (s["land_chg_cum12_last"] < 0),
        "산업시설": (s["biz5"] == "산업시설"),
    }).fillna(False)
    weights = pd.Series(w).reindex(rules.columns).fillna(0).astype(float)
    if weights.sum() == 0:
        weights = pd.Series(RISK_DEFAULTS).reindex(rules.columns).astype(float)
    score = rules.astype(float).mul(weights, axis=1).sum(axis=1) / weights.sum() * 100
    return rules, score


tab1, tab2, tab3, tab_map, tab4 = st.tabs(
    ["개요", "가격 시계열", "위험 스크리닝", "지도", "사내 데이터 결합(준비)"])

# ─────────────────────────────── 탭1 개요
with tab1:
    k = st.columns(5)
    k[0].metric("사업장", f"{len(f_sites):,}곳")
    k[1].metric("감정가 합계", f"{f_sites['appraisal_last'].sum()/1e6:,.1f}조원")
    exited_n = int(f_sites["exited"].fillna(0).sum())
    k[2].metric("공개 종료(이탈)", f"{exited_n:,}곳")
    react_n = int(f_sites["reactivated"].fillna(0).sum())
    k[3].metric("이탈 후 정상화", f"{react_n:,}곳")
    sold = f_sites[f_sites["outcome"] == "낙찰"]
    k[4].metric("낙찰 확인", f"{len(sold)}곳")

    left, right = st.columns(2)
    with left:
        st.subheader("유형 구성")
        order = ["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설", "기타"]
        vc = f_sites["biz5"].value_counts().reindex(order).dropna()
        fig = go.Figure(go.Bar(
            x=vc.index, y=vc.values,
            marker_color=[C[i] for i in vc.index],
            marker_line_width=0, width=0.55,
            hovertemplate="%{x}: %{y}곳<extra></extra>"))
        fig.update_traces(marker=dict(cornerradius=4))
        st.plotly_chart(chart_layout(fig, "사업장 수", 320),
                        width="stretch")
    with right:
        st.subheader("월별 공개 사업장 수")
        mc = f_panel.groupby("month_key")["site_id"].nunique()
        fig = go.Figure(go.Scatter(
            x=mc.index, y=mc.values, mode="lines",
            line=dict(color=C["주거시설"], width=2),
            hovertemplate="%{x}: %{y}곳<extra></extra>"))
        st.plotly_chart(chart_layout(fig, "곳", 320), width="stretch")

    st.subheader("유형별 핵심 지표 (필터 반영)")
    smry = (f_sites.groupby("biz5")
            .agg(사업장수=("site_id", "count"),
                 중앙_체류개월=("n_months", "median"),
                 중앙_최대회차=("max_round", "median"),
                 중앙_최저가하락pct=("minbid_drop_pct", "median"),
                 중앙_초과할인pp=("excess_pp", "median"),
                 중앙_감정배수=("appr_vs_rtms", "median"))
            .reindex(order).dropna(how="all").round(2))
    st.dataframe(smry, width="stretch")

# ─────────────────────────────── 탭2 시계열
with tab2:
    st.subheader("집계 경로 — 감정가·최저입찰가 중앙값")
    agg = (f_panel.groupby("month_key")
           .agg(appraisal=("appraisal_mn", "median"),
                minbid=("min_bid_mn", "median"),
                disc=("discount_ratio", "median")).reset_index())
    fig = go.Figure()
    fig.add_scatter(x=agg["month_key"], y=agg["appraisal"], name="감정가(중앙)",
                    mode="lines+markers", line=dict(color=S_APPRAISAL, width=2),
                    marker=dict(size=7),
                    hovertemplate="감정가 %{y:,.0f}백만원<extra></extra>")
    fig.add_scatter(x=agg["month_key"], y=agg["minbid"], name="최저입찰가(중앙)",
                    mode="lines+markers", line=dict(color=S_MINBID, width=2),
                    marker=dict(size=7),
                    hovertemplate="최저입찰가 %{y:,.0f}백만원<extra></extra>")
    st.plotly_chart(chart_layout(fig, "백만원"), width="stretch")

    st.subheader("최저입찰가/감정가 비율(중앙) — 저감 깊이")
    fig = go.Figure(go.Scatter(
        x=agg["month_key"], y=agg["disc"], mode="lines+markers",
        line=dict(color=S_MINBID, width=2), marker=dict(size=7),
        hovertemplate="비율 %{y:.3f}<extra></extra>"))
    st.plotly_chart(chart_layout(fig, "최저입찰가 ÷ 감정가", 300),
                    width="stretch")

    st.subheader("개별 사업장 경로")
    meta_lookup = (sites.set_index("site_id")[["address", "biz_type", "sido"]]
                   .fillna("미상"))
    pick = st.selectbox(
        "사업장 선택 (주소 · 유형 · 시도)",
        f_sites.sort_values("appraisal_last", ascending=False)["site_id"],
        format_func=lambda sid: " · ".join(map(str, meta_lookup.loc[sid])))
    sp = panel[panel["site_id"] == pick].sort_values(["month_key", "line_id"])
    line_pick = sp["line_id"].mode().iat[0]
    spl = sp[sp["line_id"] == line_pick]
    fig = go.Figure()
    fig.add_scatter(x=spl["month_key"], y=spl["appraisal_mn"], name="감정가",
                    mode="lines+markers", line=dict(color=S_APPRAISAL, width=2),
                    marker=dict(size=8))
    fig.add_scatter(x=spl["month_key"], y=spl["min_bid_mn"], name="최저입찰가",
                    mode="lines+markers", line=dict(color=S_MINBID, width=2),
                    marker=dict(size=8))
    for flag, label, color in [("ev_bid_cut", "▼ 저감", STATUS["serious"]),
                               ("ev_reappraisal", "◆ 재감정", STATUS["critical"]),
                               ("ev_bid_reset", "● 리셋", STATUS["warning"])]:
        evm = spl[spl[flag] == 1]
        if len(evm):
            fig.add_scatter(x=evm["month_key"], y=evm["min_bid_mn"],
                            name=label, mode="markers",
                            marker=dict(size=12, color=color,
                                        line=dict(width=2, color=SURFACE)))
    srow = sites.set_index("site_id").loc[pick]
    if pd.notna(srow.get("sale_price_mn")) and pd.notna(srow.get("sale_dt")):
        fig.add_scatter(x=[srow["sale_dt"].strftime("%Y-%m")],
                        y=[srow["sale_price_mn"]], name="★ 매각가", mode="markers",
                        marker=dict(size=14, color=STATUS["good"], symbol="star",
                                    line=dict(width=2, color=SURFACE)))
    # 매각월이 관측 범위 밖이어도 시간순 위치가 맞도록 사전순 정렬 강제
    fig.update_xaxes(type="category", categoryorder="category ascending")
    st.plotly_chart(chart_layout(fig, "백만원"), width="stretch")
    cc = st.columns(4)
    cc[0].metric("체류", f"{int(srow['n_months'])}개월")
    cc[1].metric("최대 회차", "-" if pd.isna(srow["max_round"]) else f"{int(srow['max_round'])}회")
    cc[2].metric("최저가 누적", "-" if pd.isna(srow["minbid_drop_pct"]) else f"{srow['minbid_drop_pct']:+.1f}%")
    cc[3].metric("처분 결과", srow["outcome"] if pd.notna(srow["outcome"]) else "공개중/미확인")
    with st.expander("이 사업장 원자료 (패널 행)"):
        st.dataframe(sp, width="stretch")

# ─────────────────────────────── 탭3 스크리닝
with tab3:
    st.subheader("점검 필요 사업장 스크리닝")
    st.caption("규칙 기반·설명 가능 스코어. 각 규칙은 Phase 1 통계 근거를 가짐 "
               "(docs/PHASE1_findings.md). 가중치는 조정 가능.")
    with st.expander("판단 규칙과 근거", expanded=False):
        st.markdown("""
| 규칙 | 임계 | 근거 |
|---|---|---|
| 가격 소진 | 최저가/감정가 < 0.5 | 8회차≈감정가 62% — 0.5 미만은 경로 후반부 |
| 유찰 누적 | 최대 회차 ≥ 5 | 유찰회차 누적 +0.24%p/회 하향 위험(방향 신호) |
| 장기 체류 | ≥ 12개월 | 중앙 7개월·12개월 잔존 32.9% — 상위 1/3 |
| 저감 반복 | 저감 사건 ≥ 2회 | 저감의 관성(사건월 비율 0.52 vs 0.61) |
| 시장 대비 고가 유지 | 초과할인 > +10%p | 주거 +20%p 계열 — 가격조정 지연 |
| 감정 괴리 | 감정가/실거래 배수 > 5 | 유형·지역 판별력 최상위 변수 |
| 지역 지가 하락 | 12개월 누적 < 0 | 지가 하락 지역 = 하향률 낮음 + 이탈 지연(HR 1.34의 역) |
| 수요 부재 유형 | 산업시설 | 체류 최장(HR 0.62)·염가에도 유찰 |
""")
        w = {}
        wc = st.columns(4)
        defaults = [("가격 소진", 20), ("유찰 누적", 15), ("장기 체류", 15),
                    ("저감 반복", 10), ("고가 유지", 15), ("감정 괴리", 10),
                    ("지가 하락", 10), ("산업시설", 5)]
        for i, (nm, dv) in enumerate(defaults):
            w[nm] = wc[i % 4].slider(nm, 0, 30, dv, key=f"w_{nm}")

    s = f_sites.copy()
    rules, score = risk_scores(s, w)
    s["위험점수"] = score.round(1)
    s["발동규칙"] = [" · ".join(rules.columns[m]) for m in rules.to_numpy()]

    thr = st.slider("표시 임계 점수", 0, 100, 40, step=5)
    loc_cols = [c for c in ["dist_ic_km", "dist_city_km", "city_name"] if c in s.columns]
    view = (s[s["위험점수"] >= thr]
            .sort_values("위험점수", ascending=False)
            [["site_id", "address", "biz_type", "sido", "위험점수", "발동규칙",
              "n_months", "max_round", "discount_last", "minbid_drop_pct",
              "excess_pp", "appraisal_last", "outcome"] + loc_cols]
            .rename(columns={"n_months": "체류(월)", "max_round": "최대회차",
                             "discount_last": "최저/감정", "minbid_drop_pct": "최저가누적%",
                             "excess_pp": "초과할인pp", "appraisal_last": "감정가(백만)",
                             "outcome": "처분결과", "dist_ic_km": "IC거리km",
                             "dist_city_km": "도시거리km", "city_name": "최근접도시"}))
    st.markdown(f"**{len(view):,}곳** / {len(s):,}곳이 임계 {thr}점 이상")
    st.dataframe(view, width="stretch", height=420)
    st.download_button("CSV 다운로드", view.to_csv(index=False).encode("utf-8-sig"),
                       "risk_screening.csv", "text/csv")

    st.subheader("위험점수 분포 (유형별)")
    order = ["주거시설", "상업시설", "산업시설", "업무시설", "숙박시설", "기타"]
    fig = go.Figure()
    for t in order:
        v = s.loc[s["biz5"] == t, "위험점수"].dropna()
        if len(v):
            fig.add_box(y=v, name=t, marker_color=C[t], boxpoints=False,
                        line=dict(width=2))
    fig.update_layout(showlegend=False)
    st.plotly_chart(chart_layout(fig, "위험점수", 340), width="stretch")

# ─────────────────────────────── 지도 탭
with tab_map:
    st.subheader("사업장 위치 지도")
    geo = f_sites.dropna(subset=["lon", "lat"]).copy()
    n_missing = len(f_sites) - len(geo)
    cap = f"좌표 확보 {len(geo):,}곳 표시"
    if n_missing:
        cap += f" (좌표 미해상 {n_missing:,}곳 제외 — 신규 택지 블록형 주소 등)"
    st.caption(cap)
    if geo.empty:
        st.info("현재 필터에 좌표 보유 사업장이 없습니다.")
    else:
        mode = st.radio("색상 기준", ["유형", "위험점수(기본 가중치)"],
                        horizontal=True, label_visibility="collapsed")
        _, gscore = risk_scores(geo, RISK_DEFAULTS)
        geo["위험점수"] = gscore.round(1)
        geo["표시크기"] = np.sqrt(geo["appraisal_last"].fillna(
            geo["appraisal_last"].median()).clip(lower=100))
        hover = {"biz_type": True, "appraisal_last": ":,.0f", "n_months": True,
                 "위험점수": True, "lon": False, "lat": False, "표시크기": False}
        for c in ["dist_ic_km", "city_name"]:
            if c in geo.columns:
                hover[c] = True
        import plotly.express as px
        if mode == "유형":
            fig = px.scatter_map(
                geo, lat="lat", lon="lon", color="biz5", size="표시크기",
                category_orders={"biz5": list(C.keys())},
                color_discrete_map=C, hover_name="address", hover_data=hover,
                size_max=16, zoom=6, center=dict(lat=36.2, lon=127.6), height=620)
        else:
            fig = px.scatter_map(
                geo, lat="lat", lon="lon", color="위험점수", size="표시크기",
                color_continuous_scale=["#cde2fb", "#86b6ef", "#3987e5",
                                        "#1c5cab", "#0d366b"],
                hover_name="address", hover_data=hover,
                size_max=16, zoom=6, center=dict(lat=36.2, lon=127.6), height=620)
        fig.update_layout(map_style="carto-positron",
                          margin=dict(l=0, r=0, t=10, b=0),
                          paper_bgcolor=SURFACE,
                          legend=dict(orientation="h", y=1.04, x=0,
                                      title_text=""))
        st.plotly_chart(fig, width="stretch")
        st.caption("마커 크기 = 감정가 규모 · IC거리/최근접 도시는 하버사인 직선거리(도로거리 아님) · "
                   "IC 좌표: OpenStreetMap(ODbL)")

# ─────────────────────────────── 탭4 사내 데이터 (placeholder)
with tab4:
    st.subheader("사내 데이터 결합 파이프라인 (Placeholder)")
    st.markdown("""
비공개 사내 데이터(여신 잔액, 사업성평가 등급, 관리 상태 등)를 확보하면 이 탭에서
공개 패널과 결합합니다. 스키마 규약은 `docs/INTERNAL_DATA_SPEC.md` 참조:

- **필수 키**: `site_id` 또는 `address`(주소 자동 매칭) · 선택 키: `month_key`(YYYY-MM)
- **값 컬럼**: 자동으로 `int_` 접두사가 붙어 공개 변수와 격리됩니다
- 업로드 데이터는 **세션 메모리에서만** 사용되며 서버에 저장되지 않습니다
""")
    up = st.file_uploader("사내 데이터 CSV 업로드 (스키마 검증만 수행)", type="csv")
    if up is not None:
        try:
            it = pd.read_csv(up)
            probs = []
            if "site_id" not in it.columns and "address" not in it.columns:
                probs.append("`site_id` 또는 `address` 컬럼이 필요합니다")
            if "month_key" in it.columns:
                bad = (~it["month_key"].astype(str).str.match(r"^\d{4}-\d{2}$")).sum()
                if bad:
                    probs.append(f"`month_key` 형식 오류 {bad}행 (YYYY-MM)")
            if probs:
                st.error("스키마 검증 실패:\n- " + "\n- ".join(probs))
            else:
                st.success(f"스키마 통과: {len(it):,}행 × {len(it.columns)}열 — "
                           "결합 시 아래 미리보기 형태로 편입됩니다")
                if "site_id" in it.columns:
                    hit = it["site_id"].isin(sites["site_id"]).mean() * 100
                    st.info(f"site_id 매칭률: {hit:.1f}%")
                st.dataframe(it.head(20), width="stretch")
        except Exception as e:  # noqa: BLE001
            st.error(f"파일을 읽을 수 없습니다: {e}")

st.divider()
st.caption("데이터 출처: 전국은행연합회 PF 정보공개, 온비드, 국토교통부 실거래가, "
           "한국부동산원 R-ONE, ECOS/KOSIS 등 공개 자료 · "
           "본 대시보드는 정보 제공 목적이며 투자 자문이 아닙니다.")

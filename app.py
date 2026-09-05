"""Geo-Swap — Petroleum Swap Rate Dashboard."""

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.loaders import load_all
from src.ai_brief import generate_briefing
from src.engine import (
    BENCHMARKS,
    COUNTRY_BENCHMARK,
    ETS_EUR_VINTAGE,
    EUR_KRW,
    USD_KRW,
    ETS_EUR,
    FREIGHT_PER_BBL_NM,
    GRADE_TO_DISCOUNT,
    HIGH_RISK_COUNTRIES,
    STRUCTURING_FEE_RATE,
    country_grade,
    country_quality_specs,
    country_year_totals,
    esg_swap_metrics,
    geo_discount,
    hhi_by_year,
    high_risk_share_by_year,
    ksure_country_risk,
    latest_swap_rate,
    load_oil_mining_risk,
    market_impact,
    middle_east_share_by_year,
    model_validation,
    monthly_swap_series,
    quality_adj,
    resolve_benchmark,
)
from src.chokepoints import (
    BYPASS_SHARE,
    CHOKEPOINTS,
    KAZAKH_CHAIN,
    alternatives,
    concentration_risk,
    esg_risk_tradeoff,
    exposure,
    serial_dependency,
)
from src.sanctions import (
    SDN_URL,
    SNAPSHOT_DATE,
    coverage as sdn_coverage,
    flag_risk_profile,
    origin_sanctions_note,
    program_summary,
    screen_vessel,
)
from src.shocks import (
    SPREAD_SHOCK_PP,
    classify_regime,
    country_gpr_innovation,
    credit_discount,
    delivery_discount,
    gpr_coverage,
    gpr_source,
    load_gpr_real,
    inventory_coverage,
    inventory_signal,
    monthly_regime_series,
)

DATA_SOURCE_FOOTER = (
    "데이터: 산업통상부 — 한국석유공사(국가별·유질별 원유수입, KOSIS TX_31801_A008·A009) · "
    "한국무역보험공사(국가신용등급) · 한국가스공사(EU ETS 탄소가격) | "
    "국제유가: World Bank Pink Sheet(Brent·Dubai·WTI) | "
    "지정학위험지수: Caldara & Iacoviello (2022, AER) | "
    "원유재고: 미국 EIA (OECD 상업재고 · 미국 상업재고) | "
    "연계: EIA(원유품질 API·황) | 운송거리(sea-distances 근사)·탄소계수(IMO) 기반 ESG 추정 | "
    "모델 검증: 페트로넷 CIF 도입단가"
)

GRADE_LABELS = {"light": "경질유", "medium": "중(中)질유", "heavy": "중(重)질유"}


def default_ets_eur(eu_ets: pd.DataFrame) -> float:
    """Latest EU ETS annual average (€/ton) from bundled CSV."""
    if eu_ets is None or eu_ets.empty:
        return ETS_EUR
    latest = eu_ets.sort_values("연도").iloc[-1]
    return float(latest["연평균(Euro)"])


def esg_country_options() -> list[str]:
    return sorted(COUNTRY_BENCHMARK.keys())


def fmt_eok_krw(value: float) -> str:
    return f"₩{value / 1e8:,.0f}억"


def fmt_man_ton(value: float) -> str:
    return f"{value / 1e4:,.0f}만 톤"


def fmt_eok_bbl(value: float) -> str:
    return f"{value / 1e8:.1f}억 배럴"


@st.cache_data
def get_data():
    return load_all()


def footer():
    st.caption(DATA_SOURCE_FOOTER)


def render_hero():
    """클린한 제목 헤더 (사진 없이 미니멀·프로페셔널)."""
    st.title("🛢️ Geo-Swap")
    st.markdown(
        "**원자재 수입 법인 금융소비자를 위한 AI 무역금융 리스크·보안 비서**" + chr(10) + chr(10) +
        "나프타·벙커C유 등 파생 원자재를 **수입신용장**(L/C)으로 들여오는 중견·중소 법인과 "
        "그 은행을 위해, **지정학 조달 리스크**와 **OFAC 제재 위반 위험**을 함께 계량한다."
    )


def tab_import_structure(countries):
    st.header("원유 수입 구조")
    years = sorted(countries["연도"].unique())
    year = st.slider("연도", min(years), max(years), value=max(years))

    year_df = country_year_totals(countries, year)
    year_df = year_df[year_df["물량_천배럴"] > 0]

    col1, col2 = st.columns(2)
    with col1:
        fig_tree = px.treemap(
            year_df,
            path=["대륙", "국가"],
            values="물량_천배럴",
            title=f"{year}년 대륙·국가별 수입 (천 배럴)",
            color="물량_천배럴",
            color_continuous_scale="Blues",
        )
        fig_tree.update_layout(margin=dict(t=40, l=10, r=10, b=10))
        st.plotly_chart(fig_tree, use_container_width=True)

    with col2:
        top15 = year_df.nlargest(15, "물량_천배럴")
        fig_bar = px.bar(
            top15.sort_values("물량_천배럴"),
            x="물량_천배럴",
            y="국가",
            orientation="h",
            color="대륙",
            title=f"{year}년 상위 15개국 수입량",
            labels={"물량_천배럴": "천 배럴", "국가": ""},
        )
        for country in HIGH_RISK_COUNTRIES:
            if country in top15["국가"].values:
                fig_bar.add_annotation(
                    x=top15.loc[top15["국가"] == country, "물량_천배럴"].values[0],
                    y=country,
                    text="⚠ 고위험",
                    showarrow=True,
                    arrowhead=2,
                    ax=40,
                    font=dict(color="red", size=11),
                )
        st.plotly_chart(fig_bar, use_container_width=True)

    hhi = hhi_by_year(countries)
    me_share = middle_east_share_by_year(countries)
    risk_share = high_risk_share_by_year(countries)

    fig_trend = make_subplots(specs=[[{"secondary_y": True}]])
    fig_trend.add_trace(
        go.Scatter(x=hhi["연도"], y=hhi["HHI"], name="HHI (집중도)", mode="lines+markers"),
        secondary_y=False,
    )
    fig_trend.add_trace(
        go.Scatter(
            x=me_share["연도"],
            y=me_share["중동_의존도_pct"],
            name="중동 의존도 (%)",
            mode="lines+markers",
            line=dict(dash="dot"),
        ),
        secondary_y=True,
    )
    fig_trend.update_layout(
        title="수입 집중도(HHI) & 중동 의존도 추이",
        xaxis_title="연도",
        legend=dict(orientation="h", y=-0.15),
    )
    fig_trend.update_yaxes(title_text="HHI (0–1)", secondary_y=False)
    fig_trend.update_yaxes(title_text="중동 의존도 (%)", secondary_y=True)
    fig_trend.update_xaxes(dtick=1, tickformat="d")
    st.plotly_chart(fig_trend, use_container_width=True)

    fig_risk = go.Figure()
    fig_risk.add_trace(
        go.Scatter(
            x=risk_share["연도"],
            y=risk_share["고위험국_비중_pct"],
            mode="lines+markers+text",
            name="러시아+카자흐스탄",
            line=dict(color="crimson", width=3),
            marker=dict(size=10),
            text=[f"{v:.1f}%" for v in risk_share["고위험국_비중_pct"]],
            textposition="top center",
        )
    )
    fig_risk.add_vrect(x0=2022.5, x1=2024.5, fillcolor="red", opacity=0.08, line_width=0)
    fig_risk.add_annotation(
        x=2023,
        y=risk_share["고위험국_비중_pct"].max() * 0.85,
        text="전쟁·제재·파이프라인 리스크<br>→ 러시아 수입 0, 카자흐 급감",
        showarrow=False,
        font=dict(color="crimson", size=12),
        bgcolor="rgba(255,255,255,0.8)",
    )
    fig_risk.update_layout(
        title="⭐ 고위험국(러시아+카자흐스탄) 노출 비중 추이",
        xaxis_title="연도",
        yaxis_title="비중 (%)",
        yaxis=dict(rangemode="tozero"),
    )
    fig_risk.update_xaxes(dtick=1, tickformat="d")
    st.plotly_chart(fig_risk, use_container_width=True)

    st.subheader("국가별 연도별 수입량 (천 배럴)")
    pivot = countries.pivot_table(
        index=["대륙", "국가"], columns="연도", values="물량_천배럴", fill_value=0
    )
    st.dataframe(pivot, use_container_width=True)


def tab_grade_composition(grades, grades_monthly):
    st.header("유질 구성")
    grades = grades.copy()
    grades["유질_한글"] = grades["유질"].map(GRADE_LABELS)

    yearly = grades.groupby(["연도", "유질"]).agg({"물량_천배럴": "sum"}).reset_index()
    yearly["유질_한글"] = yearly["유질"].map(GRADE_LABELS)

    fig_area = px.area(
        yearly,
        x="연도",
        y="물량_천배럴",
        color="유질_한글",
        title="유질별 원유 수입 추이 (천 배럴)",
        labels={"물량_천배럴": "천 배럴", "연도": "연도"},
        category_orders={"유질_한글": list(GRADE_LABELS.values())},
    )
    fig_area.update_xaxes(dtick=1, tickformat="d")
    st.plotly_chart(fig_area, use_container_width=True)

    fig_share = px.area(
        yearly,
        x="연도",
        y="물량_천배럴",
        color="유질_한글",
        groupnorm="percent",
        title="유질별 비중 추이 (%)",
        labels={"물량_천배럴": "비중 (%)", "연도": "연도"},
        category_orders={"유질_한글": list(GRADE_LABELS.values())},
    )
    fig_share.update_xaxes(dtick=1, tickformat="d")
    st.plotly_chart(fig_share, use_container_width=True)

    if grades_monthly is not None:
        st.subheader("2024년 월별 유질 추이")
        monthly = grades_monthly.copy()
        monthly["유질_한글"] = monthly["유질"].map(GRADE_LABELS)
        fig_m = px.line(
            monthly,
            x="월",
            y="물량_천배럴",
            color="유질_한글",
            markers=True,
            title="2024년 월별 유질별 수입 (천 배럴)",
            labels={"물량_천배럴": "천 배럴", "월": "월"},
        )
        st.plotly_chart(fig_m, use_container_width=True)


def tab_oil_prices(prices):
    st.header("국제유가 & 스프레드")

    fig_prices = px.line(
        prices,
        x="연월",
        y=BENCHMARKS,
        title="벤치마크 월별 유가 ($/배럴)",
        labels={"value": "$/배럴", "연월": "연월", "variable": "유종"},
    )
    fig_prices.update_layout(legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig_prices, use_container_width=True)

    spread_df = prices[["연월", "연도"]].copy()
    spread_df["Brent−WTI"] = prices["Brent"] - prices["WTI"]
    spread_df["Brent−Dubai"] = prices["Brent"] - prices["Dubai"]

    fig_spread = px.line(
        spread_df,
        x="연월",
        y=["Brent−WTI", "Brent−Dubai"],
        title="유종 간 스프레드 ($/배럴)",
        labels={"value": "$/배럴", "연월": "연월", "variable": "스프레드"},
    )
    st.plotly_chart(fig_spread, use_container_width=True)

    annual = prices.groupby("연도")[BENCHMARKS].mean().reset_index()
    st.subheader("연도별 평균 유가")
    st.dataframe(annual.style.format({b: "{:.2f}" for b in BENCHMARKS}), use_container_width=True)


def tab_deep_analysis(countries, gpr_region_monthly, oil_quality, ksure_grades):
    st.header("🔍 심층분석")
    st.caption("독립된 두 공공데이터가 같은 사건을 어떻게 보여주는지 확인하는 탭입니다.")
    st.caption(f"K-SURE 표본 {len(ksure_grades):,}건 · 품질 표본 {len(oil_quality):,}건")

    years = sorted(countries["연도"].unique())
    year = st.slider("버블 기준 연도", min_value=min(years), max_value=max(years), value=max(years))

    # 1) GPR ↔ 수입 상관
    # 진본 GPR (Caldara & Iacoviello 2022) 사용. 폐기된 AI-GPR을 쓰지 않는다.
    _gr = load_gpr_real()
    if not _gr.empty and "GPR_REAL_Russia" in _gr.columns:
        gpr_df = _gr[["Date", "GPR_REAL_Russia"]].rename(columns={"GPR_REAL_Russia": "GPR_OIL_Russia"}).copy()
        gpr_df["Date"] = pd.to_datetime(gpr_df["Date"])
        _gpr_label = "진본 GPR — 러시아 (Caldara & Iacoviello 2022)"
    else:
        gpr_df = gpr_region_monthly[["Date", "GPR_OIL_Russia"]].copy()
        _gpr_label = "GPR — 러시아"
    rus_import = (
        countries[countries["국가"] == "러시아"]
        .groupby("연도", as_index=False)["물량_천배럴"]
        .sum()
        .rename(columns={"물량_천배럴": "러시아_수입량"})
    )
    rus_import["Date"] = pd.to_datetime(rus_import["연도"].astype(str) + "-12-31")
    gpr_max = float(gpr_df["GPR_OIL_Russia"].max())

    fig_corr = make_subplots(specs=[[{"secondary_y": True}]])
    fig_corr.add_trace(
        go.Scatter(
            x=gpr_df["Date"],
            y=gpr_df["GPR_OIL_Russia"],
            mode="lines",
            name=_gpr_label,
            line=dict(color="#1f77b4", width=2.5),
        ),
        secondary_y=False,
    )
    fig_corr.add_trace(
        go.Scatter(
            x=rus_import["Date"],
            y=rus_import["러시아_수입량"],
            mode="lines+markers",
            name="한국 러시아 원유 수입량 (연별)",
            line=dict(color="crimson", width=3, dash="dot"),
            marker=dict(size=8),
        ),
        secondary_y=True,
    )
    spike_row = gpr_df.loc[gpr_df["Date"] == pd.Timestamp("2022-03-01")]
    if not spike_row.empty and not rus_import.empty:
        spike_y = float(spike_row.iloc[0]["GPR_OIL_Russia"])
        import_2022 = rus_import.loc[rus_import["연도"] == 2022, "러시아_수입량"]
        if not import_2022.empty:
            fig_corr.add_annotation(
                x=pd.Timestamp("2022-03-01"),
                y=spike_y,
                yref="y",
                text="2022-03 GPR 급등",
                showarrow=True,
                arrowhead=2,
                ax=25,
                ay=-35,
                font=dict(color="#1f77b4"),
            )
            fig_corr.add_annotation(
                x=pd.Timestamp("2022-12-31"),
                y=float(import_2022.iloc[0]),
                yref="y2",
                text="러시아 수입 절벽",
                showarrow=True,
                arrowhead=2,
                ax=30,
                ay=-35,
                font=dict(color="crimson"),
            )
    fig_corr.update_layout(
        title="GPR ↔ 러시아 원유 수입 상관",
        xaxis_title="시점",
        legend=dict(orientation="h", y=-0.2),
    )
    fig_corr.update_yaxes(
        title_text="지정학위험지수 (러시아)",
        range=[0, gpr_max * 1.15],
        secondary_y=False,
    )
    fig_corr.update_yaxes(
        title_text="한국 러시아 원유 수입량 (천 배럴)",
        rangemode="tozero",
        secondary_y=True,
    )
    st.plotly_chart(fig_corr, use_container_width=True)
    st.caption("독립된 두 공공데이터가 같은 사건을 증명: 2022-03 지정학 충격과 이후 수입 급감.")

    # 2) 품질-지정학 사분면
    import_year = countries[countries["연도"] == year].groupby("국가", as_index=False)["물량_천배럴"].sum()
    quality = oil_quality.copy()
    quality["K-SURE_국가등급"] = quality["국가명"].map(country_grade)
    quality = quality.merge(import_year, left_on="국가명", right_on="국가", how="left")
    quality["물량_천배럴"] = quality["물량_천배럴"].fillna(0)
    quality = quality.dropna(subset=["API_비중", "K-SURE_국가등급"]).copy()

    fig_quad = px.scatter(
        quality,
        x="API_비중",
        y="K-SURE_국가등급",
        size="물량_천배럴",
        color="황함량_pct",
        hover_name="국가명",
        hover_data={"API_비중": ":.1f", "황함량_pct": ":.2f", "K-SURE_국가등급": True, "물량_천배럴": ":,.0f"},
        size_max=38,
        title=f"품질-지정학 사분면 (버블={year}년 수입량)",
        labels={"API_비중": "API", "K-SURE_국가등급": "K-SURE 등급", "황함량_pct": "황함량(%)", "물량_천배럴": "수입량"},
        color_continuous_scale="Viridis",
    )
    kaz = quality[quality["국가명"] == "카자흐스탄"]
    if not kaz.empty:
        row = kaz.iloc[0]
        fig_quad.add_annotation(
            x=float(row["API_비중"]),
            y=float(row["K-SURE_국가등급"]),
            text="고품질인데 지정학으로 저평가<br>= 스왑 차익 기회",
            showarrow=True,
            arrowhead=2,
            ax=30,
            ay=-35,
            bgcolor="rgba(255,255,255,0.85)",
            font=dict(color="black"),
        )
        fig_quad.add_trace(
            go.Scatter(
                x=[float(row["API_비중"])],
                y=[float(row["K-SURE_국가등급"])],
                mode="markers",
                marker=dict(size=22, color="red", symbol="x"),
                name="카자흐스탄 강조",
            )
        )
    fig_quad.update_layout(
        xaxis_title="API (높을수록 경질)",
        yaxis_title="K-SURE 등급 (높을수록 위험)",
        coloraxis_colorbar_title="황함량(%)",
    )
    st.plotly_chart(fig_quad, use_container_width=True)

    with st.expander("해석 메모"):
        st.write(
            "카자흐스탄은 API가 높아 품질 프리미엄이 가능하지만, K-SURE 등급과 러시아 경유 리스크 때문에 "
            "시장에서는 저평가되기 쉽습니다. 이런 괴리가 스왑 차익의 출발점입니다."
        )


def tab_esg_savings(eu_ets: pd.DataFrame):
    st.header("🌱 ESG 절감")
    st.markdown(
        "위험 산지 원유를 안전 산지 원유로 **스왑**하면 실물 항로가 짧아져 "
        "**탄소발자국·운임**을 절감할 수 있습니다."
    )

    countries = esg_country_options()
    default_ets = default_ets_eur(eu_ets)

    col_a, col_b, col_vol, col_carbon = st.columns(4)
    with col_a:
        idx_a = countries.index("카자흐스탄") if "카자흐스탄" in countries else 0
        country_from = st.selectbox("위험 산지 A", countries, index=idx_a)
    with col_b:
        idx_b = countries.index("사우디아라비아") if "사우디아라비아" in countries else 0
        country_to = st.selectbox("안전 산지 B", countries, index=idx_b)
    with col_vol:
        volume_bbl = st.number_input(
            "거래량 (배럴)",
            min_value=1000,
            max_value=2_000_000,
            value=1_000_000,
            step=100_000,
        )
    with col_carbon:
        ets_eur = st.number_input(
            "탄소가격 (€/톤)",
            key="esg_ets_eur",
            min_value=0.0,
            value=float(default_ets),
            step=1.0,
            format="%.2f",
        )

    metrics = esg_swap_metrics(
        country_from,
        country_to,
        float(volume_bbl),
        ets_eur=ets_eur,
        eur_krw=EUR_KRW,
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("운송거리 절감", f"{metrics['distance_saved_nm']:,.0f} nm")
    with m2:
        st.metric("탄소발자국 절감", f"{metrics['co2_saved_ton']:,.0f} t CO₂")
    with m3:
        st.metric("탄소가치", f"₩{metrics['carbon_value_krw']:,.0f}")
    with m4:
        st.metric("운임 절감", f"${metrics['freight_saved_usd']:,.0f}")

    fig_co2 = go.Figure(
        data=[
            go.Bar(
                x=["직도입 (A→한국)", "스왑 (B→한국)"],
                y=[metrics["co2_direct_ton"], metrics["co2_swap_ton"]],
                marker_color=["crimson", "seagreen"],
                text=[
                    f"{metrics['co2_direct_ton']:,.0f} t",
                    f"{metrics['co2_swap_ton']:,.0f} t",
                ],
                textposition="outside",
            )
        ]
    )
    fig_co2.update_layout(
        title=f"탄소발자국 비교 — {country_from} 직도입 vs {country_to} 스왑",
        yaxis_title="톤 CO₂",
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig_co2, use_container_width=True)

    with st.expander("계산 근거·가정"):
        st.markdown(
            f"- **항로 거리**: sea-distances.org 기반 근사 "
            f"(A {metrics['distance_from_nm']:,.0f} nm → B {metrics['distance_to_nm']:,.0f} nm, "
            f"절감 {metrics['distance_saved_nm']:,.0f} nm)\n"
            f"- **탄소계수**: ≈0.3 g CO₂/(배럴·해리) — IMO VLCC 벙커유 소비 근사\n"
            f"- **운임계수**: ${FREIGHT_PER_BBL_NM} / (배럴·해리)\n"
            f"- **탄소가격**: 한국가스공사 제공 EU ETS €{ets_eur:.2f}/톤 (**{ETS_EUR_VINTAGE}년 연평균**) × ₩{EUR_KRW:,.0f}/€"
        )


def tab_market_impact(countries: pd.DataFrame, eu_ets: pd.DataFrame, prices: pd.DataFrame):
    st.header("📈 시장규모·임팩트")
    st.markdown(
        "한국 **원유 도입 전체**를 Geo-Swap 관점에서 합산한 연간 시장규모와 "
        "ESG·금융 임팩트 추정입니다. (공공데이터 기반 보수적 추정)"
    )

    years = sorted(countries["연도"].unique())
    default_ets = default_ets_eur(eu_ets)

    col_year, col_fee, col_ets = st.columns(3)
    with col_year:
        year = st.selectbox("기준 연도", years, index=len(years) - 1)
    with col_fee:
        fee_rate = st.slider(
            "구조화 수수료율 (가정)",
            min_value=0.001,
            max_value=0.02,
            value=STRUCTURING_FEE_RATE,
            step=0.001,
            format="%.3f",
        )
    with col_ets:
        ets_eur = st.number_input(
            "탄소가격 (€/톤)",
            key="mi_ets_eur",
            min_value=0.0,
            value=float(default_ets),
            step=1.0,
            format="%.2f",
        )

    # 수수료 산출에 쓰는 유종가를 하드코딩 대신 **데이터의 최신 관측치**로 쓴다
    _px = prices.dropna(subset=["Dubai"]).sort_values("연월")
    _crude = float(_px.iloc[-1]["Dubai"]) if len(_px) else None
    _crude_ym = str(_px.iloc[-1]["연월"]) if len(_px) else "—"

    impact = market_impact(
        countries,
        year=int(year),
        fee_rate=fee_rate,
        ets_eur=ets_eur,
        eur_krw=EUR_KRW,
        usd_krw=USD_KRW,
        crude_price_usd=_crude,
    )
    swap_share_pct = (
        impact["스왑대상물량"] / impact["총물량"] * 100 if impact["총물량"] else 0.0
    )

    h1, h2, h3 = st.columns(3)
    with h1:
        st.metric("연간 시장규모", fmt_eok_krw(impact["총시장_원"]))
    with h2:
        st.metric("CO₂ 절감", fmt_man_ton(impact["탄소절감_t"]))
    with h3:
        st.metric(
            "스왑 대상",
            fmt_eok_bbl(impact["스왑대상물량"]),
            delta=f"도입의 {swap_share_pct:.0f}%",
        )

    st.info(
        f"CO₂ {fmt_man_ton(impact['탄소절감_t'])} = "
        f"🌳 **나무 {impact['나무'] / 1e4:,.0f}만 그루** / "
        f"🚗 **승용차 {impact['승용차'] / 1e4:,.1f}만 대** 1년치"
    )

    st.subheader("Win-Win-Win 가치 분해")
    win1, win2, win3 = st.columns(3)
    with win1:
        st.metric("정유사 운임절감", fmt_eok_krw(impact["운임절감_원"]))
    with win2:
        st.metric("환경 탄소가치", fmt_eok_krw(impact["탄소가치_원"]))
    with win3:
        st.metric("플랫폼 신규수익", fmt_eok_krw(impact["하나수익_원"]))
    st.caption("고객·지구·플랫폼 3자 모두 이득 — ESG형 미래금융")

    fig_breakdown = go.Figure(
        data=[
            go.Bar(
                x=["정유사 운임절감", "환경 탄소가치", "플랫폼 신규수익"],
                y=[
                    impact["운임절감_원"] / 1e8,
                    impact["탄소가치_원"] / 1e8,
                    impact["하나수익_원"] / 1e8,
                ],
                marker_color=["#1f77b4", "#2ca02c", "#ff7f0e"],
                text=[
                    fmt_eok_krw(impact["운임절감_원"]),
                    fmt_eok_krw(impact["탄소가치_원"]),
                    fmt_eok_krw(impact["하나수익_원"]),
                ],
                textposition="outside",
            )
        ]
    )
    fig_breakdown.update_layout(
        title=f"{year}년 Geo-Swap 가치 분해 (억 원)",
        yaxis_title="억 원",
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig_breakdown, use_container_width=True)

    per_country = impact["per_country"]
    if not per_country.empty:
        st.subheader("국가별 기여 Top 8")
        top8 = per_country.head(8).sort_values("가치_원")
        fig_top = px.bar(
            top8,
            x="가치_원",
            y="국가",
            orientation="h",
            title=f"{year}년 스왑 가치 기여 상위 8개국",
            labels={"가치_원": "가치 (원)", "국가": ""},
            text=top8["가치_원"].apply(lambda v: fmt_eok_krw(v)),
        )
        fig_top.update_traces(textposition="outside")
        fig_top.update_layout(yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig_top, use_container_width=True)

    st.markdown(
        "본 추정은 **크루드·한국·1년** 기준입니다. "
        "가스(한국가스공사)·타 수입국·누적 적용 시 **수조 원 규모**로 확대될 수 있습니다."
    )

    st.error(
        "**⚠ 이 탭의 최적 방향은 「🚢 초크포인트 노출」 탭과 정반대다.**  "
        "ESG 모형은 항로가 짧은 **중동** 6,400nm으로 갈수록 좋다고 말한다. "
        "그런데 중동은 **호르무즈와 말라카를 모두** 지나야 하는, 관문 노출이 가장 큰 산지다. "
        "미국은 항로가 1.5배(9,500nm) 길지만 **관문을 하나도 지나지 않는다**(태평양 항로).  "
        "→ **탄소를 최소화하는 조달 구조가 관문 리스크를 최대화한다.** "
        "두 목표는 같은 방향이 아니며, 이 상충을 모르고 ESG 수치만 보면 위험한 결론에 이른다."
    )

    with st.expander("가정·계산 근거 (방어용)"):
        st.markdown(
            f"- **거리**: sea-distances.org 기반 근사, 안전 인도 기준 {6400:,} nm (중동→한국)\n"
            f"- **탄소계수**: IMO VLCC 근사 ≈0.3 g CO₂/(배럴·해리) = 3e-7 t/(배럴·해리)\n"
            f"- **운임계수**: ${FREIGHT_PER_BBL_NM} / (배럴·해리)\n"
            f"- **탄소가격**: 한국가스공사 EU ETS €{ets_eur:.2f}/톤 × ₩{EUR_KRW:,}/€\n"
            f"- **수수료율**: {fee_rate:.1%} (가정·슬라이더 조정 가능)\n"
            f"- **스왑 대상**: 중동보다 먼 항로 국가 수입 전량 (거리 절감 > 0)\n"
            "- 모든 계수는 공공데이터·업계 표준 기반의 **보수적 추정**입니다."
        )

    st.divider()
    v = model_validation(countries, prices)
    st.subheader("가격 패스스루 정합성 확인 — 공공데이터 대조")
    c1, c2, c3 = st.columns(3)
    c1.metric("모델 추정 도입가", f"${v['model_price']:.2f}")
    c2.metric("페트로넷 실제 FOB", f"${v['fob_ref']:.2f}", f"오차 {v['fob_err_pct']:+.1f}%", delta_color="off")
    c3.metric("페트로넷 실제 CIF", f"${v['cif_ref']:.2f}", f"오차 {v['cif_err_pct']:+.1f}%", delta_color="off")

    fig_val = go.Figure(
        data=[
            go.Bar(
                x=["모델 추정", "페트로넷 FOB", "페트로넷 CIF"],
                y=[v["model_price"], v["fob_ref"], v["cif_ref"]],
                marker_color=["#1f77b4", "#2ca02c", "#ff7f0e"],
                text=[
                    f"${v['model_price']:.2f}",
                    f"${v['fob_ref']:.2f}",
                    f"${v['cif_ref']:.2f}",
                ],
                textposition="outside",
            )
        ]
    )
    fig_val.update_layout(
        title="도입단가 비교 ($/배럴)",
        yaxis_title="$/배럴",
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig_val, use_container_width=True)
    st.caption(
        f"수입량 가중평균 도입가가 페트로넷 실제 FOB와 **{abs(v['fob_err_pct']):.2f}%** 차이. "
        f"CIF와의 차이({abs(v['cif_err_pct']):.1f}%)는 **운임 성분**이며 ESG 탭의 운임 모델과 정합한다. "
        f"(기준: {v['period']}, 도입가는 운임 미포함 spot 기준)"
    )
    st.warning(
        "**이것을 '모델 검증'이라 부르지 않는다.** 이 모델의 수입량 가중 배수는 "
        f"**{v['multiplier']:.4f}** — 즉 산출가는 사실상 **Dubai의 패스스루**다. "
        "따라서 도입가 지수와 맞는 것은 당연하며, **품질보정·신용할인이 옳다는 증거가 되지 못한다.** "
        "가격 스케일이 어긋나지 않았다는 **정합성 확인**으로만 읽어야 한다."
    )
    st.success(
        "**이 서비스의 실제 검증은 「⚡ 국면 판정」 탭에 있다.** "
        "2022 우크라이나(생산자 충격)와 2026 호르무즈(수송로 충격)라는 **두 독립 사건**에서 "
        "국면 분류가 각각 맞았고, 분류기는 2022 사건에 맞춰 조정된 적이 없다."
    )


def tab_swap_calculator(prices):
    st.header("⭐ 석유 환율 계산기")
    st.markdown(
        "**석유 환율(Petroleum Swap Rate)** = 두 유종 간 가치 교환 비율 "
        "(A 1배럴 = B 몇 배럴)"
    )

    country_options = sorted(COUNTRY_BENCHMARK.keys())
    all_options_a = [f"{c} ({COUNTRY_BENCHMARK[c]})" for c in country_options] + BENCHMARKS
    all_options_b = all_options_a.copy()

    def parse_selection(label: str) -> tuple[str, str]:
        if label in BENCHMARKS:
            return label, label
        country = label.rsplit(" (", 1)[0]
        return country, resolve_benchmark(country)

    col_a, col_b = st.columns(2)
    with col_a:
        idx_a = all_options_a.index("카자흐스탄 (Brent)") if "카자흐스탄 (Brent)" in all_options_a else 0
        sel_a = st.selectbox("유종 A (보유/위험 산지)", all_options_a, index=idx_a)
    with col_b:
        idx_b = all_options_b.index("사우디아라비아 (Dubai)") if "사우디아라비아 (Dubai)" in all_options_b else 0
        sel_b = st.selectbox("유종 B (인도/안전 산지)", all_options_b, index=idx_b)

    name_a, bench_a = parse_selection(sel_a)
    name_b, bench_b = parse_selection(sel_b)

    month_options = prices["연월"].dropna().sort_values().unique().tolist()
    selected_month = st.select_slider(
        "기준 월",
        options=month_options,
        value=month_options[-1],
    )
    selected_row = prices.loc[prices["연월"] == selected_month].iloc[-1]

    st.subheader("구조적 신용 할인율 직접 조정")
    st.caption(
        "기본값은 **K-SURE 국가등급**만으로 정해진 구조적 할인이다. "
        "국면에 따른 좌초 할인은 벤치마크 가격에 이미 반영돼 있으므로 여기에 다시 곱하지 않는다(이중계상 방지)."
    )
    grade_a = country_grade(name_a)
    grade_b = country_grade(name_b)
    # v3: 구조적 신용 할인은 K-SURE 등급만으로 정한다.
    # 국면에 따른 좌초 할인은 벤치마크 가격에 이미 들어 있으므로 여기서 다시 곱하지 않는다.
    discount_a_basis = float(credit_discount(name_a))
    discount_b_basis = float(credit_discount(name_b))
    discount_b_default = discount_b_basis
    disc_col_a, disc_col_b = st.columns(2)
    with disc_col_a:
        discount_a = st.slider(
            f"{name_a} 신용 할인율",
            0.0,
            0.30,
            discount_a_basis,
            0.01,
            format="%.2f",
        )
    with disc_col_b:
        discount_b = st.slider(
            f"{name_b} 신용 할인율",
            0.0,
            0.30,
            discount_b_default,
            0.01,
            format="%.2f",
        )

    rate, period = latest_swap_rate(
        prices,
        bench_a,
        bench_b,
        country_a=name_a,
        country_b=name_b,
        geo_discount_a=discount_a,
        geo_discount_b=discount_b,
        month=selected_month,
    )
    series = monthly_swap_series(
        prices,
        bench_a,
        bench_b,
        country_a=name_a,
        country_b=name_b,
        geo_discount_a=discount_a,
        geo_discount_b=discount_b,
    )

    # ── v3: 국면 판정 ──────────────────────────────────────────────────────
    regime = classify_regime(prices, selected_month)
    dd = delivery_discount(prices, selected_month)
    inv_c = inventory_signal(selected_month)

    badge = {
        "transit_shock": "🔴", "producer_shock": "🟠", "aggregate_demand": "🟡",
        "quiet": "🟢", "undetermined": "⚪", "no_data": "⚫",
    }[regime.kind]
    st.markdown(f"#### {badge} 국면 — **{regime.label}** (신뢰도 {regime.confidence})")

    vc1, vc2, vc3 = st.columns(3)
    vc1.metric("스왑비율", f"{rate:.3f}" if rate == rate else "—",
               help="A 1배럴 = B 몇 배럴 (품질·국가등급 반영)")
    vc2.metric("인도위험 초과할인", f"{regime.excess_discount:+.1f}%p",
               help="중동산이 대서양산 대비 받는 초과 할인. 관측치.")
    vc3.metric("지정학 혁신 z",
               "관측없음" if pd.isna(regime.innovation) else f"{regime.innovation:+.2f}")

    if regime.kind == "transit_shock":
        st.error(
            "**수송로 충격** — 봉쇄된 산지의 배럴이 좌초되어 할인 거래되고 있다. "
            "**스왑 유인이 최대인 국면**이나, 싸진 것은 가격이지 접근권이 아니다."
        )
    elif regime.kind == "producer_shock":
        st.warning(
            "**생산자 충격** — 벤치마크가 나란히 움직인다. 물량이 재배치되며 "
            "**산지 간 교환비율이 거의 바뀌지 않으므로 스왑 유인이 낮다.** (Kilian·Park 2009)"
        )
    elif regime.kind == "aggregate_demand":
        st.info("**글로벌 총수요** — 전면적 이동이라 교환비율이 거의 안 바뀐다. 스왑 유인 낮음.")
    elif regime.kind in ("undetermined", "no_data"):
        st.warning("지정학에 귀속할 근거가 없어 지정학 국면으로 판정하지 않았다 (Kilian 2008).")

    if inv_c.get("conflict"):
        st.warning(
            f"⚠ **재고 괴리** — OECD {inv_c['oecd']['mom']:+.2f}% vs 미국 {inv_c['us']['mom']:+.2f}%. "
            "부족이 미국이 아니라 OECD(한국 포함)에 왔다. 「⚡ 국면 판정」 탭 참조."
        )
    with st.expander("판정 근거 보기"):
        for e in regime.evidence:
            st.markdown(f"- {e}")
        for cav in regime.caveats:
            st.caption(f"⚠ {cav}")
    st.divider()
    quality_a = 1.0 if name_a in BENCHMARKS else float(quality_adj(name_a))
    quality_b = 1.0 if name_b in BENCHMARKS else float(quality_adj(name_b))
    effective_a = float(selected_row[bench_a]) * quality_a * (1 - discount_a)
    effective_b = float(selected_row[bench_b]) * quality_b * (1 - discount_b)

    st.markdown("---")
    st.metric(
        label=f"현재 석유 환율 ({period} 기준)",
        value=f"{rate:.4f}",
        help=f"{name_a}({bench_a}) 1배럴 = {name_b}({bench_b}) {rate:.4f}배럴",
    )
    st.markdown(
        f"### {name_a}({bench_a}) 1배럴 = **{name_b}({bench_b}) {rate:.4f}** 배럴"
    )

    col_break_a, col_break_b = st.columns(2)
    with col_break_a:
        st.markdown("#### A 분해")
        st.write(f"P_ref(Dubai) = ${float(selected_row[bench_a]):.2f}")
        st.write(f"품질보정 = {quality_a:.3f}")
        if grade_a is not None:
            st.write(
                f"지정학할인 = {discount_a:.1%} "
                f"(기본 {discount_a_basis:.1%} = K-SURE {grade_a}등급, 시나리오 반영)"
            )
        else:
            st.write(f"지정학할인 = {discount_a:.1%} (벤치마크 직접 선택)")
        st.write(f"유효가격 = ${effective_a:.2f}")
    with col_break_b:
        st.markdown("#### B 분해")
        st.write(f"P_ref(Dubai) = ${float(selected_row[bench_b]):.2f}")
        st.write(f"품질보정 = {quality_b:.3f}")
        if grade_b is not None:
            st.write(
                f"지정학할인 = {discount_b:.1%} "
                f"(기본 {discount_b_basis:.1%} = K-SURE {grade_b}등급, 시나리오 반영)"
            )
        else:
            st.write(f"지정학할인 = {discount_b:.1%} (벤치마크 직접 선택)")
        st.write(f"유효가격 = ${effective_b:.2f}")

    st.caption(
        f"{bench_a} ${float(selected_row[bench_a]):.2f} × {quality_a:.3f} × (1 − {discount_a:.1%}) "
        f"÷ {bench_b} ${float(selected_row[bench_b]):.2f} × {quality_b:.3f} × (1 − {discount_b:.1%}) = {rate:.4f}"
    )

    fig_swap = px.line(
        series,
        x="연월",
        y="swap_rate",
        title=f"{name_a}({bench_a}) → {name_b}({bench_b}) 월별 석유 환율",
        labels={"swap_rate": "스왑 비율", "연월": "연월"},
    )
    fig_swap.add_hline(y=1.0, line_dash="dash", line_color="gray", annotation_text="1:1")
    st.plotly_chart(fig_swap, use_container_width=True)

    with st.expander("지정학 할인율 산출 근거"):
        st.write(
            "할인율은 한국무역보험공사(K-SURE) 국가신용등급(1~7)에 기반합니다. "
            "등급별 할인은 1→0%, 2→2%, 3→4%, 4→6%, 5→9%, 6→14%, 7→22%이며, "
            "계산기 기본값은 양쪽 국가의 K-SURE 등급 기반 할인율을 모두 자동 반영하며, "
            "슬라이더로 시나리오 조정이 가능합니다."
        )

    st.markdown("---")
    st.markdown("#### 🚢 이 스왑으로 절감되는 운송거리/탄소")
    if name_a in COUNTRY_BENCHMARK and name_b in COUNTRY_BENCHMARK:
        esg = esg_swap_metrics(name_a, name_b, 1_000_000)
        st.markdown(
            f"이 스왑은 운송거리 약 **{esg['distance_saved_nm']:,.0f}**해리를 줄여 "
            f"탄소 **{esg['co2_saved_ton']:,.0f}**톤을 절감합니다 (100만 배럴 기준) → "
            "자세히는 **'🌱 ESG 절감'** 탭"
        )
    else:
        st.caption("벤치마크 직접 선택 시 항로 ESG 절감은 국가 단위로 'ESG 절감' 탭에서 확인하세요.")

    volume_bbl = 1_000_000
    if name_a in COUNTRY_BENCHMARK and name_b in COUNTRY_BENCHMARK:
        esg_brief = esg_swap_metrics(name_a, name_b, volume_bbl)
        co2_saved = esg_brief["co2_saved_ton"]
        freight_saved = esg_brief["freight_saved_usd"]
    else:
        co2_saved = 0.0
        freight_saved = 0.0

    api_a, sulfur_a = country_quality_specs(name_a)
    api_a = api_a if api_a is not None else 0.0
    sulfur_a = sulfur_a if sulfur_a is not None else 0.0
    grade_a_val = grade_a if grade_a is not None else 0
    gpr_stress_a = country_gpr_innovation(name_a, selected_month)
    if gpr_stress_a != gpr_stress_a:  # NaN
        gpr_stress_a = 0.0

    st.divider()
    st.subheader("🤖 AI 지정학 브리핑")
    st.caption(
        "Gemini가 공공데이터 지표를 해석해 스왑 추천을 생성합니다. "
        "국면 판정 결과를 먼저 읽고 국면별 규칙에 따라 실행/관망을 판단합니다."
    )
    if st.button("브리핑 생성"):
        with st.spinner("AI가 지정학 리스크를 분석 중…"):
            text = generate_briefing(
                name_a,
                name_b,
                selected_month,
                grade_a_val,
                api_a,
                sulfur_a,
                gpr_stress_a,
                discount_a,
                rate,
                volume_bbl,
                co2_saved,
                freight_saved,
                shock_label=regime.label,
                shock_confidence=regime.confidence,
                shock_innovation=None if pd.isna(regime.innovation) else float(regime.innovation),
                dispersion_z=float(regime.excess_discount),
                scarcity_prem_b=0.0,
                inventory_dir=regime.inventory_dir,
                inventory_mom=None if pd.isna(regime.inventory_mom) else float(regime.inventory_mom),
                inventory_source=inv_c.get("source", "-"),
                inventory_conflict=bool(inv_c.get("conflict")),
                inv_oecd=(inv_c.get("oecd") or {}).get("mom"),
                inv_us=(inv_c.get("us") or {}).get("mom"),
                band_low=None,
                band_high=None,
            )
        if text is None:
            st.info(
                "AI 브리핑을 쓰려면 Streamlit Secrets에 GEMINI_API_KEY를 설정하세요. "
                "(설정 전에도 나머지 기능은 정상)"
            )
        else:
            st.markdown(text)


def tab_geopolitical_risk(countries):
    st.header("지정학 리스크")
    st.success("K-SURE 국가위험도 연동 완료")

    risk = ksure_country_risk(countries)
    risk_graph = risk.dropna(subset=["K-SURE_국가등급"]).sort_values(
        ["K-SURE_국가등급", "국가"], ascending=[True, True]
    )
    fig_ksure = px.bar(
        risk_graph,
        x="K-SURE_국가등급",
        y="국가",
        color="K-SURE_국가등급",
        orientation="h",
        text="K-SURE_국가등급",
        title="국가별 K-SURE 국가등급 (수입국 기준)",
        labels={"K-SURE_국가등급": "국가등급", "국가": ""},
        color_continuous_scale=["#2e7d32", "#f9a825", "#c62828"],
        range_color=[1, 7],
    )
    fig_ksure.update_yaxes(
        categoryorder="array",
        categoryarray=risk_graph["국가"].tolist(),
    )
    fig_ksure.update_xaxes(dtick=1, tickformat="d", range=[0, 7.4])
    fig_ksure.update_layout(height=max(520, len(risk_graph) * 24), coloraxis_showscale=False)
    st.plotly_chart(fig_ksure, use_container_width=True)

    st.subheader("등급→할인율 매핑")
    mapping_rows = [
        {"K-SURE 국가등급": grade, "지정학 할인율": f"{discount:.0%}"}
        for grade, discount in GRADE_TO_DISCOUNT.items()
    ]
    st.dataframe(mapping_rows, use_container_width=True)

    st.subheader("원유광업 업종 위험지수 참고")
    st.caption("K-SURE는 원유광업 업종 특화 위험지수도 제공 — 향후 업종 특화 모델로 확장 가능")
    st.dataframe(load_oil_mining_risk(), use_container_width=True)


def tab_shock_regime(prices):
    st.header("⚡ 충격 유형 판정")
    st.markdown(
        "**\u201c유가가 얼마나 올랐나\u201d는 정보가 아니다. \u201c왜 올랐나\u201d가 정보다.** "
        "같은 크기의 상승이라도 원인이 다르면 산지 간 교환비율에 미치는 영향이 정반대가 된다"
        "(Kilian & Park 2009). 이 탭은 매월의 국면을 관측 가능한 신호만으로 분류한다."
    )

    cov_lo, cov_hi = gpr_coverage()
    month_options = prices["연월"].dropna().sort_values().unique().tolist()
    default_idx = month_options.index("2026-03") if "2026-03" in month_options else len(month_options) - 1
    month = st.select_slider("판정 기준 월", options=month_options, value=month_options[default_idx])

    r = classify_regime(prices, month)
    dd = delivery_discount(prices, month)
    inv = inventory_signal(month)

    tone = {
        "transit_shock": ("🔴", "error"),
        "producer_shock": ("🟠", "warning"),
        "aggregate_demand": ("🟡", "warning"),
        "quiet": ("🟢", "success"),
        "undetermined": ("⚪", "info"),
        "no_data": ("⚫", "info"),
    }[r.kind]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("국면", f"{tone[0]} {r.label}")
    c2.metric("신뢰도", r.confidence)
    c3.metric(
        "인도위험 초과할인",
        f"{r.excess_discount:+.1f}%p",
        help="중동산(Dubai)이 대서양산(Brent) 대비 받는 할인율에서 평시 중위값을 뺀 값. 관측치이며 추정치가 아니다.",
    )
    c4.metric(
        "지정학 혁신 z",
        "관측없음" if pd.isna(r.innovation) else f"{r.innovation:+.2f}",
        help="log(1+GPR)의 AR(5) 잔차. 수준이 아니라 '예상 밖의 정도'를 잰다.",
    )
    c5.metric(
        "재고 방향",
        inv["dir"] if inv["available"] else "관측없음",
        f"{inv['mom']:+.1f}% MoM" if inv["available"] else None,
        help="주 지표는 OECD 상업재고. 미국은 보조.",
    )

    getattr(st, tone[1])(f"**{r.label}** — 신뢰도 {r.confidence}")

    st.subheader("판정 근거")
    for e in r.evidence:
        st.markdown(f"- {e}")
    for cav in r.caveats:
        st.warning(cav)

    if inv.get("conflict"):
        o, u = inv["oecd"], inv["us"]
        st.error(
            f"**재고 괴리** — OECD **{o['mom']:+.2f}%** vs 미국 **{u['mom']:+.2f}%**. "
            "부족이 미국에는 오지 않고 OECD에 왔다는 뜻입니다. 미국은 순수출국이라 중동 초크포인트에 "
            "절연돼 있고, **한국은 OECD이며 호르무즈 노출이 큽니다.**"
        )

    st.divider()
    st.subheader("두 지정학 충격은 같지 않다 — 수송로냐 생산자냐")
    st.markdown(
        "같은 「지정학 리스크」라도 **수송로를 막느냐 생산자를 막느냐**에 따라 "
        "벤치마크 반응이 정반대다. 이 구분이 스왑 유인의 유무를 정한다."
    )
    st.dataframe(
        pd.DataFrame([
            {"국면": "수송로 충격", "사례": "2026 호르무즈 봉쇄",
             "벤치마크": "**갈라진다** — 봉쇄된 산지가 좌초되어 할인",
             "스왑 유인": "**최대**"},
            {"국면": "생산자 충격", "사례": "2022 러시아 제재",
             "벤치마크": "**나란히 간다** — 물량이 재배치되며 함께 상승",
             "스왑 유인": "낮음"},
        ]),
        hide_index=True, use_container_width=True,
    )
    st.caption(
        f"판정 임계값 — 인도위험 초과할인 {SPREAD_SHOCK_PP:.0f}%p 이상 + 지정학 혁신 1.5σ 이상. "
        "적합 파라미터는 없다. 크기는 추정하지 않고 **관측된 스프레드에서 직접 측정**한다."
    )

    st.divider()
    st.subheader("국면 시계열 — 언제 갈라졌나")
    series = monthly_regime_series(prices, "카자흐스탄", "사우디아라비아")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=series["연월"], y=series["스왑비율"], name="스왑비율 (카자흐→사우디)",
                   mode="lines", line=dict(color="#0F766E", width=3)),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=series["연월"], y=series["인도위험 초과할인(%p)"],
               name="인도위험 초과할인(%p)", marker_color="#C62828", opacity=0.4),
        secondary_y=True,
    )
    fig.add_hline(y=1.0, line_dash="dot", line_color="#94A3B8", secondary_y=False)
    fig.update_yaxes(title_text="스왑비율", secondary_y=False)
    fig.update_yaxes(title_text="초과할인(%p)", secondary_y=True)
    fig.update_layout(height=430, margin=dict(t=30, b=10), legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("월별 판정 이력")
    st.dataframe(series.tail(24), hide_index=True, use_container_width=True)

    st.caption(f"지정학지수 소스 — **{gpr_source()}**  ·  보유 구간 {cov_lo} ~ {cov_hi}")
    st.info(
        "**이 엔진에는 적합(fitted) 파라미터가 없습니다.** 지정학지수는 국면을 **분류**하는 데만 쓰고, "
        "할인의 크기는 **관측된 벤치마크 스프레드에서 직접 측정**합니다. "
        "지정학 뉴스로 가격을 예측하면 과대추정이 된다는 문헌(Kilian 2008)을 설계로 옮긴 것입니다."
    )



def tab_chokepoints(countries):
    st.header("🚢 초크포인트 노출")
    st.markdown(
        "가격 신호는 **호르무즈 하나만** 잡는다. 나머지 관문에는 공개 가격 계열이 없다. "
        "그래서 가격이 없는 곳은 **노출 구조**로 잡는다 — "
        "*막히면 얼마가 묶이나*. 추정이 아니라 **도입 실적에 경로를 대입한 산술**이다."
    )

    years = sorted(countries["연도"].unique())
    year = st.select_slider("기준 연도", options=years, value=max(years))

    st.subheader("우회 능력 가정 (조정 가능)")
    st.caption(
        "각국 총수출 대비 '호르무즈를 피해 내보낼 수 있는 비율'. "
        "**추정된 계수가 아니라 명시적 가정**이므로 직접 바꿔볼 수 있게 열어 둔다."
    )
    cols = st.columns(3)
    byp = dict(BYPASS_SHARE)
    for i, k in enumerate(["사우디아라비아", "아랍에미리트", "이라크"]):
        with cols[i]:
            byp[k] = st.slider(f"{k} 우회비율", 0.0, 1.0, float(BYPASS_SHARE[k]), 0.05)

    e = exposure(countries, year, bypass=byp)
    worst = e.loc[e["순노출비중"].idxmax()]

    m1, m2, m3 = st.columns(3)
    m1.metric("최대 노출 관문", worst["관문"], f"순노출 {worst['순노출비중']:.1f}%")
    hz = e[e["관문"] == "호르무즈 해협"].iloc[0]
    m2.metric("호르무즈 순노출", f"{hz['순노출비중']:.1f}%", f"통과 {hz['통과비중']:.1f}%")
    m3.metric("가격 신호 보유 관문", f"1 / {len(CHOKEPOINTS)}", "나머지는 노출로 측정")

    if worst["관문"] != "호르무즈 해협":
        st.error(
            f"**한국의 최대 관문은 호르무즈가 아니라 「{worst['관문']}」이다.** "
            f"순노출 **{worst['순노출비중']:.1f}%** (호르무즈 {hz['순노출비중']:.1f}%). "
            "호르무즈는 파이프라인 우회로가 있지만, 이 관문에는 **파이프라인 대체가 아예 없다** — "
            "더 긴 해상 항로뿐이다."
        )

    st.dataframe(e, hide_index=True, use_container_width=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=e["관문"], y=e["우회가능_천배럴"], name="우회 가능", marker_color="#94A3B8"))
    fig.add_trace(go.Bar(x=e["관문"], y=e["순노출_천배럴"], name="순노출", marker_color="#C62828"))
    fig.update_layout(barmode="stack", height=380, margin=dict(t=30, b=10),
                      yaxis_title="천 배럴", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("우회로는 공짜가 아니다 — 직렬 의존")
    st.markdown(
        "호르무즈를 피하는 사우디 East-West 파이프라인은 **얀부(홍해)로 나온다.** "
        "그리고 얀부에서 동아시아로 가려면 **바브엘만데브를 지나야 한다.** "
        "우회로가 또 다른 관문으로 들어가는 것을 직렬 의존이라 한다."
    )
    st.dataframe(serial_dependency(countries, year), hide_index=True, use_container_width=True)
    st.warning(
        "**따라서 「호르무즈 우회 가능 물량」을 안전물량으로 세면 안 된다.** "
        "사우디 우회분은 바브엘만데브로 나오고, 그 뒤에도 **말라카가 남아 있다.**"
    )

    st.divider()
    st.subheader("관문이 막혔을 때 남는 것 — 대체 산지")
    key = st.selectbox(
        "관문 선택",
        [c.key for c in CHOKEPOINTS],
        format_func=lambda k: next(c.name for c in CHOKEPOINTS if c.key == k),
    )
    a = alternatives(countries, year, key)
    cp = a["관문"]
    st.info(f"**{cp.name}** ({cp.eng}) — {cp.note}")
    st.caption(f"우회 경로: {cp.bypass_note or '없음'}  ·  가격 신호: {cp.price_signal or '없음 (노출로 측정)'}")

    a1, a2, a3 = st.columns(3)
    a1.metric("영향 없는 물량", f"{a['안전물량_천배럴']:,} 천배럴", f"{a['안전비중']}%")
    a2.metric("대체 산지 HHI", f"{a['대체산지_HHI']:,}",
              help="1,500 미만 분산 · 2,500 초과 고집중. 대체처가 한 곳에 쏠려 있으면 그것도 리스크다.")
    a3.metric("최대 대체 산지", a["상위_대체산지"][0][0] if a["상위_대체산지"] else "—",
              f"{a['상위_대체산지'][0][1]:,.0f} 천배럴" if a["상위_대체산지"] else None)

    if a["대체산지_HHI"] >= 2500:
        st.warning(
            f"**대체 산지도 집중돼 있다 (HHI {a['대체산지_HHI']:,}).** "
            "관문이 막혔을 때 기댈 곳이 몇 군데뿐이라는 뜻이며, "
            "그 자체가 2차 리스크다."
        )
    st.dataframe(
        pd.DataFrame(a["상위_대체산지"], columns=["산지", "물량_천배럴"]),
        hide_index=True, use_container_width=True,
    )

    st.divider()
    st.subheader("탄소와 관문은 같은 방향이 아니다")
    st.markdown(
        "「🌱 ESG 절감」 탭은 항로가 짧을수록 좋다고 말한다. "
        "그런데 **가장 가까운 산지가 관문이 가장 많다.**"
    )
    st.dataframe(esg_risk_tradeoff(countries, year), hide_index=True, use_container_width=True)
    st.error(
        "**중동 6,400nm — 관문 2개(호르무즈·말라카).  미국 9,500nm — 관문 0개.**  "
        "탄소를 최소화하는 조달 구조가 관문 리스크를 최대화한다. "
        "**두 탭의 최적해가 반대**라는 사실을 숨기지 않는다 — "
        "조달 의사결정은 이 상충 위에서 내려야 한다."
    )

    st.divider()
    st.subheader("카자흐 원유가 한국에 닿기까지 — 관문 사슬")
    st.markdown(" → ".join(f"**{x}**" for x in KAZAKH_CHAIN))
    st.error(
        "**관문 넷과 타국 영토 하나를 지나야 실물이 온다.** CPC 파이프라인은 러시아 영토를 통과하고, "
        "흑해로 나온 뒤 터키 해협·수에즈·바브엘만데브·말라카를 차례로 거친다." + chr(10) + chr(10) +
        "**이것이 Geo-Swap이 존재하는 이유다.** 물리적 인도가 관문의 곱으로 어려워질수록, "
        "「기름을 옮기지 않고 인도처를 맞바꾸는」 금융적 해법의 가치가 커진다. "
        "카자흐 권리를 확보하되 실물은 걸프에서 받는 것 — 그것이 스왑이다."
    )

    st.caption(
        "출처: 통과 산지·우회 경로는 지리적 사실, 물량은 한국석유공사 국가별 원유수입(KOSIS). "
        "우회 비율은 파이프라인 공칭 용량 대비 수출량으로 잡은 **명시적 가정**이며 위 슬라이더에서 조정 가능하다."
    )



def tab_trade_finance_screening(countries):
    st.header("🛡️ 무역금융 제재 스크리닝")
    st.markdown(
        "**대상 금융소비자** — 원유 **직도입**은 국내 정유 4사와 한국석유공사만 수행한다. "
        "그 아래에서 **나프타·벙커C유·아스팔트·윤활기유·석유코크스** 등 파생 원자재를 "
        "**수입신용장**(L/C)으로 들여오는 **중견·중소 법인 금융소비자**가 이 화면의 사용자다."
    )
    st.markdown(
        "**왜 필요한가** — 이들은 자체 컴플라이언스 조직이 얇다. 거래 상대가 붙여 준 선박이 "
        "**OFAC 제재 대상**(그림자 선단)인지 모른 채 L/C를 개설하고, 사후에 계좌 동결과 "
        "**2차 제재**(secondary sanctions)에 걸린다. **은행도 함께 걸린다.** "
        "→ **L/C 개설 시점의 대조**가 가장 값싼 방어다."
    )

    cov = sdn_coverage()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("OFAC 제재 선박", f"{cov['total']:,}척")
    k2.metric("유조선류", f"{cov['tankers']:,}척")
    k3.metric("IMO 보유", f"{cov['with_imo']:,}척", f"{cov['with_imo']/max(cov['total'],1):.0%}")
    k4.metric("목록 기준일", cov["date"])

    st.divider()
    st.subheader("① L/C 개설 전 3단 스크리닝")

    c1, c2 = st.columns([1, 1])
    with c1:
        origins = ["사우디아라비아", "아랍에미리트", "쿠웨이트", "이라크", "카타르", "미국",
                   "카자흐스탄", "러시아", "이란", "베네수엘라", "알제리", "나이지리아"]
        origin = st.selectbox("수입 화물 산지", origins, index=0)
    with c2:
        vessel = st.text_input("선박명 또는 IMO 번호", value="ARTAVIL",
                               help="그림자 선단은 선박명을 자주 바꾼다. IMO 번호가 더 신뢰할 수 있다.")

    note = origin_sanctions_note(origin)
    st.markdown("**1단 — 산지 제재 축 대조**")
    (st.error if note["sanctioned"] else st.success)(note["note"])

    st.markdown("**2단 — 선박 대조 (OFAC SDN)**")
    res = screen_vessel(vessel)
    if res["status"] == "제재대상":
        st.error(
            f"🚨 **제재 대상 선박입니다 — L/C 개설을 중단하고 준법감시부에 회부해야 합니다.** "
            f"({res['match_by']} 일치)"
        )
        st.dataframe(res["exact"], hide_index=True, use_container_width=True)
    elif res["status"] == "유사 일치 — 확인 필요":
        st.warning(
            "⚠ **정확 일치는 없으나 유사한 이름의 제재 선박이 있습니다.** "
            "그림자 선단은 선박명을 자주 바꾸므로, **IMO 번호로 재확인**해야 합니다."
        )
        st.dataframe(res["similar"], hide_index=True, use_container_width=True)
    elif res["status"] == "해당없음":
        st.success("✅ 현 스냅샷 기준 제재 목록에 없습니다.")
        st.caption(
            "⚠ 다만 **SDN 목록은 수시로 갱신**됩니다. 실제 운영에서는 거래 시점의 최신 목록을 조회해야 하며, "
            "본 MVP는 저장소 동봉 스냅샷으로 동작합니다."
        )
    else:
        st.info("선박명 또는 IMO를 입력하세요.")

    st.markdown("**3단 — 선적국 편의치적 점검**")
    st.caption(
        "그림자 선단은 실소유를 감추려 **편의치적**(flag of convenience)을 쓴다. "
        "제재 유조선의 선적국 분포가 그 서명을 그대로 보여준다."
    )
    st.dataframe(flag_risk_profile(), hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("② 제재 프로그램별 노출 — 원유 거래에 걸리는 축")
    st.dataframe(program_summary(), hide_index=True, use_container_width=True)
    st.info(
        "**이란 474척 · 러시아 213척(우크라이나 병기 157척 별도) · 베네수엘라 26척.** "
        "원유·석유제품 거래에서 실제로 문제가 되는 제재 축이 여기에 집중돼 있다."
    )

    st.divider()
    st.subheader("③ 왜 중견·중소 법인이 먼저 무너지는가")
    st.markdown(
        "Gertler & Hubbard(1988)는 **작은 기업의 매출 변동이 큰 것이 기술 선택이 아니라 "
        "금융 조달 마찰 때문**일 수 있음을 보였다. 결정적 근거는 — 기술 선택 모형은 매출 변동성은 "
        "설명해도 **매출과 투자 변동성이 같은 집단에서 함께 커지는 것**은 설명하지 못한다는 점이다."
    )
    st.warning(
        "**함의** — 지정학 충격으로 원자재 단가가 튀면, 외부 조달 마찰이 큰 중견·중소 수입 법인이 "
        "**가장 먼저 유동성 위기**를 겪는다. 대형 정유사는 자체 트레이딩 데스크와 파생 헤지 조직이 있지만 "
        "이들에게는 **헤지 수단 자체가 없다.** 은행의 선제적 리스크 관리가 필요한 이유다."
    )
    st.caption(
        "※ 해당 문헌은 서술 층위까지만 인용한다 — 원문이 열화 스캔본이라 표의 배수·수치는 인용하지 않는다."
    )

    st.caption(
        f"출처: 미국 재무부 OFAC SDN 목록 (공개 다운로드, API 키 불필요) · 기준일 {SNAPSHOT_DATE}  ·  {SDN_URL}"
    )


def main():
    st.set_page_config(
        page_title="Geo-Swap",
        page_icon="🛢️",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        .block-container { padding-top: 2.6rem; max-width: 1320px; }
        [data-testid="stMetric"] {
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 14px 18px;
        }
        [data-testid="stMetricLabel"] p { font-size: 0.85rem; opacity: 0.62; }
        h1 { letter-spacing: -0.5px; font-weight: 800; }
        h2, h3 { letter-spacing: -0.3px; }
        [data-testid="stTabs"] button[data-baseweb="tab"] { font-weight: 600; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_hero()

    data = get_data()
    countries = data["countries"]
    grades = data["grades"]
    grades_monthly = data["grades_monthly"]
    prices = data["prices"]
    gpr_region_monthly = data["gpr_region_monthly"]
    oil_quality = data["oil_quality"]
    ksure_grades = data["ksure_grades"]

    eu_ets = data["eu_ets"]

    st.caption(
        f"🟢 데이터 최신성 — 국제유가 {prices['연월'].max()} · "
        f"지정학지수 {gpr_coverage()[1]} · "
        f"원유재고 {inventory_coverage()} · "
        f"K-SURE 국가등급 2026-02 · 원유 수입 {int(countries['연도'].max())}(연간 확정통계)"
    )

    tab1, tab2, tab3, tab4, tab9, tab10, tab11, tab5, tab6, tab7, tab8 = st.tabs(
        [
            "📊 원유 수입 구조",
            "🛢️ 유질 구성",
            "💵 국제유가 & 스프레드",
            "⭐ 석유 환율 계산기",
            "⚡ 국면 판정",
            "🚢 초크포인트 노출",
            "🛡️ 무역금융 제재 스크리닝",
            "🔍 심층분석",
            "🌱 ESG 절감",
            "📈 시장규모·임팩트",
            "🌍 지정학 리스크",
        ]
    )

    with tab1:
        tab_import_structure(countries)
    with tab2:
        tab_grade_composition(grades, grades_monthly)
    with tab3:
        tab_oil_prices(prices)
    with tab4:
        tab_swap_calculator(prices)
    with tab9:
        tab_shock_regime(prices)
    with tab10:
        tab_chokepoints(countries)
    with tab11:
        tab_trade_finance_screening(countries)
    with tab5:
        tab_deep_analysis(countries, gpr_region_monthly, oil_quality, ksure_grades)
    with tab6:
        tab_esg_savings(eu_ets)
    with tab7:
        tab_market_impact(countries, eu_ets, prices)
    with tab8:
        tab_geopolitical_risk(countries)

    st.divider()
    footer()


if __name__ == "__main__":
    main()

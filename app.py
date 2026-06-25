"""Geo-Swap — Petroleum Swap Rate Dashboard."""

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import base64
from pathlib import Path

from src.loaders import load_all
from src.ai_brief import generate_briefing
from src.engine import (
    BENCHMARKS,
    COUNTRY_BENCHMARK,
    EUR_KRW,
    ETS_EUR,
    FREIGHT_PER_BBL_NM,
    GRADE_TO_DISCOUNT,
    HIGH_RISK_COUNTRIES,
    STRUCTURING_FEE_RATE,
    country_grade,
    country_gpr_stress,
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

DATA_SOURCE_FOOTER = (
    "데이터: 산업통상부 — 한국석유공사(국가별·유질별 원유수입·국제유가) · "
    "한국무역보험공사(국가신용등급) · 한국가스공사(EU ETS 탄소가격) | "
    "연계: EIA(원유품질 API·황), GPR 지정학지수 | "
    "운송거리(sea-distances 근사)·탄소계수(IMO) 기반 ESG 추정 | "
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
    """전체 배경 사진(어둡게) + 흰 반투명 콘텐츠 패널로 가독성 확보."""
    img = Path(__file__).resolve().parent / "assets" / "hero.jpg"
    if img.exists():
        b64 = base64.b64encode(img.read_bytes()).decode()
        bg = (
            "linear-gradient(rgba(15,23,42,0.72), rgba(15,23,42,0.88)), "
            f"url('data:image/jpeg;base64,{b64}')"
        )
        st.markdown(
            f"""
            <style>
            .stApp {{
                background-image: {bg};
                background-size: cover;
                background-position: center;
                background-attachment: fixed;
            }}
            .block-container {{
                background: rgba(255,255,255,0.96);
                border-radius: 18px;
                padding: 2.2rem 2.6rem 2.2rem 2.6rem !important;
                box-shadow: 0 12px 48px rgba(0,0,0,0.30);
                margin-top: 1.4rem;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    st.title("🛢️ Geo-Swap")
    st.markdown(
        "위험 산지 원유 **권리**를 안전 산지 원유와 교환(스왑)할 때의 "
        "**석유 환율(Petroleum Swap Rate)** 플랫폼"
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
    gpr_df = gpr_region_monthly[["Date", "GPR_OIL_Russia"]].copy()
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
            name="GPR_OIL_Russia (월별)",
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
        title_text="GPR_OIL_Russia",
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
            f"- **탄소가격**: 한국가스공사 제공 EU ETS €{ets_eur:.2f}/톤 × ₩{EUR_KRW:,}/€"
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

    impact = market_impact(
        countries,
        year=int(year),
        fee_rate=fee_rate,
        ets_eur=ets_eur,
        eur_krw=EUR_KRW,
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
    st.subheader("✅ 모델 검증 — 공공데이터 대조")
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
        f"본 모델이 산출한 수입량 가중평균 도입가가 페트로넷 실제 **FOB와 {abs(v['fob_err_pct']):.1f}% 이내로 일치** "
        f"→ 공공데이터로 모델 타당성 검증. CIF와의 차이(약 {abs(v['cif_err_pct']):.1f}%)는 **운임 성분**으로, "
        f"이는 ESG 탭의 운임 절감 모델과 정합한다. "
        f"(기준: {v['period']}, 도입가는 운임 미포함 spot 기준)"
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

    st.subheader("지정학 할인율 직접 조정")
    grade_a = country_grade(name_a)
    grade_b = country_grade(name_b)
    discount_a_basis = float(geo_discount(name_a, selected_month))
    discount_b_basis = float(geo_discount(name_b, selected_month))
    discount_b_default = discount_b_basis
    disc_col_a, disc_col_b = st.columns(2)
    with disc_col_a:
        discount_a = st.slider(
            f"{name_a} 할인율",
            0.0,
            0.30,
            discount_a_basis,
            0.01,
            format="%.2f",
        )
    with disc_col_b:
        discount_b = st.slider(
            f"{name_b} 할인율",
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
    gpr_stress_a = country_gpr_stress(name_a, selected_month)

    st.divider()
    st.subheader("🤖 AI 지정학 브리핑")
    st.caption(
        "Gemini가 공공데이터 지표를 해석해 스왑 추천을 생성합니다. "
        "지정학지수는 LLM 생성 데이터(AI-GPR) 기반."
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
        f"지정학(AI-GPR) {gpr_region_monthly['연월'].max()} · "
        f"K-SURE 국가등급 2026-02 · 원유 수입 {int(countries['연도'].max())}(연간 확정통계)"
    )

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
        [
            "📊 원유 수입 구조",
            "🛢️ 유질 구성",
            "💵 국제유가 & 스프레드",
            "⭐ 석유 환율 계산기",
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

"""Hana Geo-Swap — Petroleum Swap Rate Dashboard."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.loaders import load_all
from src.engine import (
    BENCHMARKS,
    COUNTRY_BENCHMARK,
    GRADE_TO_DISCOUNT,
    HIGH_RISK_COUNTRIES,
    country_grade,
    country_year_totals,
    geo_discount,
    hhi_by_year,
    high_risk_share_by_year,
    ksure_country_risk,
    latest_swap_rate,
    load_oil_mining_risk,
    middle_east_share_by_year,
    monthly_swap_series,
    resolve_benchmark,
)

DATA_SOURCE_FOOTER = (
    "데이터 출처 · 한국석유공사[KOSIS TX_31801_A008] · 국제유가[페트로넷] · "
    "한국무역보험공사 국가신용등급·원유광업 위험지수(지정학 할인 근거)"
)

GRADE_LABELS = {"light": "경질유", "medium": "중(中)질유", "heavy": "중(重)질유"}


@st.cache_data
def get_data():
    return load_all()


def footer():
    st.caption(DATA_SOURCE_FOOTER)


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

    st.subheader("지정학 할인율 직접 조정")
    grade_a = country_grade(name_a)
    grade_b = country_grade(name_b)
    discount_a_default = float(geo_discount(name_a))
    discount_b_basis = float(geo_discount(name_b))
    discount_b_default = discount_b_basis
    disc_col_a, disc_col_b = st.columns(2)
    with disc_col_a:
        discount_a = st.slider(
            f"{name_a} 할인율",
            0.0,
            0.30,
            discount_a_default,
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
    latest_prices = prices.iloc[-1]

    st.markdown("---")
    st.metric(
        label=f"현재 석유 환율 ({period} 기준)",
        value=f"{rate:.4f}",
        help=f"{name_a}({bench_a}) 1배럴 = {name_b}({bench_b}) {rate:.4f}배럴",
    )
    st.markdown(
        f"### {name_a}({bench_a}) 1배럴 = **{name_b}({bench_b}) {rate:.4f}** 배럴"
    )
    grade_a_text = (
        f"{name_a}: K-SURE 국가등급 {grade_a} → 기준 할인 {geo_discount(name_a):.0%}, 적용 할인 {discount_a:.0%}"
        if grade_a is not None
        else f"{name_a}: K-SURE 등급 없음/벤치마크 직접 선택 → 지정학 할인 {discount_a:.0%}"
    )
    grade_b_text = (
        f"{name_b}: K-SURE 국가등급 {grade_b} → 기준 할인 {discount_b_basis:.0%}, 적용 할인 {discount_b:.0%}"
        if grade_b is not None
        else f"{name_b}: K-SURE 등급 없음/벤치마크 직접 선택 → 지정학 할인 {discount_b:.0%}"
    )
    st.caption(
        f"{grade_a_text} · {grade_b_text}\n\n"
        f"{bench_a} ${latest_prices[bench_a]:.1f} × (1 − {discount_a:.0%}) "
        f"÷ {bench_b} ${latest_prices[bench_b]:.1f} × (1 − {discount_b:.0%}) = {rate:.2f}"
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
    st.caption("TODO(v2): 항로 거리·탄소 배출량 데이터 연동 예정")


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
        page_title="Hana Geo-Swap",
        page_icon="🛢️",
        layout="wide",
    )
    st.title("🛢️ Hana Geo-Swap")
    st.markdown(
        "위험 산지 원유 **권리**를 안전 산지 원유와 교환(스왑)할 때의 "
        "**석유 환율(Petroleum Swap Rate)** 대시보드"
    )

    data = get_data()
    countries = data["countries"]
    grades = data["grades"]
    grades_monthly = data["grades_monthly"]
    prices = data["prices"]

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "📊 원유 수입 구조",
            "🛢️ 유질 구성",
            "💵 국제유가 & 스프레드",
            "⭐ 석유 환율 계산기",
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
        tab_geopolitical_risk(countries)

    st.divider()
    footer()


if __name__ == "__main__":
    main()

"""Petroleum Swap Rate engine and import-structure metrics."""

from __future__ import annotations

import pandas as pd

BENCHMARKS = ["Dubai", "Brent", "WTI", "Oman"]

# Country → benchmark proxy for pricing (editable dict)
COUNTRY_BENCHMARK: dict[str, str] = {
    # Americas → WTI
    "미국": "WTI",
    "캐나다": "WTI",
    "멕시코": "WTI",
    "브라질": "WTI",
    "에콰도르": "WTI",
    "콜롬비아": "WTI",
    # Middle East → Dubai/Oman
    "사우디아라비아": "Dubai",
    "아랍에미리트": "Dubai",
    "쿠웨이트": "Dubai",
    "이라크": "Dubai",
    "카타르": "Dubai",
    "오만": "Oman",
    "중립지대": "Dubai",
    # Europe / Africa / CIS → Brent
    "노르웨이": "Brent",
    "영국": "Brent",
    "알제리": "Brent",
    "카메룬": "Brent",
    "콩고": "Brent",
    "가봉": "Brent",
    "나이지리아": "Brent",
    "적도기니": "Brent",
    "모잠비크": "Brent",
    "러시아": "Brent",
    "카자흐스탄": "Brent",
    # Asia-Pacific (non-Middle East)
    "필리핀": "Dubai",
    "태국": "Dubai",
    "말레이시아": "Dubai",
    "인도네시아": "Dubai",
    "브루나이": "Dubai",
    "호주": "Brent",
    "뉴질랜드": "Brent",
    "베트남": "Dubai",
    "파푸아뉴기니": "Brent",
}

HIGH_RISK_COUNTRIES = ["러시아", "카자흐스탄"]
MIDDLE_EAST_CONTINENT = "중동"

# 벤치마크 대비 할인율(양수 = 그만큼 싸게 거래됨).
# 실제 원유 Basis(CPC Blend, Urals, Merey 등)의 통상 수준을 반영한 조정 가능한 가정값.
# TODO(v2): 한국무역보험공사(K-SURE) 국가위험도 / Argus·Platts 실측 Basis로 대체 예정.
GEO_DISCOUNT: dict[str, float] = {
    "카자흐스탄": 0.07,
    "러시아": 0.25,
    "베네수엘라": 0.25,
    "나이지리아": 0.02,
    "앙골라": 0.02,
    "콩고": 0.03,
    "가봉": 0.02,
}
GEO_DISCOUNT.update({b: 0.0 for b in BENCHMARKS})

# TODO(v2): route distance hardcoding → freightFactor
FREIGHT_FACTOR: dict[str, float] = {
    "카자흐스탄→한국": 1.0,
    "중동→한국": 1.0,
    "default": 1.0,
}


def swap_rate(price_a: float, price_b: float) -> float:
    """A 1 barrel = B how many barrels (value basis)."""
    if price_b == 0:
        return float("nan")
    return price_a / price_b


def effective_price(country: str, benchmark_price: float, geo_discount: float | None = None) -> float:
    """Country crude effective price = benchmark price x (1 - geopolitical discount)."""
    discount = GEO_DISCOUNT.get(country, 0.0) if geo_discount is None else geo_discount
    return benchmark_price * (1 - discount)


def country_swap_rate(
    country_a: str,
    bench_price_a: float,
    country_b: str,
    bench_price_b: float,
    geo_discount_a: float | None = None,
    geo_discount_b: float | None = None,
) -> float:
    """A 1 barrel = B how many barrels, including country-level geopolitical discounts."""
    price_a = effective_price(country_a, bench_price_a, geo_discount_a)
    price_b = effective_price(country_b, bench_price_b, geo_discount_b)
    return swap_rate(price_a, price_b)


def adjusted_swap_rate(
    price_a: float,
    price_b: float,
    geo_discount_a: float = 0.0,
    geo_discount_b: float = 0.0,
    grade_adj: float = 1.0,
    freight_factor: float = 1.0,
) -> float:
    """v2-adjusted swap rate using discounted effective prices."""
    base = swap_rate(price_a * (1 - geo_discount_a), price_b * (1 - geo_discount_b))
    return base * grade_adj * freight_factor


def monthly_swap_series(
    prices: pd.DataFrame,
    bench_a: str,
    bench_b: str,
    country_a: str | None = None,
    country_b: str | None = None,
    geo_discount_a: float | None = None,
    geo_discount_b: float | None = None,
) -> pd.DataFrame:
    """Monthly swap rate A→B time series."""
    out = prices[["연월", "연도", "월"]].copy()
    name_a = country_a or bench_a
    name_b = country_b or bench_b
    discount_a = GEO_DISCOUNT.get(name_a, 0.0) if geo_discount_a is None else geo_discount_a
    discount_b = GEO_DISCOUNT.get(name_b, 0.0) if geo_discount_b is None else geo_discount_b
    out["swap_rate"] = (prices[bench_a] * (1 - discount_a)) / (prices[bench_b] * (1 - discount_b))
    out["bench_a"] = bench_a
    out["bench_b"] = bench_b
    out["country_a"] = name_a
    out["country_b"] = name_b
    out["geo_discount_a"] = discount_a
    out["geo_discount_b"] = discount_b
    return out


def annual_swap_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Annual average swap rate matrix for all benchmark pairs."""
    annual = prices.groupby("연도")[BENCHMARKS].mean()
    rows: list[dict] = []
    for year in annual.index:
        for a in BENCHMARKS:
            for b in BENCHMARKS:
                if a == b:
                    continue
                rows.append(
                    {
                        "연도": year,
                        "from": a,
                        "to": b,
                        "swap_rate": swap_rate(annual.loc[year, a], annual.loc[year, b]),
                    }
                )
    return pd.DataFrame(rows)


def monthly_swap_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Monthly swap rate for all benchmark pairs (long format)."""
    rows: list[dict] = []
    for _, row in prices.iterrows():
        for a in BENCHMARKS:
            for b in BENCHMARKS:
                if a == b:
                    continue
                rows.append(
                    {
                        "연월": row["연월"],
                        "연도": row["연도"],
                        "from": a,
                        "to": b,
                        "swap_rate": swap_rate(row[a], row[b]),
                    }
                )
    return pd.DataFrame(rows)


def resolve_benchmark(name: str) -> str:
    """Resolve country or benchmark name to a benchmark."""
    if name in BENCHMARKS:
        return name
    return COUNTRY_BENCHMARK.get(name, "Brent")


def country_year_totals(countries: pd.DataFrame, year: int) -> pd.DataFrame:
    """Country import volumes for a given year."""
    df = countries[countries["연도"] == year].copy()
    total = df["물량_천배럴"].sum()
    df["비중"] = df["물량_천배럴"] / total if total else 0.0
    return df


def hhi_by_year(countries: pd.DataFrame) -> pd.DataFrame:
    """Herfindahl-Hirschman Index by year (share as proportion, 0–1 scale)."""
    rows: list[dict] = []
    for year in sorted(countries["연도"].unique()):
        df = country_year_totals(countries, year)
        shares = df["비중"]
        rows.append({"연도": year, "HHI": (shares**2).sum()})
    return pd.DataFrame(rows)


def middle_east_share_by_year(countries: pd.DataFrame) -> pd.DataFrame:
    """Middle East import share (%) by year."""
    rows: list[dict] = []
    for year in sorted(countries["연도"].unique()):
        df = countries[countries["연도"] == year]
        total = df["물량_천배럴"].sum()
        me = df[df["대륙"] == MIDDLE_EAST_CONTINENT]["물량_천배럴"].sum()
        pct = (me / total * 100) if total else 0.0
        rows.append({"연도": year, "중동_의존도_pct": pct})
    return pd.DataFrame(rows)


def high_risk_share_by_year(countries: pd.DataFrame) -> pd.DataFrame:
    """High-risk country (Russia + Kazakhstan) exposure share (%) by year."""
    rows: list[dict] = []
    for year in sorted(countries["연도"].unique()):
        df = countries[countries["연도"] == year]
        total = df["물량_천배럴"].sum()
        risk = df[df["국가"].isin(HIGH_RISK_COUNTRIES)]["물량_천배럴"].sum()
        pct = (risk / total * 100) if total else 0.0
        rows.append({"연도": year, "고위험국_비중_pct": pct})
    return pd.DataFrame(rows)


def import_volatility_risk(countries: pd.DataFrame) -> pd.DataFrame:
    """Temporary risk proxy: coefficient of variation of import volumes (2020–2024)."""
    pivot = countries.pivot_table(
        index="국가", columns="연도", values="물량_천배럴", aggfunc="sum", fill_value=0
    )
    rows: list[dict] = []
    for country in pivot.index:
        vals = pivot.loc[country].values.astype(float)
        mean = vals.mean()
        std = vals.std()
        cv = (std / mean) if mean > 0 else 0.0
        bench = COUNTRY_BENCHMARK.get(country, "Brent")
        rows.append(
            {
                "국가": country,
                "변동계수": cv,
                "벤치마크": bench,
                "고위험": country in HIGH_RISK_COUNTRIES,
            }
        )
    return pd.DataFrame(rows).sort_values("변동계수", ascending=False)


def latest_swap_rate(
    prices: pd.DataFrame,
    bench_a: str,
    bench_b: str,
    country_a: str | None = None,
    country_b: str | None = None,
    geo_discount_a: float | None = None,
    geo_discount_b: float | None = None,
) -> tuple[float, str]:
    """Most recent monthly swap rate and period label."""
    series = monthly_swap_series(
        prices,
        bench_a,
        bench_b,
        country_a=country_a,
        country_b=country_b,
        geo_discount_a=geo_discount_a,
        geo_discount_b=geo_discount_b,
    )
    latest = series.iloc[-1]
    return float(latest["swap_rate"]), str(latest["연월"])

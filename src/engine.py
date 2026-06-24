"""Petroleum Swap Rate engine and import-structure metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BENCHMARKS = ["Dubai", "Brent", "WTI", "Oman"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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

GRADE_TO_DISCOUNT: dict[int, float] = {
    1: 0.00,
    2: 0.02,
    3: 0.04,
    4: 0.06,
    5: 0.09,
    6: 0.14,
    7: 0.22,
}

COUNTRY_ALIAS: dict[str, str | None] = {
    "아랍에미리트": "아랍에미리트 연합",
    "중립지대": None,
}

# Backward-compatible benchmark entries. Country-level discounts are resolved from K-SURE via geo_discount().
GEO_DISCOUNT: dict[str, float] = {}
GEO_DISCOUNT.update({b: 0.0 for b in BENCHMARKS})

# TODO(v2): route distance hardcoding → freightFactor
FREIGHT_FACTOR: dict[str, float] = {
    "카자흐스탄→한국": 1.0,
    "중동→한국": 1.0,
    "default": 1.0,
}


def _load_ksure_country_grades() -> pd.DataFrame:
    """Load K-SURE country ratings used as the source for geopolitical discounts."""
    df = pd.read_csv(DATA_DIR / "ksure_국가등급.csv", encoding="utf-8")
    df["국가명"] = df["국가명"].astype(str).str.strip()
    df["국가등급"] = pd.to_numeric(df["국가등급"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["국가명", "국가등급"])
    return df


_KSURE_GRADES = _load_ksure_country_grades()


def country_grade(country: str) -> int | None:
    """Resolve an import-data country name to a K-SURE country rating."""
    name = COUNTRY_ALIAS.get(country, country)
    if name is None or name in BENCHMARKS:
        return None

    exact = _KSURE_GRADES[_KSURE_GRADES["국가명"] == name]
    if len(exact):
        return int(exact.iloc[0]["국가등급"])

    names = _KSURE_GRADES["국가명"].astype(str)
    part = _KSURE_GRADES[
        names.str.contains(name, regex=False, na=False) | names.apply(lambda x: x in name)
    ]
    return int(part.iloc[0]["국가등급"]) if len(part) else None


def geo_discount(country: str) -> float:
    """Geopolitical discount from K-SURE rating. Missing ratings default to 0."""
    grade = country_grade(country)
    return GRADE_TO_DISCOUNT.get(grade, 0.0)


def ksure_country_risk(countries: pd.DataFrame) -> pd.DataFrame:
    """K-SURE ratings and derived discounts for crude import countries."""
    rows: list[dict] = []
    for country in sorted(countries["국가"].dropna().unique()):
        grade = country_grade(country)
        rows.append(
            {
                "국가": country,
                "K-SURE_국가등급": grade,
                "지정학_할인율": GRADE_TO_DISCOUNT.get(grade, 0.0),
                "벤치마크": COUNTRY_BENCHMARK.get(country, "Brent"),
                "최고위험": grade == 7,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["K-SURE_국가등급", "지정학_할인율", "국가"],
        ascending=[False, False, True],
        na_position="last",
    )


def load_oil_mining_risk() -> pd.DataFrame:
    """Load sparse K-SURE oil/mining sector risk index for reference display."""
    return pd.read_csv(DATA_DIR / "ksure_원유광업_위험지수.csv", encoding="utf-8")


def swap_rate(price_a: float, price_b: float) -> float:
    """A 1 barrel = B how many barrels (value basis)."""
    if price_b == 0:
        return float("nan")
    return price_a / price_b


def effective_price(country: str, benchmark_price: float, discount_override: float | None = None) -> float:
    """Country crude effective price = benchmark price x (1 - geopolitical discount)."""
    discount = geo_discount(country) if discount_override is None else discount_override
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
    discount_a = geo_discount(name_a) if geo_discount_a is None else geo_discount_a
    discount_b = geo_discount(name_b) if geo_discount_b is None else geo_discount_b
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

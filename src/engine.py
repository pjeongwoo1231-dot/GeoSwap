"""Petroleum Swap Rate engine and import-structure metrics."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pandas as pd

BENCHMARKS = ["Dubai", "Brent", "WTI", "Oman"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Country -> benchmark proxy for pricing (editable dict)
COUNTRY_BENCHMARK: dict[str, str] = {
    # Americas -> WTI
    "미국": "WTI",
    "캐나다": "WTI",
    "멕시코": "WTI",
    "브라질": "WTI",
    "에콰도르": "WTI",
    "콜롬비아": "WTI",
    # Middle East -> Dubai/Oman
    "사우디아라비아": "Dubai",
    "아랍에미리트": "Dubai",
    "쿠웨이트": "Dubai",
    "이라크": "Dubai",
    "카타르": "Dubai",
    "오만": "Oman",
    "중립지대": "Dubai",
    # Europe / Africa / CIS -> Brent
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

# Phase B model constants. Keep these top-level for easy tuning.
Q_API = 0.007
Q_S = 0.02
API_REF = 31.0
S_REF = 2.0
ALPHA = 0.5

GPR_REGION = {
    "사우디아라비아": "MiddleEast",
    "아랍에미리트": "MiddleEast",
    "쿠웨이트": "MiddleEast",
    "이라크": "MiddleEast",
    "카타르": "MiddleEast",
    "오만": "MiddleEast",
    "중립지대": "MiddleEast",
    "러시아": "Russia",
    "카자흐스탄": "Russia",  # CPC pipeline depends on Russian territory
    "베네수엘라": "Venezuela",
    "에콰도르": "Americas",
    "콜롬비아": "Americas",
    "미국": "Americas",
    "캐나다": "Americas",
    "멕시코": "Americas",
    "브라질": "Americas",
    "나이지리아": "Africa",
    "앙골라": "Africa",
    "가봉": "Africa",
    "콩고": "Africa",
    "적도기니": "Africa",
    "알제리": "Africa",
    "카메룬": "Africa",
    "노르웨이": "NorthSea",
    "영국": "NorthSea",
}

COUNTRY_ALIAS: dict[str, str | None] = {
    "아랍에미리트": "아랍에미리트 연합",
    "중립지대": None,
}

# Backward-compatible benchmark entries. Country-level discounts are resolved from K-SURE via geo_discount().
GEO_DISCOUNT: dict[str, float] = {}
GEO_DISCOUNT.update({b: 0.0 for b in BENCHMARKS})

# TODO(v2): route distance hardcoding -> freightFactor
FREIGHT_FACTOR: dict[str, float] = {
    "카자흐스탄→한국": 1.0,
    "중동→한국": 1.0,
    "default": 1.0,
}

# Phase E — route distance / carbon / freight (editable)
ROUTE_NM: dict[str, float] = {
    "중동": 6400,
    "카자흐스탄": 11500,
    "러시아": 8500,
    "미국": 9500,
    "서아프리카": 10500,
    "베네수엘라": 10000,
    "멕시코": 8500,
    "브라질": 11000,
    "유럽": 11000,
    "아시아": 2500,
}

COUNTRY_TO_ROUTE: dict[str, str] = {
    "사우디아라비아": "중동",
    "아랍에미리트": "중동",
    "쿠웨이트": "중동",
    "이라크": "중동",
    "카타르": "중동",
    "오만": "중동",
    "중립지대": "중동",
    "카자흐스탄": "카자흐스탄",
    "러시아": "러시아",
    "미국": "미국",
    "캐나다": "미국",
    "멕시코": "멕시코",
    "브라질": "브라질",
    "베네수엘라": "베네수엘라",
    "콜롬비아": "베네수엘라",
    "에콰도르": "베네수엘라",
    "나이지리아": "서아프리카",
    "앙골라": "서아프리카",
    "적도기니": "서아프리카",
    "가봉": "서아프리카",
    "콩고": "서아프리카",
    "알제리": "서아프리카",
    "카메룬": "서아프리카",
    "노르웨이": "유럽",
    "영국": "유럽",
}

CO2_PER_BBL_NM = 3e-7  # ton CO2 / (barrel·nm), ≈0.3 g CO2/(barrel·nm) IMO VLCC approx
FREIGHT_PER_BBL_NM = 3.9e-4  # USD / (barrel·nm)
ETS_EUR = 81.24  # gas_EU_ETS_탄소가격.csv latest annual avg (€/ton)
EUR_KRW = 1450  # FX for carbon value conversion

# Market impact model (adjustable)
BASE_ROUTE_NM = 6400  # safe import baseline: Middle East -> Korea
CRUDE_PRICE_USD = 73.0  # benchmark crude price ($/bbl)
STRUCTURING_FEE_RATE = 0.005  # structuring fee on swapped volume
TON_PER_TREE = 0.022  # annual CO2 uptake per tree (ton)
TON_PER_CAR = 4.6  # annual CO2 emissions per passenger car (ton)


def route_distance(country: str) -> float:
    """One-way sea distance (nm) from origin country to Korea (Ulsan approx)."""
    key = COUNTRY_TO_ROUTE.get(country)
    return ROUTE_NM.get(key, ROUTE_NM["아시아"])


def esg_swap_metrics(
    country_from: str,
    country_to: str,
    volume_bbl: float,
    ets_eur: float = ETS_EUR,
    eur_krw: float = EUR_KRW,
) -> dict[str, float]:
    """ESG savings when swapping risky origin imports for a safer origin."""
    d_from = route_distance(country_from)
    d_to = route_distance(country_to)
    d_saved = max(d_from - d_to, 0.0)
    co2_direct_ton = d_from * volume_bbl * CO2_PER_BBL_NM
    co2_swap_ton = d_to * volume_bbl * CO2_PER_BBL_NM
    co2_saved_ton = co2_direct_ton - co2_swap_ton
    freight_saved_usd = d_saved * volume_bbl * FREIGHT_PER_BBL_NM
    carbon_value_krw = co2_saved_ton * ets_eur * eur_krw
    return {
        "distance_from_nm": d_from,
        "distance_to_nm": d_to,
        "distance_saved_nm": d_saved,
        "co2_direct_ton": co2_direct_ton,
        "co2_swap_ton": co2_swap_ton,
        "co2_saved_ton": co2_saved_ton,
        "freight_saved_usd": freight_saved_usd,
        "carbon_value_krw": carbon_value_krw,
    }


def market_impact(
    countries: pd.DataFrame,
    year: int = 2024,
    fee_rate: float = STRUCTURING_FEE_RATE,
    ets_eur: float = ETS_EUR,
    eur_krw: float = EUR_KRW,
) -> dict:
    """Annual market size and ESG impact aggregated from country imports."""
    df = countries[countries["연도"] == year]
    total_vol = swap_vol = co2 = freight_usd = carbon_krw = fee_usd = 0.0
    per_country: list[dict] = []

    for _, row in df.iterrows():
        volume_bbl = int(row["물량_천배럴"]) * 1000
        if volume_bbl <= 0:
            continue

        total_vol += volume_bbl
        region = COUNTRY_TO_ROUTE.get(row["국가"])
        dist = ROUTE_NM.get(region, ROUTE_NM["아시아"])
        saved = max(dist - BASE_ROUTE_NM, 0.0)
        country_co2 = saved * volume_bbl * CO2_PER_BBL_NM
        country_freight_usd = saved * volume_bbl * FREIGHT_PER_BBL_NM
        country_carbon_krw = country_co2 * ets_eur * eur_krw

        co2 += country_co2
        freight_usd += country_freight_usd
        carbon_krw += country_carbon_krw

        if saved > 0:
            swap_vol += volume_bbl
            fee_usd += volume_bbl * CRUDE_PRICE_USD * fee_rate
            per_country.append(
                {
                    "국가": row["국가"],
                    "물량_배럴": volume_bbl,
                    "거리절감_nm": saved,
                    "탄소절감_t": country_co2,
                    "가치_원": country_carbon_krw + country_freight_usd * eur_krw,
                }
            )

    freight_krw = freight_usd * eur_krw
    fee_krw = fee_usd * eur_krw
    per_country_df = pd.DataFrame(per_country)
    if not per_country_df.empty:
        per_country_df = per_country_df.sort_values("가치_원", ascending=False).reset_index(drop=True)

    return {
        "총물량": total_vol,
        "스왑대상물량": swap_vol,
        "탄소절감_t": co2,
        "탄소가치_원": carbon_krw,
        "운임절감_원": freight_krw,
        "수수료_원": fee_krw,
        "사회가치_원": carbon_krw + freight_krw,
        "하나수익_원": fee_krw,
        "총시장_원": carbon_krw + freight_krw + fee_krw,
        "per_country": per_country_df,
        "나무": co2 / TON_PER_TREE,
        "승용차": co2 / TON_PER_CAR,
    }


def _read_csv_utf8(path: Path) -> pd.DataFrame:
    """Read UTF-8 CSV and strip duplicate BOM markers."""
    raw_bytes = path.read_bytes()
    while raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    return pd.read_csv(io.BytesIO(raw_bytes), encoding="utf-8")


def _country_name_variants(country: str) -> list[str]:
    """Return exact and alias country labels for lookup."""
    variants = [country]
    alias = COUNTRY_ALIAS.get(country)
    if alias and alias not in variants:
        variants.append(alias)
    for source, target in COUNTRY_ALIAS.items():
        if target == country and source not in variants:
            variants.append(source)
    return variants


@lru_cache(maxsize=1)
def _load_ksure_country_grades() -> pd.DataFrame:
    """Load K-SURE country ratings used as the source for geopolitical discounts."""
    path = DATA_DIR / "ksure_국가등급.csv"
    if not path.exists():
        return pd.DataFrame(columns=["국가명", "국가등급", "평가일자"])

    df = _read_csv_utf8(path)
    df["국가명"] = df["국가명"].astype(str).str.strip()
    df["국가등급"] = pd.to_numeric(df["국가등급"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["국가명", "국가등급"])
    return df


@lru_cache(maxsize=1)
def _load_oil_quality() -> pd.DataFrame:
    """Load crude API / sulfur quality reference data."""
    path = DATA_DIR / "원유품질_API황.csv"
    if not path.exists():
        return pd.DataFrame(columns=["국가명", "API_비중", "황함량_pct", "표본물량", "출처"])

    df = _read_csv_utf8(path)
    df["국가명"] = df["국가명"].astype(str).str.strip()
    for col in ["API_비중", "황함량_pct", "표본물량"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["국가명"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def _load_gpr_oil_region_monthly() -> pd.DataFrame:
    """Load monthly oil geopolitical risk indices by region."""
    path = DATA_DIR / "gpr_oil_region_monthly.csv"
    if not path.exists():
        return pd.DataFrame(columns=["Date", "연월"])

    df = _read_csv_utf8(path)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).reset_index(drop=True)
    df["연도"] = df["Date"].dt.year.astype("Int64")
    df["월"] = df["Date"].dt.month.astype("Int64")
    df["연월"] = df["Date"].dt.strftime("%Y-%m")
    for col in [c for c in df.columns if c.startswith("GPR_OIL")]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@lru_cache(maxsize=1)
def _quality_row(country: str) -> pd.Series | None:
    """Resolve a country to one row of API/sulfur quality data."""
    df = _load_oil_quality()
    if df.empty:
        return None

    for candidate in _country_name_variants(country):
        exact = df[df["국가명"] == candidate]
        if len(exact):
            return exact.iloc[0]

    for candidate in _country_name_variants(country):
        part = df[df["국가명"].astype(str).str.contains(candidate, regex=False, na=False)]
        if len(part):
            return part.iloc[0]

    return None


@lru_cache(maxsize=1)
def _gpr_region_for_country(country: str) -> str | None:
    """Resolve a country name to a GPR region column suffix."""
    for candidate in _country_name_variants(country):
        region = GPR_REGION.get(candidate)
        if region:
            return region
    return None


def _month_key(value: str | pd.Timestamp | None) -> str | None:
    """Normalize a value to YYYY-MM for monthly lookups."""
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m")


def country_grade(country: str) -> int | None:
    """Resolve an import-data country name to a K-SURE country rating."""
    name = COUNTRY_ALIAS.get(country, country)
    if name is None or name in BENCHMARKS:
        return None

    ksure_grades = _load_ksure_country_grades()
    if ksure_grades.empty:
        return None

    variants = _country_name_variants(name)
    for candidate in variants:
        exact = ksure_grades[ksure_grades["국가명"] == candidate]
        if len(exact):
            return int(exact.iloc[0]["국가등급"])

    names = ksure_grades["국가명"].astype(str)
    for candidate in variants:
        part = ksure_grades[
            names.str.contains(candidate, regex=False, na=False) | names.apply(lambda x: x in candidate)
        ]
        if len(part):
            return int(part.iloc[0]["국가등급"])

    return None


def quality_adj(country: str) -> float:
    """Static crude quality adjustment from API and sulfur content."""
    row = _quality_row(country)
    if row is None:
        return 1.0
    api = float(row["API_비중"])
    sulfur = float(row["황함량_pct"])
    return 1 + Q_API * (api - API_REF) - Q_S * (sulfur - S_REF)


def gpr_stress(region: str | None, t: str | pd.Timestamp | None) -> float:
    """Normalize GPR stress so median->0 and p90->1, clipped to [0, 2]."""
    if region is None:
        return 0.0

    df = _load_gpr_oil_region_monthly()
    col = f"GPR_OIL_{region}"
    if df.empty or col not in df.columns:
        return 0.0

    month_key = _month_key(t)
    if month_key is None:
        return 0.0

    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if series.empty:
        return 0.0

    value_rows = df.loc[df["연월"] == month_key, col].dropna()
    if value_rows.empty:
        return 0.0

    value = float(value_rows.iloc[0])
    median = float(series.median())
    p90 = float(series.quantile(0.9))
    if p90 <= median:
        return 0.0

    stress = (value - median) / (p90 - median)
    return float(max(0.0, min(2.0, stress)))


def geo_discount(country: str, t: str | pd.Timestamp | None = None) -> float:
    """Geopolitical discount from K-SURE rating and optional GPR shock."""
    grade = country_grade(country)
    base = GRADE_TO_DISCOUNT.get(grade, 0.0)
    if t is None:
        return base

    region = _gpr_region_for_country(country)
    stress = gpr_stress(region, t) if region else 0.0
    return base * (1 + ALPHA * stress)


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
    path = DATA_DIR / "ksure_원유광업_위험지수.csv"
    if not path.exists():
        return pd.DataFrame(columns=["국가명", "원유광업_위험지수", "기준년월"])
    return pd.read_csv(path, encoding="utf-8")


def swap_rate(price_a: float, price_b: float) -> float:
    """A 1 barrel = B how many barrels (value basis)."""
    if price_b == 0:
        return float("nan")
    return price_a / price_b


def effective_price(
    country: str,
    benchmark_price: float,
    t: str | pd.Timestamp | None = None,
    quality_override: float | None = None,
    geo_discount_override: float | None = None,
) -> float:
    """Country crude effective price = benchmark price x quality x (1 - discount)."""
    quality = quality_adj(country) if quality_override is None else quality_override
    discount = geo_discount(country, t) if geo_discount_override is None else geo_discount_override
    return benchmark_price * quality * (1 - discount)


def country_swap_rate(
    country_a: str,
    bench_price_a: float,
    country_b: str,
    bench_price_b: float,
    t: str | pd.Timestamp | None = None,
    geo_discount_a: float | None = None,
    geo_discount_b: float | None = None,
) -> float:
    """A 1 barrel = B how many barrels, including quality and geopolitical adjustments."""
    price_a = effective_price(country_a, bench_price_a, t=t, geo_discount_override=geo_discount_a)
    price_b = effective_price(country_b, bench_price_b, t=t, geo_discount_override=geo_discount_b)
    return swap_rate(price_a, price_b)


def adjusted_swap_rate(
    price_a: float,
    price_b: float,
    geo_discount_a: float = 0.0,
    geo_discount_b: float = 0.0,
    grade_adj: float = 1.0,
    freight_factor: float = 1.0,
    quality_a: float = 1.0,
    quality_b: float = 1.0,
) -> float:
    """v2-adjusted swap rate using discounted effective prices."""
    base = swap_rate(
        price_a * quality_a * (1 - geo_discount_a),
        price_b * quality_b * (1 - geo_discount_b),
    )
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
    """Monthly swap rate A->B time series."""
    out = prices[["연월", "연도", "월"]].copy()
    name_a = country_a or bench_a
    name_b = country_b or bench_b
    quality_a = quality_adj(name_a)
    quality_b = quality_adj(name_b)

    if geo_discount_a is None:
        discount_a = [geo_discount(name_a, month) for month in out["연월"]]
    else:
        discount_a = [geo_discount_a] * len(out)
    if geo_discount_b is None:
        discount_b = [geo_discount(name_b, month) for month in out["연월"]]
    else:
        discount_b = [geo_discount_b] * len(out)

    out["quality_adj_a"] = quality_a
    out["quality_adj_b"] = quality_b
    out["geo_discount_a"] = discount_a
    out["geo_discount_b"] = discount_b
    out["effective_price_a"] = prices[bench_a] * quality_a * (1 - out["geo_discount_a"])
    out["effective_price_b"] = prices[bench_b] * quality_b * (1 - out["geo_discount_b"])
    out["swap_rate"] = out["effective_price_a"] / out["effective_price_b"]
    out["bench_a"] = bench_a
    out["bench_b"] = bench_b
    out["country_a"] = name_a
    out["country_b"] = name_b
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
    """Herfindahl-Hirschman Index by year (share as proportion, 0-1 scale)."""
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
    """Temporary risk proxy: coefficient of variation of import volumes (2020-2024)."""
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
    month: str | pd.Timestamp | None = None,
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
    if month is not None:
        month_key = _month_key(month)
        if month_key is not None:
            filtered = series[series["연월"] == month_key]
            if len(filtered):
                latest = filtered.iloc[-1]
                return float(latest["swap_rate"]), str(latest["연월"])
    latest = series.iloc[-1]
    return float(latest["swap_rate"]), str(latest["연월"])

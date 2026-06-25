"""CSV loading and cleaning for Geo-Swap dashboard."""

import io
import re
from pathlib import Path

import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - fallback for non-Streamlit environments
    class _StreamlitFallback:
        @staticmethod
        def cache_data(*args, **kwargs):
            if args and callable(args[0]) and not kwargs:
                return args[0]

            def decorator(func):
                return func

            return decorator

    st = _StreamlitFallback()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

GRADE_MAP = {
    "경질유": "light",
    "중(中)질유": "medium",
    "중(重)질유": "heavy",
}

_MONTH_RE = re.compile(r"(?:(\d{2})년\s*)?(\d{1,2})월")
_SKIP_MONTH_LABELS = {"전월비", "전년동월비", "평균", "nan", ""}


def _read_csv_utf8(path: Path) -> pd.DataFrame:
    """Read UTF-8 CSV, tolerating duplicate BOM markers."""
    raw_bytes = path.read_bytes()
    while raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    return pd.read_csv(io.BytesIO(raw_bytes), encoding="utf-8")


def _extract_year_col(name: str) -> int | None:
    """Extract year from columns like 'Y2020 2020'."""
    if name.startswith("Y") and " " in name:
        return int(name.split()[0][1:])
    return None


@st.cache_data(show_spinner=False)
def load_ksure_country_grades(path: Path | None = None) -> pd.DataFrame:
    """Load K-SURE country grades (1=lowest risk, 7=highest risk)."""
    path = path or DATA_DIR / "ksure_국가등급.csv"
    df = _read_csv_utf8(path)
    df["국가명"] = df["국가명"].astype(str).str.strip()
    df["국가등급"] = pd.to_numeric(df["국가등급"], errors="coerce").astype("Int64")
    df["평가일자"] = pd.to_datetime(df["평가일자"], errors="coerce").dt.date
    return df.dropna(subset=["국가명", "국가등급"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_oil_quality(path: Path | None = None) -> pd.DataFrame:
    """Load crude oil API and sulfur quality reference data."""
    path = path or DATA_DIR / "원유품질_API황.csv"
    df = _read_csv_utf8(path)
    df["국가명"] = df["국가명"].astype(str).str.strip()
    for col in ["API_비중", "황함량_pct", "표본물량"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["국가명"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_eu_ets_carbon_prices(path: Path | None = None) -> pd.DataFrame:
    """Load EU ETS carbon prices by year."""
    path = path or DATA_DIR / "gas_EU_ETS_탄소가격.csv"
    df = _read_csv_utf8(path)
    df = df.rename(
        columns={
            "최저 가격(Euro)": "최저(Euro)",
            "최대 가격(Euro)": "최대(Euro)",
            "연평균 가격(Euro)": "연평균(Euro)",
        }
    )
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    for col in ["최저(Euro)", "최대(Euro)", "연평균(Euro)"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["연도"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_gpr_oil_region_monthly(path: Path | None = None) -> pd.DataFrame:
    """Load monthly oil geopolitical risk indices by region."""
    path = path or DATA_DIR / "gpr_oil_region_monthly.csv"
    df = _read_csv_utf8(path)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).reset_index(drop=True)
    df["연도"] = df["Date"].dt.year.astype("Int64")
    df["월"] = df["Date"].dt.month.astype("Int64")
    df["연월"] = df["Date"].dt.strftime("%Y-%m")
    for col in [c for c in df.columns if c.startswith("GPR_OIL")]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_ksure_oil_mining_risk(path: Path | None = None) -> pd.DataFrame:
    """Load the sparse K-SURE oil/mining sector risk reference table."""
    path = path or DATA_DIR / "ksure_원유광업_위험지수.csv"
    df = _read_csv_utf8(path)
    df["국가명"] = df["국가명"].astype(str).str.strip()
    df["원유광업_위험지수"] = pd.to_numeric(df["원유광업_위험지수"], errors="coerce")
    df["기준년월"] = df["기준년월"].astype(str).str.strip()
    return df.dropna(subset=["국가명"]).reset_index(drop=True)


def load_country_imports(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load country-level crude imports (thousand barrels, annual).

    Returns (country_rows, subtotal_rows) tidy DataFrames.
    """
    path = path or DATA_DIR / "국가별_원유수입.csv"
    raw = _read_csv_utf8(path)
    col0, col1 = raw.columns[0], raw.columns[1]
    year_cols = {c: _extract_year_col(c) for c in raw.columns[2:]}
    year_cols = {c: y for c, y in year_cols.items() if y is not None}

    country_rows: list[dict] = []
    subtotal_rows: list[dict] = []

    for _, row in raw.iterrows():
        label1 = str(row[col1]).strip()
        continent_raw = str(row[col0]).strip()
        continent = continent_raw.split(" ", 1)[1] if " " in continent_raw else continent_raw

        record_base = {"대륙": continent}
        for col, year in year_cols.items():
            val = row[col]
            if pd.isna(val) or val == "":
                val = 0
            else:
                val = int(float(val))

            rec = {**record_base, "연도": year, "물량_천배럴": val}
            if label1 == "소계":
                subtotal_rows.append(rec)
            else:
                country = label1.split(" ", 1)[1] if " " in label1 else label1
                country_rows.append({**rec, "국가": country})

    countries = pd.DataFrame(country_rows)
    subtotals = pd.DataFrame(subtotal_rows)
    return countries, subtotals


def load_grade_imports(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Load crude imports by grade (thousand barrels).

    Returns (annual_tidy, monthly_2024_or_none).
    """
    path = path or DATA_DIR / "유질별_원유수입.csv"
    raw = _read_csv_utf8(path)
    grade_col = raw.columns[0]
    monthly_cols = [c for c in raw.columns if str(c).startswith("2024.")]
    yearly_cols = [c for c in raw.columns if str(c).isdigit() and len(str(c)) == 4]

    annual_rows: list[dict] = []
    monthly_rows: list[dict] = []

    for _, row in raw.iterrows():
        grade_label = str(row[grade_col]).strip().strip('"')
        if grade_label == "합계":
            continue
        if grade_label not in GRADE_MAP:
            continue
        grade = GRADE_MAP[grade_label]

        for ycol in yearly_cols:
            year = int(ycol)
            val = row[ycol]
            val = 0 if pd.isna(val) or val == "" else int(float(val))
            annual_rows.append({"연도": year, "유질": grade, "물량_천배럴": val})

        if monthly_cols:
            total_2024 = sum(
                int(float(row[c])) if not pd.isna(row[c]) and row[c] != "" else 0
                for c in monthly_cols
            )
            annual_rows.append({"연도": 2024, "유질": grade, "물량_천배럴": total_2024})

            for mc in monthly_cols:
                month = int(str(mc).split(".")[1])
                val = row[mc]
                val = 0 if pd.isna(val) or val == "" else int(float(val))
                monthly_rows.append(
                    {"연월": f"2024-{month:02d}", "월": month, "유질": grade, "물량_천배럴": val}
                )

    annual = pd.DataFrame(annual_rows)
    monthly = pd.DataFrame(monthly_rows) if monthly_rows else None
    return annual, monthly


def load_oil_prices(path: Path | None = None) -> pd.DataFrame:
    """Load international benchmark prices ($/barrel, monthly)."""
    path = path or DATA_DIR / "국제유가.csv"
    raw = _read_csv_utf8(path)
    month_col = raw.columns[0]
    benchmarks = ["Dubai", "Brent", "WTI", "Oman"]
    current_year: int | None = None
    rows: list[dict] = []

    for _, row in raw.iterrows():
        month_str = str(row[month_col]).replace("\xa0", " ").strip()
        if month_str in _SKIP_MONTH_LABELS:
            continue

        match = _MONTH_RE.match(month_str)
        if not match:
            continue

        year_prefix, month = match.group(1), int(match.group(2))
        if year_prefix:
            current_year = 2000 + int(year_prefix)
        if current_year is None:
            continue

        rec: dict = {
            "연월": f"{current_year}-{month:02d}",
            "연도": current_year,
            "월": month,
        }
        for b in benchmarks:
            rec[b] = float(row[b])
        rows.append(rec)

    return pd.DataFrame(rows)


def load_all() -> dict:
    """Load all datasets into a single dict."""
    countries, subtotals = load_country_imports()
    grades, grades_monthly = load_grade_imports()
    prices = load_oil_prices()
    ksure_grades = load_ksure_country_grades()
    oil_quality = load_oil_quality()
    eu_ets = load_eu_ets_carbon_prices()
    gpr_region_monthly = load_gpr_oil_region_monthly()
    oil_mining_risk = load_ksure_oil_mining_risk()
    return {
        "countries": countries,
        "subtotals": subtotals,
        "grades": grades,
        "grades_monthly": grades_monthly,
        "prices": prices,
        "ksure_grades": ksure_grades,
        "oil_quality": oil_quality,
        "eu_ets": eu_ets,
        "gpr_region_monthly": gpr_region_monthly,
        "oil_mining_risk": oil_mining_risk,
    }

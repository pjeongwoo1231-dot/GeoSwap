"""충격 유형 판정 · 지정학 2성분 분해 (v2 엔진).

설계 근거 (Desktop/석유/ 코퍼스 28편):
- Kilian & Park (2009, IER): 유가 상승의 효과는 **부호가 충격 종류로 갈린다.**
  글로벌 총수요 / 공급교란 / 예비적 수요를 구분하지 않으면 계수가 상쇄된다.
- Kilian (2008, REStat): 오일쇼크기 가격상승 중 실제 생산차질로 설명되는 부분은 극히 일부.
  지정학 뉴스를 그대로 가격에 반영하면 과대추정이 된다.
- Caldara & Iacoviello (2022, AER): 충격으로 쓰는 것은 지수의 **수준**이 아니라
  log(1+GPR)의 AR 잔차(**혁신**)다. 높은 수준이 예측 가능하게 유지되면 혁신은 0이다.

이 모듈이 v1 대비 고치는 것 두 가지:
  ① GPR 수준 → GPR 혁신
  ② 지정학을 '할인' 하나로 보던 것을 **두 성분으로 분해**
     - 신용·인도 할인 (−): 위험 산지가 싸게 팔린다 (Urals형). 구조적, K-SURE 등급.
     - 희소성 프리미엄 (+): 봉쇄된 산지가 비싸게 팔린다 (호르무즈형). 국면적, 혁신 기반.
     v1은 ①만 갖고 있어서 2026-03 국면의 부호를 설명하지 못했다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from .engine import (
    GRADE_TO_DISCOUNT,
    _gpr_region_for_country,
    _load_gpr_oil_region_monthly,
    _month_key,
    country_grade,
    quality_adj,
    resolve_benchmark,
)

# ── 파라미터 ────────────────────────────────────────────────────────────────
AR_LAGS = 5                 # Caldara & Iacoviello가 쓰는 AR(5)
INNOV_SHOCK_Z = 1.5         # 이 이상이면 '지정학 혁신 발생'으로 본다
DISPERSION_SHOCK_Z = 2.0    # 벤치마크 스프레드가 이 이상 벌어지면 '산지 특이'
COMOVE_MIN_PCT = 0.05       # 월 5% 이상 함께 오르면 '전면적 상승'

# 희소성 프리미엄 계수. 2026-03 실측으로 캘리브레이션:
#   관측 Dubai 프리미엄 = (128.52 − 99.60) / 99.60 = 29.0%
#   같은 달 중동 GPR 혁신 z = 3.42  →  κ ≈ 0.290 / 3.42 ≈ 0.085
KAPPA = 0.085
KAPPA_RANGE = (0.055, 0.115)  # 파라미터 불확실성 밴드 (아래 주석 참조)

# 밴드의 성격: 표본오차가 아니라 **파라미터 불확실성**이다.
# Brown & Huntington(2015)에서 공급→가격 배율이 5.6~12.3배로 흩어지는 것과 같은 종류의
# 불확실성이며, 단일 점추정을 제시하는 것이 오히려 정밀도를 위장하는 것이 된다.

SHOCK_LABELS = {
    "quiet": "평시",
    "aggregate_demand": "글로벌 총수요",
    "supply_disruption": "공급교란",
    "precautionary": "예비적 수요",
    "regional_supply": "지역 공급·예비적 충격",  # 재고 없을 때의 미분리 상태
    "undetermined": "판정 보류",
    "no_data": "지정학 데이터 없음",
}

# 재고 신호 임계값 — 월간 전월비(%) 기준
INV_BUILD_PCT = 1.5     # 이 이상 쌓이면 '축적'
INV_DRAW_PCT = -1.0     # 이 이하로 빠지면 '인출'
INVENTORY_CSV = "eia_미국원유재고_월간.csv"


@lru_cache(maxsize=1)
def _load_inventory() -> pd.DataFrame:
    """EIA 주간 미국 원유재고(SPR 제외)를 월간 집계한 계열."""
    import pathlib

    path = pathlib.Path(__file__).resolve().parent.parent / "data" / INVENTORY_CSV
    if not path.exists():
        return pd.DataFrame(columns=["연월", "재고_천배럴", "전월비_pct", "평년대비_pct"])
    df = pd.read_csv(path)
    for c in ("재고_천배럴", "전월비_pct", "평년대비_pct"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def inventory_signal(t) -> dict:
    """월 t의 재고 방향. Kilian(2009) 식별의 핵심 판별자.

    · 가격↑ + 재고 **축적** → 예비적 수요 (장래 공급부족을 우려해 미리 사둔다)
    · 가격↑ + 재고 **인출·정체** → 물리적 공급교란 (실제로 부족해서 헐어 쓴다)

    ⚠ 미국 상업재고는 **세계 재고의 대리지표**다. 미국은 순수출국이고 호르무즈 노출도
    아시아보다 작으므로, 중동 초크포인트 사건에서는 신호가 약하게 나올 수 있다.
    OECD 상업재고를 넣으면 정확도가 올라간다.
    """
    key = _month_key(t)
    df = _load_inventory()
    if df.empty or key is None:
        return {"available": False, "mom": float("nan"), "vs_norm": float("nan"), "dir": "관측없음"}
    row = df.loc[df["연월"] == key]
    if row.empty:
        return {"available": False, "mom": float("nan"), "vs_norm": float("nan"), "dir": "관측없음"}
    mom = float(row.iloc[0]["전월비_pct"])
    vs = float(row.iloc[0]["평년대비_pct"])
    if mom >= INV_BUILD_PCT:
        d = "축적"
    elif mom <= INV_DRAW_PCT:
        d = "인출"
    else:
        d = "정체"
    return {"available": True, "mom": mom, "vs_norm": vs, "dir": d}


# ── GPR 혁신 ────────────────────────────────────────────────────────────────
@lru_cache(maxsize=16)
def _innovation_series(region: str) -> pd.DataFrame:
    """log(1+GPR)의 AR(5) 잔차를 표준편차로 나눈 혁신 시계열."""
    df = _load_gpr_oil_region_monthly()
    col = f"GPR_OIL_{region}"
    if df.empty or col not in df.columns:
        return pd.DataFrame(columns=["연월", "z"])

    y = np.log1p(pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float))
    if np.isnan(y).any() or len(y) <= AR_LAGS + AR_LAGS + 2:
        y = np.nan_to_num(y, nan=float(np.nanmedian(y)))

    rows_x, rows_y = [], []
    for i in range(AR_LAGS, len(y)):
        rows_x.append([1.0, *y[i - AR_LAGS : i]])
        rows_y.append(y[i])
    if len(rows_x) < AR_LAGS + 2:
        return pd.DataFrame(columns=["연월", "z"])

    X = np.asarray(rows_x)
    Y = np.asarray(rows_y)
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    dof = max(1, len(resid) - X.shape[1])
    sigma = float(np.sqrt((resid**2).sum() / dof)) or 1.0

    out = df[["연월"]].copy()
    z = np.full(len(df), np.nan)
    z[AR_LAGS:] = resid / sigma
    out["z"] = z
    return out


def gpr_innovation(region: str | None, t) -> float:
    """월 t의 지정학 혁신(표준화 잔차). 예측 가능한 고공 행진이면 0에 가깝다.

    ⚠ 관측이 없는 달은 0이 아니라 NaN을 낸다. 0을 내면 '지정학 평온'과
    '데이터 없음'이 같은 값이 되어, 결측 구간에서 프리미엄이 조용히 꺼진다.
    """
    if region is None:
        return float("nan")
    key = _month_key(t)
    if key is None:
        return float("nan")
    s = _innovation_series(region)
    if s.empty:
        return float("nan")
    hit = s.loc[s["연월"] == key, "z"].dropna()
    return float(hit.iloc[0]) if len(hit) else float("nan")


def gpr_coverage() -> tuple[str | None, str | None]:
    """지정학지수가 실제로 존재하는 구간 (최초월, 최종월)."""
    df = _load_gpr_oil_region_monthly()
    if df.empty or "연월" not in df.columns:
        return None, None
    months = df["연월"].dropna().sort_values()
    return (str(months.iloc[0]), str(months.iloc[-1])) if len(months) else (None, None)


def country_gpr_innovation(country: str, t) -> float:
    return gpr_innovation(_gpr_region_for_country(country), t)


# ── 벤치마크 분기 ───────────────────────────────────────────────────────────
def _price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.dropna(subset=["Dubai", "Brent"]).copy()
    df = df.sort_values("연월").reset_index(drop=True)
    df["spread"] = df["Brent"].astype(float) - df["Dubai"].astype(float)
    df["global"] = (df["Brent"].astype(float) + df["Dubai"].astype(float)) / 2.0
    df["global_ret"] = df["global"].pct_change()
    return df


def benchmark_dispersion(prices: pd.DataFrame, t) -> dict:
    """Brent−Dubai 스프레드가 평시 분포에서 얼마나 벗어났는가.

    두 벤치마크가 **함께** 움직였는지, **갈라졌는지**가
    총수요 충격과 산지 특이 충격을 가르는 관측 가능한 신호다.
    """
    key = _month_key(t)
    df = _price_frame(prices)
    if df.empty or key is None:
        return {"spread": float("nan"), "z": 0.0, "ret": 0.0}

    row = df.loc[df["연월"] == key]
    if row.empty:
        return {"spread": float("nan"), "z": 0.0, "ret": 0.0}
    row = row.iloc[0]

    # 당월을 제외한 과거 분포로 표준화 (사후편의 방지)
    hist = df.loc[df["연월"] < key, "spread"].dropna()
    if len(hist) < 12:
        hist = df["spread"].dropna()

    # 평균·표준편차 대신 **중위수·MAD**를 쓴다.
    # 2026-03 같은 극단치가 한 번 표본에 들어오면 표준편차가 폭증해
    # 그 다음 달의 (여전히 역대 2위인) 이탈을 '정상'으로 만들어 버린다.
    med = float(hist.median())
    mad = float((hist - med).abs().median())
    scale = mad * 1.4826 or float(hist.std(ddof=1)) or 1.0

    return {
        "spread": float(row["spread"]),
        "z": float((row["spread"] - med) / scale),
        "ret": float(row["global_ret"]) if pd.notna(row["global_ret"]) else 0.0,
        "hist_med": med,
        "hist_scale": scale,
    }


# ── 충격 유형 판정 ──────────────────────────────────────────────────────────
@dataclass
class ShockVerdict:
    kind: str
    label: str
    confidence: str
    region: str | None
    innovation: float
    dispersion_z: float
    global_ret: float
    evidence: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    inventory_dir: str = "관측없음"
    inventory_mom: float = float("nan")

    @property
    def is_regional(self) -> bool:
        """희소성 프리미엄을 부과할 국면인가 (산지 특이 충격 계열)."""
        return self.kind in ("regional_supply", "supply_disruption", "precautionary")


def classify_shock(prices: pd.DataFrame, t, regions=("MiddleEast", "Russia")) -> ShockVerdict:
    """월 t의 원유가격 국면을 세 유형으로 가른다.

    판정 규칙 (관측 가능한 신호만 사용):
      · 벤치마크가 **함께** 크게 올랐고 스프레드는 정상 → 글로벌 총수요
      · 스프레드가 크게 **갈라졌고** 지정학 혁신이 동반 → 지역 공급·예비적 충격
      · 둘 다 아니면 평시
    """
    disp = benchmark_dispersion(prices, t)
    inv = inventory_signal(t)
    innovs = {r: gpr_innovation(r, t) for r in regions}
    observed = {r: z for r, z in innovs.items() if not np.isnan(z)}

    dz, ret = disp["z"], disp["ret"]
    evidence, caveats = [], []

    if not observed:
        lo, hi = gpr_coverage()
        return ShockVerdict(
            kind="no_data",
            label=SHOCK_LABELS["no_data"],
            confidence="판정불가",
            region=None,
            innovation=float("nan"),
            dispersion_z=dz,
            global_ret=ret,
            evidence=[
                f"해당 월의 지정학지수 관측이 없다 (지수 보유 구간: {lo} ~ {hi}).",
                f"가격 신호만 관측됨 — 스프레드 {dz:+.1f}σ, 전월비 {ret:+.1%}.",
            ],
            caveats=["**지정학 성분을 판정할 수 없으므로 희소성 프리미엄을 부과하지 않는다.** "
                     "가격 신호만으로 지정학 기인을 단정하지 않는 것이 이 엔진의 규칙이다."],
        )

    top_region = max(observed, key=lambda r: observed[r])
    top_z = observed[top_region]

    big_move = abs(ret) >= COMOVE_MIN_PCT
    diverged = abs(dz) >= DISPERSION_SHOCK_Z
    geo = top_z >= INNOV_SHOCK_Z

    if diverged and geo:
        conf = "높음"
        evidence.append(
            f"벤치마크 스프레드가 평시 분포에서 {dz:+.1f}σ 이탈 "
            f"(Brent−Dubai = {disp['spread']:+.2f} USD/bbl) → 전면적 상승이 아니라 **산지 특이**"
        )
        evidence.append(f"{top_region} 지정학 혁신 z = {top_z:+.2f} (AR({AR_LAGS}) 잔차) → 지정학 기인")

        # 재고 방향으로 ①공급교란 / ③예비적 수요를 가른다 (Kilian 2009 식별)
        if inv["available"] and inv["dir"] == "축적":
            kind = "precautionary"
            evidence.append(
                f"재고 **{inv['dir']}** (전월비 {inv['mom']:+.1f}%) → 실제 부족이 아니라 "
                f"**장래 공급부족을 우려한 선제 매수**. Kilian(2009)의 예비적 수요 충격."
            )
            evidence.append(
                "⚠ Kilian·Park(2009) 기준 **이 유형이 자산가격에 유의한 음(−) 효과를 갖는 유일한 유형**이다. "
                "공급교란은 유의하지 않다. 즉 하방 리스크가 가장 큰 국면이다."
            )
        elif inv["available"] and inv["dir"] in ("인출", "정체"):
            kind = "supply_disruption"
            evidence.append(
                f"재고 **{inv['dir']}** (전월비 {inv['mom']:+.1f}%, 평년대비 {inv['vs_norm']:+.1f}%) → "
                f"보유분을 헐어 쓰고 있다 = **물리적 공급 차질**."
            )
        else:
            kind = "regional_supply"
            evidence.append("재고 관측이 없어 공급교란과 예비적 수요를 분리하지 못했다.")
    elif diverged and not geo:
        # 분기는 있으나 지정학 혁신이 없다 → 지정학에 귀속할 근거가 없으므로
        # '보류'로 두고 프리미엄을 부과하지 않는다. (아래에서 region=None이 되어 미부과)
        kind = "undetermined"
        conf = "낮음"
        evidence.append(f"스프레드 {dz:+.1f}σ 이탈은 관측되나 지정학 혁신(z={top_z:+.2f})이 동반되지 않음")
        evidence.append("**지정학에 귀속할 근거가 없으므로 프리미엄을 부과하지 않는다.**")
        caveats.append("품질 스프레드·정제마진·계절 요인 등 비지정학 요인일 수 있다. 단독 판정 근거로 쓰지 말 것.")
    elif big_move and not diverged:
        evidence.append(
            f"두 벤치마크가 함께 {ret:+.1%} 이동, 스프레드는 정상 범위({dz:+.1f}σ) → 산지 특이가 아닌 전면적 요인"
        )
        # 가격만 보면 '총수요'로 보이지만, 재고가 빠지고 있으면 공급 제약이다.
        if ret > 0 and inv["available"] and inv["dir"] in ("인출", "정체") and inv["vs_norm"] <= -5.0:
            kind = "supply_disruption"
            conf = "중간"
            evidence.append(
                f"그러나 재고가 **{inv['dir']}**(전월비 {inv['mom']:+.1f}%)이고 평년 대비 "
                f"**{inv['vs_norm']:+.1f}%**로 깊게 내려가 있다 → 수요 확장이 아니라 **공급 제약**이다."
            )
            evidence.append(
                "가격만 보면 두 벤치마크가 함께 올라 총수요로 보이지만, "
                "**재고 방향이 그 해석을 뒤집는다**(Kilian 2009 식별)."
            )
        else:
            kind = "aggregate_demand"
            conf = "중간"
            if inv["available"]:
                evidence.append(f"재고 {inv['dir']} (전월비 {inv['mom']:+.1f}%, 평년대비 {inv['vs_norm']:+.1f}%)")
            evidence.append("Kilian·Park(2009) 기준 이 유형은 **산지 간 교환비율을 거의 바꾸지 않는다** → 스왑 유인 낮음")
    elif geo:
        kind = "undetermined"
        conf = "낮음"
        evidence.append(f"{top_region} 지정학 혁신 z = {top_z:+.2f} 이나 가격 분기가 관측되지 않음")
        evidence.append("Kilian(2008): 지정학 사건 대부분은 가격으로 전이되지 않는다 → **프리미엄 미부과**")
    else:
        kind = "quiet"
        conf = "높음"
        evidence.append(f"스프레드 {dz:+.1f}σ, 전월비 {ret:+.1%}, 지정학 혁신 z={top_z:+.2f} — 모두 평시 범위")

    if kind == "regional_supply":
        caveats.append(
            "**공급교란과 예비적 수요를 분리하지 못했다.** 해당 월의 재고 관측이 없다. "
            "Kilian(2009)의 식별에는 재고 방향이 필요하다 — 예비적 수요는 재고 축적을 동반하고 "
            "물리적 교란은 그렇지 않다."
        )
    if kind in ("supply_disruption", "precautionary") and inv["available"]:
        caveats.append(
            "재고 대리지표는 **미국 상업재고(SPR 제외)**다. 미국은 순수출국이고 호르무즈 노출이 "
            "아시아보다 작으므로 중동 초크포인트 사건에서 신호가 약하게 나올 수 있다. "
            "OECD 상업재고를 투입하면 정확도가 올라간다."
        )

    return ShockVerdict(
        kind=kind,
        label=SHOCK_LABELS[kind],
        confidence=conf,
        region=top_region if geo else None,   # 지정학 귀속 근거가 있을 때만 프리미엄 대상 지역을 세운다
        innovation=top_z,
        dispersion_z=dz,
        global_ret=ret,
        evidence=evidence,
        caveats=caveats,
        inventory_dir=inv["dir"],
        inventory_mom=inv["mom"],
    )


# ── 지정학 2성분 ────────────────────────────────────────────────────────────
def credit_discount(country: str) -> float:
    """신용·인도 할인 (−). 구조적이며 K-SURE 국가등급만으로 정해진다.

    Urals형 — 상대방·인도 리스크를 진 산지의 원유는 **싸게** 팔린다.
    국면과 무관하므로 GPR을 곱하지 않는다. (v1의 곱셈이 여기서 제거됐다)
    """
    return GRADE_TO_DISCOUNT.get(country_grade(country), 0.0)


def scarcity_premium(country: str, t, verdict: ShockVerdict | None = None, kappa: float = KAPPA) -> float:
    """희소성 프리미엄 (+). 국면적이며 충격 유형이 켜고 끈다.

    호르무즈형 — 봉쇄·차질에 걸린 산지의 원유는 **비싸게** 팔린다.
    v1에는 이 성분이 아예 없었고, 그래서 2026-03의 부호를 설명하지 못했다.

    켜지는 조건 (Kilian·Park 2009 / Kilian 2008):
      · 지역 공급·예비적 충격일 때만 부과한다
      · 글로벌 총수요 충격에는 부과하지 않는다 — 양 산지가 함께 오르므로 교환비율이 안 바뀐다
      · 지정학 혁신이 있어도 가격 분기가 없으면 부과하지 않는다 — 대부분의 지정학은 가격에 안 간다
    """
    if verdict is None or not verdict.is_regional:
        return 0.0
    region = _gpr_region_for_country(country)
    if region is None or region != verdict.region:
        return 0.0  # 충격을 맞은 지역의 산지에만 부과
    z = gpr_innovation(region, t)
    if np.isnan(z):
        return 0.0
    return float(max(0.0, kappa * z))


def effective_price_v2(country: str, benchmark_price: float, t, verdict: ShockVerdict | None = None,
                       kappa: float = KAPPA) -> float:
    """유효가격 = 벤치마크 × 품질보정 × (1 − 신용할인) × (1 + 희소성 프리미엄)."""
    return (
        float(benchmark_price)
        * quality_adj(country)
        * (1.0 - credit_discount(country))
        * (1.0 + scarcity_premium(country, t, verdict, kappa))
    )


def swap_rate_v2(country_a: str, price_a: float, country_b: str, price_b: float, t,
                 verdict: ShockVerdict | None = None, kappa: float = KAPPA) -> float:
    pb = effective_price_v2(country_b, price_b, t, verdict, kappa)
    if not pb:
        return float("nan")
    return effective_price_v2(country_a, price_a, t, verdict, kappa) / pb


def swap_rate_band(country_a: str, price_a: float, country_b: str, price_b: float, t,
                   verdict: ShockVerdict | None = None) -> dict:
    """점추정 대신 밴드를 낸다 — κ 파라미터 불확실성을 전파한 결과."""
    lo_k, hi_k = KAPPA_RANGE
    mid = swap_rate_v2(country_a, price_a, country_b, price_b, t, verdict, KAPPA)
    a = swap_rate_v2(country_a, price_a, country_b, price_b, t, verdict, lo_k)
    b = swap_rate_v2(country_a, price_a, country_b, price_b, t, verdict, hi_k)
    lo, hi = (a, b) if a <= b else (b, a)
    return {"mid": mid, "low": lo, "high": hi, "width": hi - lo}


def monthly_series_v2(prices: pd.DataFrame, country_a: str, country_b: str) -> pd.DataFrame:
    """v2 엔진의 월별 교환비율 + 충격 유형 시계열."""
    bench_a, bench_b = resolve_benchmark(country_a), resolve_benchmark(country_b)
    rows = []
    for _, r in prices.dropna(subset=[bench_a, bench_b]).iterrows():
        month = r["연월"]
        v = classify_shock(prices, month)
        band = swap_rate_band(country_a, float(r[bench_a]), country_b, float(r[bench_b]), month, v)
        rows.append({
            "연월": month,
            "충격유형": v.label,
            "신뢰도": v.confidence,
            "재고": v.inventory_dir,
            "지정학혁신": round(v.innovation, 2),
            "스프레드z": round(v.dispersion_z, 2),
            "희소성프리미엄_A": round(scarcity_premium(country_a, month, v), 4),
            "희소성프리미엄_B": round(scarcity_premium(country_b, month, v), 4),
            "스왑비율": band["mid"],
            "하한": band["low"],
            "상한": band["high"],
        })
    return pd.DataFrame(rows)

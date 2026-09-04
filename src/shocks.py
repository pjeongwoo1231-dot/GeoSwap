"""국면 판정 · 인도위험 측정 (v3 엔진).

설계 근거 (Desktop/석유/ 코퍼스 28편 + 2026-09-04 가격 진본 대조):

- Kilian & Park (2009, IER): 유가 상승의 효과는 **부호가 충격 종류로 갈린다.**
  글로벌 총수요 / 공급교란 / 예비적 수요를 구분하지 않으면 계수가 상쇄된다.
- Kilian (2008, REStat): 오일쇼크기 가격상승 중 실제 생산차질로 설명되는 부분은 극히 일부.
  **지정학 뉴스로 가격을 예측하려 하면 과대추정이 된다.**
- Caldara & Iacoviello (2022, AER): 충격은 지수의 **수준**이 아니라
  log(1+GPR)의 AR 잔차(**혁신**)다.

■ v3가 v2에서 바꾼 것 — 그리고 왜 바꿨는가

v2는 지정학 혁신 × κ 로 **가격 성분을 예측**하려 했다. 두 가지 이유로 폐기했다.

  ① **부호가 틀렸다.** v2는 봉쇄된 산지가 비싸진다고 가정했다(희소성 프리미엄 +).
     진본 가격(World Bank Pink Sheet)으로 대조하니 정반대였다 —
     2026-04 Brent 120.40 vs Dubai 92.70, 즉 봉쇄된 중동산이 **23% 할인**되어 거래됐다.
     수송로가 막히면 산지의 배럴은 **좌초되어 싸진다**(Urals 패턴).
  ② **적합이 안 된다.** 감쇠 누적 모형을 돌려도 R² = 0.36이고 정점 월을 크게 빗나간다.
     수송로 봉쇄 사건이 표본에 **하나뿐**이므로 동적 반응함수를 추정할 수 없다.

→ **그래서 예측하지 않는다.** 지정학지수는 **국면을 분류**하는 데만 쓰고,
  크기는 **관측된 벤치마크 스프레드에서 직접 측정**한다.
  Kilian(2008)의 경고를 설계로 옮긴 결과이며, 적합 파라미터가 하나도 없다.
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
)

# ── 판정 임계값 ─────────────────────────────────────────────────────────────
AR_LAGS = 5                  # Caldara & Iacoviello가 쓰는 AR(5)
INNOV_SHOCK_Z = 1.5          # 이 이상이면 '지정학 혁신 발생'
SPREAD_SHOCK_PP = 4.0        # 인도위험 초과할인이 이 %p를 넘으면 '수송로 충격'
COMOVE_MIN_PCT = 0.05        # 월 5% 이상 함께 움직이면 '전면적 이동'

REGIME_LABELS = {
    "quiet": "평시",
    "aggregate_demand": "글로벌 총수요",
    "transit_shock": "수송로 충격",
    "producer_shock": "생산자 충격",
    "undetermined": "판정 보류",
    "no_data": "지정학 데이터 없음",
}

# ── 지정학지수 (진본) ───────────────────────────────────────────────────────
GPR_REAL_CSV = "gpr_real_caldara_iacoviello_monthly.csv"
GPR_REAL_PREFIX = "GPR_REAL_"


def _data_path(name: str):
    import pathlib

    return pathlib.Path(__file__).resolve().parent.parent / "data" / name


@lru_cache(maxsize=1)
def _load_gpr_real() -> pd.DataFrame:
    """Caldara & Iacoviello 진본 GPR (글로벌 + 국가/지역 분해), 월간."""
    path = _data_path(GPR_REAL_CSV)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["연월"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m")
    for c in df.columns:
        if c.startswith(GPR_REAL_PREFIX):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def gpr_source() -> str:
    return "진본 GPR (Caldara & Iacoviello 2022, AER)" if not _load_gpr_real().empty else "AI-GPR (자체 생성)"


@lru_cache(maxsize=16)
def _innovation_series(region: str) -> pd.DataFrame:
    """log(1+GPR)의 AR(5) 잔차를 표준편차로 나눈 혁신 시계열."""
    df = _load_gpr_real()
    col = f"{GPR_REAL_PREFIX}{region}"
    if df.empty or col not in df.columns:
        df = _load_gpr_oil_region_monthly()
        col = f"GPR_OIL_{region}"
    if df.empty or col not in df.columns:
        return pd.DataFrame(columns=["연월", "z"])

    y = np.log1p(pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float))
    y = np.nan_to_num(y, nan=float(np.nanmedian(y)))
    if len(y) < AR_LAGS * 2 + 2:
        return pd.DataFrame(columns=["연월", "z"])

    X = np.asarray([[1.0, *y[i - AR_LAGS : i]] for i in range(AR_LAGS, len(y))])
    Y = np.asarray([y[i] for i in range(AR_LAGS, len(y))])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    sigma = float(np.sqrt((resid**2).sum() / max(1, len(resid) - X.shape[1]))) or 1.0

    out = df[["연월"]].copy()
    z = np.full(len(df), np.nan)
    z[AR_LAGS:] = resid / sigma
    out["z"] = z
    return out


def gpr_innovation(region: str | None, t) -> float:
    """월 t의 지정학 혁신. 관측이 없으면 0이 아니라 NaN을 낸다.

    0을 내면 '지정학 평온'과 '데이터 없음'이 같은 값이 되어,
    결측 구간에서 리스크가 조용히 사라진다.
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


def country_gpr_innovation(country: str, t) -> float:
    return gpr_innovation(_gpr_region_for_country(country), t)


def gpr_coverage() -> tuple[str | None, str | None]:
    df = _load_gpr_real()
    if df.empty:
        df = _load_gpr_oil_region_monthly()
    if df.empty or "연월" not in df.columns:
        return None, None
    m = df["연월"].dropna().sort_values()
    return (str(m.iloc[0]), str(m.iloc[-1])) if len(m) else (None, None)


# ── 재고 (OECD 우선) ────────────────────────────────────────────────────────
INV_BUILD_PCT = 1.5
INV_DRAW_PCT = -1.0
US_INVENTORY_CSV = "eia_미국원유재고_월간.csv"
OECD_INVENTORY_CSV = "eia_steo_OECD상업재고_월간.csv"


@lru_cache(maxsize=2)
def _load_inv(name: str) -> pd.DataFrame:
    path = _data_path(name)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for c in df.columns:
        if c != "연월":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _dir_of(mom: float) -> str:
    return "축적" if mom >= INV_BUILD_PCT else ("인출" if mom <= INV_DRAW_PCT else "정체")


def _one_inv(df: pd.DataFrame, key: str | None) -> dict | None:
    if df.empty or key is None or "전월비_pct" not in df.columns:
        return None
    row = df.loc[df["연월"] == key]
    if row.empty or pd.isna(row.iloc[0]["전월비_pct"]):
        return None
    mom = float(row.iloc[0]["전월비_pct"])
    return {"mom": mom, "vs_norm": float(row.iloc[0]["평년대비_pct"]), "dir": _dir_of(mom)}


def inventory_signal(t) -> dict:
    """재고 방향. **주 지표는 OECD 상업재고**, 미국은 보조.

    미국은 순수출국이라 중동 초크포인트에 절연돼 있고, 한국은 OECD 회원국이다.
    2026-03에 두 지표가 정반대였다(미국 +5.0% 축적, OECD −0.9% 인출).
    """
    key = _month_key(t)
    oecd = _one_inv(_load_inv(OECD_INVENTORY_CSV), key)
    us = _one_inv(_load_inv(US_INVENTORY_CSV), key)
    primary = oecd or us
    if primary is None:
        return {"available": False, "mom": float("nan"), "vs_norm": float("nan"),
                "dir": "관측없음", "source": "없음", "us": us, "oecd": oecd, "conflict": False}
    conflict = bool(oecd and us and oecd["mom"] * us["mom"] < 0 and abs(oecd["mom"] - us["mom"]) >= 2.0)
    return {"available": True, **primary,
            "source": "OECD 상업재고" if oecd else "미국 상업재고(대체)",
            "us": us, "oecd": oecd, "conflict": conflict}


# ── 인도위험 할인 (모델이 아니라 관측) ──────────────────────────────────────
def _price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.dropna(subset=["Dubai", "Brent"]).sort_values("연월").reset_index(drop=True).copy()
    df["Brent"] = df["Brent"].astype(float)
    df["Dubai"] = df["Dubai"].astype(float)
    # 중동산(Dubai)이 대서양산(Brent) 대비 받는 할인율(%)
    df["disc"] = (df["Brent"] - df["Dubai"]) / df["Brent"] * 100.0
    df["global"] = (df["Brent"] + df["Dubai"]) / 2.0
    df["ret"] = df["global"].pct_change()
    return df


def delivery_discount(prices: pd.DataFrame, t) -> dict:
    """중동산 원유의 **인도위험 할인** — 관측값이다. 추정하지 않는다.

    수송로가 막히면 산지의 배럴은 나갈 수 없어 좌초되고, 그만큼 싸게 팔린다.
    그 크기는 Brent−Dubai 스프레드에 그대로 찍힌다.
    평시 중위 할인율을 빼서 '초과 할인'(%p)을 낸다.
    """
    key = _month_key(t)
    df = _price_frame(prices)
    empty = {"available": False, "disc": float("nan"), "base": float("nan"),
             "excess": 0.0, "spread": float("nan"), "ret": 0.0}
    if df.empty or key is None:
        return empty
    row = df.loc[df["연월"] == key]
    if row.empty:
        return empty
    row = row.iloc[0]
    hist = df.loc[df["연월"] < key, "disc"].dropna()
    if len(hist) < 12:
        hist = df["disc"].dropna()
    base = float(hist.median())
    return {
        "available": True,
        "disc": float(row["disc"]),
        "base": base,
        "excess": float(row["disc"] - base),
        "spread": float(row["Brent"] - row["Dubai"]),
        "ret": float(row["ret"]) if pd.notna(row["ret"]) else 0.0,
    }


MAX_EPISODE_MONTHS = 18  # 지속 판정을 소급할 최대 개월


def _transit_onset(prices: pd.DataFrame, key: str | None, regions=("MiddleEast", "Russia")) -> str | None:
    """t 이전에 개시된 수송로 충격이 아직 끝나지 않았는가.

    끝났다는 판정은 **할인이 평시로 복귀한 달이 하나라도 있었는가**로 한다.
    복귀가 있었으면 그 에피소드는 종료된 것이다.
    """
    if key is None:
        return None
    df = _price_frame(prices)
    months = [m for m in df["연월"].tolist() if m < key]
    for m in reversed(months[-MAX_EPISODE_MONTHS:]):
        dd = delivery_discount(prices, m)
        if dd["excess"] < SPREAD_SHOCK_PP:
            return None  # 평시 복귀가 있었다 → 에피소드 종료
        zs = [gpr_innovation(r, m) for r in regions]
        zs = [x for x in zs if not np.isnan(x)]
        if zs and max(zs) >= INNOV_SHOCK_Z:
            return m  # 개시 시점 발견
    return None


def onset_region(prices: pd.DataFrame, onset_month: str, regions=("MiddleEast", "Russia")) -> str | None:
    """개시월에 혁신이 가장 컸던 지역."""
    vals = {r: gpr_innovation(r, onset_month) for r in regions}
    vals = {r: v for r, v in vals.items() if not np.isnan(v)}
    return max(vals, key=lambda r: vals[r]) if vals else None


# ── 국면 판정 ───────────────────────────────────────────────────────────────
@dataclass
class Regime:
    kind: str
    label: str
    confidence: str
    region: str | None
    innovation: float
    excess_discount: float
    spread: float
    global_ret: float
    inventory_dir: str = "관측없음"
    inventory_mom: float = float("nan")
    evidence: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def swap_favorable(self) -> bool:
        """스왑 유인이 큰 국면인가."""
        return self.kind == "transit_shock"


def classify_regime(prices: pd.DataFrame, t, regions=("MiddleEast", "Russia")) -> Regime:
    """월 t의 원유시장 국면을 가른다. 관측 가능한 신호만 쓴다.

    · 스프레드가 크게 벌어졌고 지정학 혁신이 동반 → **수송로 충격**
      (봉쇄된 산지의 배럴이 좌초되어 할인된다. 스왑 유인 최대)
    · 벤치마크가 **함께** 급등했고 지정학 혁신이 동반 → **생산자 충격**
      (산지 간 교환비율이 거의 안 바뀐다. 스왑 유인 낮음)
    · 함께 크게 움직였는데 지정학 근거가 없음 → 글로벌 총수요
    · 스프레드는 벌어졌는데 지정학 근거가 없음 → 판정 보류 (귀속하지 않는다)
    """
    dd = delivery_discount(prices, t)
    inv = inventory_signal(t)
    innovs = {r: gpr_innovation(r, t) for r in regions}
    observed = {r: z for r, z in innovs.items() if not np.isnan(z)}

    excess, ret, spread = dd["excess"], dd["ret"], dd["spread"]
    ev: list[str] = []
    cav: list[str] = []

    def build(kind, conf, region, z_val):
        return Regime(kind=kind, label=REGIME_LABELS[kind], confidence=conf, region=region,
                      innovation=z_val, excess_discount=excess, spread=spread, global_ret=ret,
                      inventory_dir=inv["dir"], inventory_mom=inv["mom"],
                      evidence=ev, caveats=cav)

    if not observed:
        lo, hi = gpr_coverage()
        ev.append(f"해당 월의 지정학지수 관측이 없다 (보유 구간 {lo} ~ {hi}).")
        ev.append(f"가격 신호만 관측 — 인도위험 초과할인 {excess:+.1f}%p, 전월비 {ret:+.1%}.")
        cav.append("**지정학 성분을 판정할 수 없다.** 가격만으로 지정학 기인을 단정하지 않는다.")
        return build("no_data", "판정불가", None, float("nan"))

    top = max(observed, key=lambda r: observed[r])
    z = observed[top]
    geo = z >= INNOV_SHOCK_Z
    diverged = excess >= SPREAD_SHOCK_PP
    big = abs(ret) >= COMOVE_MIN_PCT

    if diverged and geo:
        ev.append(
            f"중동산 인도위험 초과할인 **{excess:+.1f}%p** "
            f"(Brent−Dubai = {spread:+.2f} USD/bbl) → 벤치마크가 **갈라졌다**"
        )
        ev.append(f"{top} 지정학 혁신 z = {z:+.2f} (AR({AR_LAGS}) 잔차) → 지정학 기인")
        ev.append(
            "**수송로 충격**의 서명이다 — 산지의 배럴이 물리적으로 나갈 수 없어 좌초되고, "
            "그만큼 할인되어 거래된다. 인도 가능한 대서양산은 반대로 프리미엄을 받는다."
        )
        if inv["available"]:
            ev.append(f"{inv['source']} {inv['dir']} (전월비 {inv['mom']:+.1f}%)")
        cav.append(
            "이 국면에서 싸진 것은 **가격이지 접근권이 아니다.** 할인폭은 곧 "
            "「그 배럴을 실제로 실어낼 수 있는가」에 시장이 매긴 값이다. "
            "인도를 확보할 수 없다면 할인은 기회가 아니라 경고다."
        )
        return build("transit_shock", "높음", top, z)

    if big and geo and not diverged:
        ev.append(f"두 벤치마크가 **함께** {ret:+.1%} 이동, 스프레드는 정상({excess:+.1f}%p)")
        ev.append(f"{top} 지정학 혁신 z = {z:+.2f} → 지정학 기인이나 **산지 특이가 아니다**")
        ev.append(
            "**생산자 충격**의 서명이다 — 특정 산유국이 제재·감산으로 막혀도 "
            "수송로가 열려 있으면 물량이 재배치되며 벤치마크는 나란히 움직인다. "
            "Kilian·Park(2009) 기준 **산지 간 교환비율이 거의 바뀌지 않으므로 스왑 유인이 낮다.**"
        )
        return build("producer_shock", "중간", top, z)

    if big and not diverged:
        ev.append(f"두 벤치마크가 함께 {ret:+.1%} 이동, 스프레드 정상({excess:+.1f}%p), 지정학 혁신 z={z:+.2f}")
        ev.append("전면적 수요·공급 요인. **교환비율을 거의 바꾸지 않으므로 스왑 유인이 낮다.**")
        return build("aggregate_demand", "중간", None, z)

    if diverged and not geo:
        # 봉쇄는 뉴스가 잠잠해졌다고 끝나지 않는다.
        # 혁신은 '놀람'을 재는 값이라 한 달 스파이크로 끝나지만, 수송로가 막힌 '상태'는 지속된다.
        # 직전에 수송로 충격이 개시됐고 그 이후 할인이 한 번도 정상으로 돌아오지 않았다면
        # 같은 국면의 **지속**으로 본다.
        onset = _transit_onset(prices, key=_month_key(t))
        if onset:
            ev.append(
                f"인도위험 초과할인 **{excess:+.1f}%p**가 유지되고 있다 "
                f"(Brent−Dubai = {spread:+.2f} USD/bbl)"
            )
            ev.append(
                f"지정학 혁신은 소멸했으나(z={z:+.2f}), **{onset}에 개시된 수송로 충격 이후 "
                "할인이 한 번도 평시로 복귀하지 않았다** → 같은 국면의 지속"
            )
            ev.append(
                "혁신은 '놀람'을 재는 값이라 한 달로 끝난다. "
                "그러나 **수송로가 막힌 상태는 지속된다** — 상태와 놀람을 구분한다."
            )
            if inv["available"]:
                ev.append(f"{inv['source']} {inv['dir']} (전월비 {inv['mom']:+.1f}%)")
            cav.append(
                "지속 판정은 **가격이 정상으로 복귀하지 않았다**는 사실에 근거한다. "
                "새로운 지정학 충격이 아니므로 신뢰도를 한 단계 낮춰 쓴다."
            )
            return build("transit_shock", "중간", onset_region(prices, onset), z)

        ev.append(f"인도위험 초과할인 {excess:+.1f}%p는 관측되나 지정학 혁신(z={z:+.2f})이 동반되지 않음")
        ev.append("**지정학에 귀속할 근거가 없으므로 지정학 국면으로 판정하지 않는다.**")
        cav.append(
            "품질 스프레드·정제마진·계절 요인일 수 있다. "
            "다만 **할인 자체는 실재**하므로 조달 단가에는 그대로 반영된다."
        )
        return build("undetermined", "낮음", None, z)

    ev.append(f"초과할인 {excess:+.1f}%p, 전월비 {ret:+.1%}, 지정학 혁신 z={z:+.2f} — 모두 평시 범위")
    return build("quiet", "높음", None, z)


# ── 구조적 신용·인도 할인 (K-SURE) ──────────────────────────────────────────
def credit_discount(country: str) -> float:
    """상대방 리스크에 대한 **구조적** 할인. K-SURE 국가등급만으로 정해진다.

    국면 성분(수송로 충격에 따른 좌초 할인)은 **벤치마크 가격에 이미 들어 있으므로**
    여기에 다시 곱하지 않는다. 이중계상 방지.
    """
    return GRADE_TO_DISCOUNT.get(country_grade(country), 0.0)


# ── 월별 국면 시계열 ────────────────────────────────────────────────────────
def monthly_regime_series(prices: pd.DataFrame, country_a: str, country_b: str) -> pd.DataFrame:
    from .engine import monthly_swap_series, resolve_benchmark

    swaps = monthly_swap_series(
        prices, resolve_benchmark(country_a), resolve_benchmark(country_b),
        country_a=country_a, country_b=country_b,
    ).set_index("연월")["swap_rate"]

    rows = []
    for m in prices.dropna(subset=["Dubai", "Brent"])["연월"]:
        r = classify_regime(prices, m)
        rows.append({
            "연월": m,
            "국면": r.label,
            "신뢰도": r.confidence,
            "인도위험 초과할인(%p)": round(r.excess_discount, 1),
            "Brent−Dubai": round(r.spread, 2),
            "지정학혁신": None if np.isnan(r.innovation) else round(r.innovation, 2),
            "재고": r.inventory_dir,
            "스왑비율": round(float(swaps.get(m, float("nan"))), 3),
        })
    return pd.DataFrame(rows)

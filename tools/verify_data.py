"""데이터 무결성 검증기.

왜 만들었나 — 이 프로젝트에서 데이터 오류를 **세 번** 겪었고, 세 번 다
그럴듯한 서사를 만들어 냈다. 가장 비쌌던 것:

  `국제유가.csv`의 2026-03 Dubai가 128.52로 들어가 있었다(진본 91.90).
  그 결과 "Brent−Dubai가 −28.92로 역전, 표본 차순위의 9배"라는 결론이 나왔고
  제출 문서의 중심 근거가 됐다. **부호까지 반대인 오류였다.**

교훈은 하나다 — **표본 내 차순위 대비 몇 배로 벌어진 극단치는
발견이 아니라 오류의 서명일 수 있다.** 채택 전에 독립 출처와 대조해야 한다.

이 스크립트는 그 대조를 자동화한다.

사용:
    python tools/verify_data.py            # 오프라인 검사만
    python tools/verify_data.py --online   # FRED 대조까지 (네트워크 필요)

실패가 하나라도 있으면 exit code 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.loaders import load_oil_prices  # noqa: E402

# 극단치 판정 — 차순위 대비 이 배율을 넘으면 경고
OUTLIER_RATIO = 3.0
# FRED 대조 허용 오차.
# 절대·상대를 함께 본다 — 저유가 국면(2020-04 배럴 $20대)에서 3달러는 13%지만
# 고유가 국면($120)에서는 2.5%다. 또 FRED(일별 현물 평균)와 World Bank(월간 평가가격)는
# 산출 방식이 달라 변동성이 큰 달에는 몇 달러 벌어지는 것이 정상이다.
FRED_TOL_ABS = 3.0
FRED_TOL_REL = 0.06

# 조사 완료된 기지(旣知) 불일치 — 이유가 확인된 것만 등록한다.
# 원칙: 등록 없이 통과시키지 않고, 등록할 때는 반드시 근거를 적는다.
KNOWN_DIFFS = {
    ("Brent", "2020-04"): (
        "World Bank 23.3 vs EIA/FRED 18.38. 2026-09-04 3개 출처 대조 확인 — "
        "COVID 붕괴월(WTI 마이너스 진입)로 평가 방식 차이가 벌어진 구간이며 "
        "World Bank Brent만 높다. 같은 해 다른 달은 모두 일치한다(2020-01 63.6 vs 63.65 등). "
        "분석 구간(2022·2026) 밖이고, 인도위험 기준선은 중위수라 단월 이상치의 영향이 없다."
    ),
}

FAILS: list[str] = []
WARNS: list[str] = []
OKS: list[str] = []


def ok(msg):
    OKS.append(msg)


def warn(msg):
    WARNS.append(msg)


def fail(msg):
    FAILS.append(msg)


# ── 1. 가격 계열 내부 정합성 ────────────────────────────────────────────────
def check_price_sanity(p: pd.DataFrame) -> None:
    need = ["Brent", "Dubai", "WTI"]
    missing = [c for c in need if c not in p.columns]
    if missing:
        fail(f"가격 컬럼 누락: {missing}")
        return

    for c in need:
        bad = p[(p[c] <= 0) | (p[c] > 300)]
        if len(bad):
            fail(f"{c} 비현실적 값 {len(bad)}건: {bad['연월'].tolist()[:5]}")
    ok(f"가격 범위 검사 통과 ({len(p)}개월, {p['연월'].min()} ~ {p['연월'].max()})")

    # 월간 변화율이 ±60%를 넘으면 의심
    for c in need:
        r = p[c].pct_change().abs()
        hits = p.loc[r > 0.60, "연월"].tolist()
        if hits:
            warn(f"{c} 월간 변동 60% 초과: {hits}")


# ── 2. 스프레드 극단치 — 이 검사가 −28.92를 잡았어야 했다 ──────────────────
def check_spread_outlier(p: pd.DataFrame) -> None:
    d = p.dropna(subset=["Brent", "Dubai"]).copy()
    d["spread"] = d["Brent"] - d["Dubai"]
    s = d["spread"].abs().sort_values(ascending=False)
    if len(s) < 3:
        return
    top, second = float(s.iloc[0]), float(s.iloc[1])
    ratio = top / second if second else float("inf")
    top_m = d.loc[s.index[0], "연월"]

    if ratio >= OUTLIER_RATIO:
        fail(
            f"Brent−Dubai 극단치 — {top_m}의 |{top:.2f}|가 차순위 |{second:.2f}|의 "
            f"**{ratio:.1f}배**. 발견으로 채택하기 전에 독립 출처 2곳과 대조할 것. "
            f"(이 검사가 없어서 2026-03 −28.92 오류를 놓쳤다)"
        )
    else:
        ok(f"Brent−Dubai 극단치 검사 통과 (최대 {top:.2f} @{top_m}, 차순위 대비 {ratio:.1f}배)")

    # 부호 상식: 통상 Brent ≥ Dubai (경질저유황 프리미엄)
    neg = d[d["spread"] < -2.0]
    if len(neg):
        warn(
            f"Brent < Dubai 가 2달러 넘게 역전된 달 {len(neg)}건: {neg['연월'].tolist()[:6]}. "
            "물리적으로 가능하나 드물다 — 원자료 확인 권장."
        )


# ── 3. 계열 간 커버리지 ─────────────────────────────────────────────────────
def check_coverage() -> None:
    from src.shocks import gpr_coverage, inventory_coverage

    p = load_oil_prices()
    price_last = str(p["연월"].max())
    gpr_last = gpr_coverage()[1]
    inv_last = inventory_coverage()

    ok(f"커버리지 — 유가 {price_last} · 지정학지수 {gpr_last} · 재고 {inv_last}")

    lasts = {"유가": price_last, "지정학지수": gpr_last, "재고": inv_last}
    valid = {k: v for k, v in lasts.items() if v and v != "관측없음"}
    if valid:
        binding = min(valid, key=lambda k: valid[k])
        if len(set(valid.values())) > 1:
            warn(
                f"계열 종료월이 어긋난다 → **판정 가능 구간은 '{binding}'({valid[binding]})가 제한**한다. "
                "가장 짧은 계열을 먼저 갱신할 것."
            )


# ── 4. FRED 대조 (온라인) ───────────────────────────────────────────────────
def check_against_fred(p: pd.DataFrame) -> None:
    import urllib.request

    series = {"Brent": "DCOILBRENTEU", "WTI": "DCOILWTICO"}
    for col, sid in series.items():
        url = (
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            f"&cosd=2020-01-01"
        )
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = pd.read_csv(r)
        except Exception as e:  # noqa: BLE001
            warn(f"FRED 조회 실패 ({sid}): {e}")
            continue

        raw.columns = ["date", "v"]
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["v"] = pd.to_numeric(raw["v"], errors="coerce")
        m = raw.dropna().set_index("date")["v"].resample("MS").mean()
        ref = pd.DataFrame({"연월": m.index.strftime("%Y-%m"), "fred": m.values})

        j = p[["연월", col]].merge(ref, on="연월", how="inner").dropna()
        if j.empty:
            warn(f"{col}: FRED와 겹치는 구간이 없다")
            continue
        j["diff"] = (j[col] - j["fred"]).abs()
        j["rel"] = j["diff"] / j["fred"].abs()
        over = j[(j["diff"] > FRED_TOL_ABS) & (j["rel"] > FRED_TOL_REL)]
        known = over[over["연월"].map(lambda m: (col, m) in KNOWN_DIFFS)]
        bad = over[~over["연월"].map(lambda m: (col, m) in KNOWN_DIFFS)]
        soft = j[(j["diff"] > FRED_TOL_ABS) & (j["rel"] <= FRED_TOL_REL)]
        for _, r in known.iterrows():
            warn(f"{col} {r['연월']}: 기지 불일치 — {KNOWN_DIFFS[(col, r['연월'])]}")
        if len(bad):
            rows = ", ".join(
                f"{r['연월']}(CSV {r[col]:.1f} vs FRED {r['fred']:.1f}, {r['rel']:.0%})"
                for _, r in bad.head(5).iterrows()
            )
            fail(f"{col}: FRED와 절대 {FRED_TOL_ABS}달러·상대 {FRED_TOL_REL:.0%}를 모두 넘긴 달 {len(bad)}건 — {rows}")
        else:
            ok(
                f"{col}: FRED 대조 통과 ({len(j)}개월, 최대 오차 {j['diff'].max():.2f}달러 / "
                f"{j['rel'].max():.1%})"
            )
        if len(soft):
            warn(
                f"{col}: 절대 오차는 크나 상대 오차는 허용 범위인 달 {len(soft)}건 "
                f"({', '.join(soft['연월'].head(4))}) — 변동성 국면의 산출방식 차이로 본다"
            )


# ── 5. 수입 통계 정합성 ─────────────────────────────────────────────────────
def check_imports() -> None:
    from src.loaders import load_country_imports

    countries, subtotals = load_country_imports()
    for year in sorted(countries["연도"].unique()):
        tot = subtotals[(subtotals["연도"] == year) & (subtotals["대륙"] == "합계")]["물량_천배럴"]
        parts = subtotals[(subtotals["연도"] == year) & (subtotals["대륙"] != "합계")]["물량_천배럴"].sum()
        if tot.empty:
            continue
        t = int(tot.iloc[0])
        if t == 0:
            continue
        gap = abs(t - int(parts)) / t
        if gap > 0.02:
            warn(f"{year} 합계({t:,})와 대륙 소계 합({int(parts):,})이 {gap:.1%} 어긋난다")
    ok(f"원유수입 합계 정합성 검사 완료 (연도 {countries['연도'].min()}~{countries['연도'].max()})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true", help="FRED 대조까지 수행")
    args = ap.parse_args()

    p = load_oil_prices()
    check_price_sanity(p)
    check_spread_outlier(p)
    check_coverage()
    check_imports()
    if args.online:
        check_against_fred(p)

    print("=" * 72)
    for m in OKS:
        print(f"  [OK]   {m}")
    for m in WARNS:
        print(f"  [WARN] {m}")
    for m in FAILS:
        print(f"  [FAIL] {m}")
    print("=" * 72)
    print(f"  통과 {len(OKS)} · 경고 {len(WARNS)} · 실패 {len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

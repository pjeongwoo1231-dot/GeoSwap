"""초크포인트 노출 모형 — 한국행 원유가 지나야 하는 관문들.

■ 왜 필요한가

v3 엔진의 가격 신호(Brent−Dubai 인도위험 할인)는 **호르무즈 하나만** 잡는다.
표본에 수송로 봉쇄 사건이 1건뿐이라는 것이 이 모델의 최대 약점이었다.

그런데 초크포인트는 호르무즈만이 아니고, 나머지에는 공개 가격 계열이 없다.
그래서 **가격 신호가 없는 곳은 노출 구조로 잡는다.**

  · 가격 신호 있음 → 얼마나 비싸졌나 (호르무즈)
  · 가격 신호 없음 → **막히면 얼마가 묶이나** (말라카·터키해협·바브엘만데브)

후자는 추정이 아니라 **도입 실적에 경로를 대입한 산술**이다.

■ 이 모형이 드러내는 것 — 우회로는 공짜가 아니다

호르무즈를 피하는 사우디 East-West 파이프라인은 **얀부(홍해)로 나온다.**
그리고 얀부에서 동아시아로 가려면 **바브엘만데브를 지나야 한다.**
즉 우회로가 또 다른 초크포인트로 들어간다 — 이것을 '직렬 의존'이라 부른다.

카자흐스탄은 더 심하다. CPC 파이프라인은 **러시아 영토**를 지나 흑해로 나오고,
거기서 **터키 해협 → 수에즈 → 바브엘만데브 → 말라카**를 지나야 한국에 닿는다.
관문 넷을 통과해야 실물이 온다.

**바로 그래서 스왑이 답이다.** 물리적 인도가 넷의 곱으로 어려워질수록,
'인도처를 맞바꾸는' 금융적 해법의 가치가 커진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# ── 우회 능력 가정 ──────────────────────────────────────────────────────────
# ⚠ 이 값들은 **가정**이며 추정된 계수가 아니다. 근거를 함께 적고 UI에서 조정 가능하게 한다.
#   각국 총수출 대비 '호르무즈를 피해 내보낼 수 있는 비율'이다.
BYPASS_SHARE = {
    "사우디아라비아": 0.55,   # East-West(Petroline) 얀부행. 공칭 5.0 mb/d, 수출 약 6.3 mb/d
    "아랍에미리트": 0.65,     # ADCOP 후자이라행 약 1.8 mb/d. Murban은 상당 부분 이미 후자이라 선적
    "이라크": 0.13,           # 이라크-튀르키예 파이프라인(제이한) 약 0.45 mb/d. 잦은 가동중단
    "쿠웨이트": 0.0,          # 대체 경로 없음
    "카타르": 0.0,            # 대체 경로 없음
    "중립지대": 0.0,          # 대체 경로 없음
    "바레인": 0.0,
    "이란": 0.0,              # 자스크 터미널이 있으나 대한 수입 실적 없음
}

# 우회로가 빠져나가는 관문 — 우회가 곧 안전이 아니다
BYPASS_EXIT = {
    "사우디아라비아": "바브엘만데브",   # 얀부(홍해) → 남하
    "아랍에미리트": None,               # 후자이라는 오만만(灣), 관문 밖
    "이라크": "터키 해협",              # 제이한은 지중해 → 수에즈 경유 동행
}


@dataclass
class Chokepoint:
    key: str
    name: str
    eng: str
    origins: list[str]                    # 이 관문을 지나야 하는 산지
    note: str
    price_signal: str | None = None       # 가격 신호가 있으면 그 이름
    bypass_note: str = ""
    serial: list[str] = field(default_factory=list)  # 우회 시 만나는 다음 관문


CHOKEPOINTS: list[Chokepoint] = [
    Chokepoint(
        key="hormuz",
        name="호르무즈 해협",
        eng="Strait of Hormuz",
        origins=["사우디아라비아", "아랍에미리트", "쿠웨이트", "카타르", "이라크", "중립지대", "바레인", "이란"],
        note=(
            "걸프 내부에서 나오는 모든 원유가 지난다. **오만은 관문 밖**이다 — "
            "미나 알파할·두쿰은 오만만·아라비아해에 면해 있어 해협을 통과하지 않는다."
        ),
        price_signal="Brent−Dubai 인도위험 할인",
        bypass_note="사우디 East-West(얀부)·UAE ADCOP(후자이라)·이라크 제이한",
        serial=["바브엘만데브", "터키 해협"],
    ),
    Chokepoint(
        key="malacca",
        name="말라카 해협",
        eng="Strait of Malacca",
        origins=[
            "사우디아라비아", "아랍에미리트", "쿠웨이트", "카타르", "이라크", "중립지대", "오만", "바레인", "이란",
            "카자흐스탄", "러시아", "알제리", "나이지리아", "적도기니", "모잠비크", "카메룬", "콩고", "가봉",
        ],
        note=(
            "중동·아프리카·유럽에서 한국으로 오는 물량이 지난다. "
            "**아메리카·호주·동남아 물량은 지나지 않는다** — 태평양 항로다."
        ),
        price_signal=None,
        bypass_note="롬복·순다 해협 (VLCC 통항 가능, 항해 3~5일 추가)",
    ),
    Chokepoint(
        key="turkish",
        name="터키 해협",
        eng="Turkish Straits (Bosphorus·Dardanelles)",
        origins=["카자흐스탄", "러시아"],
        note=(
            "흑해에서 지중해로 나가는 유일한 해상 통로. **카자흐 CPC Blend가 여기로 나온다.** "
            "그리고 CPC 파이프라인은 **러시아 영토**를 지난다 — 카자흐는 관문과 영토에 이중으로 걸려 있다."
        ),
        price_signal=None,
        bypass_note="BTC 파이프라인(아제르바이잔 경유 제이한) — 카자흐 물량 일부만",
    ),
    Chokepoint(
        key="babelmandeb",
        name="바브엘만데브",
        eng="Bab el-Mandeb",
        origins=["알제리", "나이지리아", "적도기니", "카메룬", "콩고", "가봉", "모잠비크",
                 "카자흐스탄", "러시아"],  # 흑해·지중해발 한국행은 수에즈→홍해로 내려온다
        note=(
            "홍해 남쪽 관문. 한국행 **직접** 통과 물량은 작지만, "
            "**호르무즈 우회로(사우디 얀부)의 출구**라는 점이 핵심이다 — 우회가 곧 안전은 아니다."
        ),
        price_signal=None,
        bypass_note="희망봉 우회 (항해 10~14일 추가)",
    ),
]

CHOKEPOINT_BY_KEY = {c.key: c for c in CHOKEPOINTS}

# 카자흐 원유가 한국에 닿기까지 지나는 관문 사슬
KAZAKH_CHAIN = ["러시아 영토 (CPC 파이프라인)", "터키 해협", "수에즈", "바브엘만데브", "말라카 해협"]


def _year_volumes(countries: pd.DataFrame, year: int) -> dict[str, float]:
    d = countries[countries["연도"] == year]
    return {str(r["국가"]): float(r["물량_천배럴"]) for _, r in d.iterrows()}


def exposure(countries: pd.DataFrame, year: int, bypass: dict[str, float] | None = None) -> pd.DataFrame:
    """관문별 한국 도입물량 노출.

    통과물량 = 그 관문을 지나야 하는 산지들의 도입 합
    우회가능 = 통과물량 × 산지별 우회 비율 (호르무즈에만 적용)
    순노출   = 통과물량 − 우회가능
    """
    bypass = BYPASS_SHARE if bypass is None else bypass
    vols = _year_volumes(countries, year)
    total = sum(vols.values())

    rows = []
    for cp in CHOKEPOINTS:
        transit = sum(vols.get(o, 0.0) for o in cp.origins)
        if cp.key == "hormuz":
            byp = sum(vols.get(o, 0.0) * bypass.get(o, 0.0) for o in cp.origins)
        else:
            byp = 0.0
        rows.append({
            "관문": cp.name,
            "통과물량_천배럴": round(transit),
            "통과비중": round(transit / total * 100, 1) if total else 0.0,
            "우회가능_천배럴": round(byp),
            "순노출_천배럴": round(transit - byp),
            "순노출비중": round((transit - byp) / total * 100, 1) if total else 0.0,
            "가격신호": cp.price_signal or "—",
        })
    return pd.DataFrame(rows)


def alternatives(countries: pd.DataFrame, year: int, key: str) -> dict:
    """해당 관문이 막혔을 때 **영향받지 않는** 산지의 규모와 집중도."""
    cp = CHOKEPOINT_BY_KEY[key]
    vols = _year_volumes(countries, year)
    total = sum(vols.values())
    safe = {k: v for k, v in vols.items() if k not in cp.origins and v > 0}
    safe_total = sum(safe.values())
    hhi = sum((v / safe_total * 100) ** 2 for v in safe.values()) if safe_total else 0.0
    top = sorted(safe.items(), key=lambda kv: -kv[1])[:5]
    return {
        "안전물량_천배럴": round(safe_total),
        "안전비중": round(safe_total / total * 100, 1) if total else 0.0,
        "대체산지_HHI": round(hhi),
        "상위_대체산지": top,
        "관문": cp,
    }


def serial_dependency(countries: pd.DataFrame, year: int) -> pd.DataFrame:
    """우회로가 어느 관문으로 빠져나가는가 — 우회는 공짜가 아니다."""
    vols = _year_volumes(countries, year)
    rows = []
    for origin, share in BYPASS_SHARE.items():
        v = vols.get(origin, 0.0)
        if v <= 0 or share <= 0:
            continue
        rows.append({
            "산지": origin,
            "도입물량_천배럴": round(v),
            "우회비율": f"{share:.0%}",
            "우회가능_천배럴": round(v * share),
            "우회로 출구": BYPASS_EXIT.get(origin) or "관문 밖 (안전)",
        })
    return pd.DataFrame(rows)


def concentration_risk(countries: pd.DataFrame, year: int) -> dict:
    """가장 아픈 관문과, 그 관문 하나로 묶이는 비중."""
    e = exposure(countries, year)
    worst = e.loc[e["순노출비중"].idxmax()]
    return {
        "최대관문": worst["관문"],
        "순노출비중": float(worst["순노출비중"]),
        "순노출_천배럴": int(worst["순노출_천배럴"]),
    }

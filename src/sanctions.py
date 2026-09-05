"""무역금융 제재 스크리닝 — OFAC SDN 선박 대조.

■ 왜 이 기능이 필요한가

원유 **직도입**은 국내 정유 4사와 한국석유공사만 수행한다. 그러나 은행 무역금융의
실제 고객층은 그 아래에 있다 — **나프타·벙커C유·아스팔트·윤활기유·석유코크스 등
파생 원자재를 수입신용장(L/C)으로 들여오는 중견·중소 법인 금융소비자**들이다.

이들은 자체 컴플라이언스 조직이 얇다. 그래서 거래 상대가 붙여 준 선박이
**OFAC 제재 대상(그림자 선단)**인지 모른 채 L/C를 개설하고, 사후에
계좌 동결·2차 제재(secondary sanctions)에 걸린다. 은행도 함께 걸린다.

→ **L/C 개설 시점에 선박을 대조**하는 것이 가장 값싼 방어다.

■ 데이터

미국 재무부 OFAC **SDN(Specially Designated Nationals) 목록**의 선박 항목.
공개 다운로드이며 API 키가 필요 없다.
  https://sanctionslistservice.ofac.treas.gov/api/download/sdn.csv

수록 1,540척 · IMO 번호 보유 1,525척(99%) · 유조선류 805척.
선적국은 파나마·팔라우·쿡제도·코모로·가봉 등 **편의치적에 쏠려 있다** —
그림자 선단의 전형적 서명이다.

⚠ SDN 목록은 수시로 갱신된다. 실제 운영에서는 **거래 시점의 최신 목록**을 조회해야 하며,
본 MVP는 저장소에 동봉한 스냅샷으로 동작한다(기준일 아래 SNAPSHOT_DATE).
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/download/sdn.csv"
VESSEL_CSV = "ofac_제재선박.csv"
SNAPSHOT_DATE = "2026-09-05"

# 원유·석유제품 거래에서 특히 중요한 제재 프로그램
ENERGY_PROGRAMS = {
    "RUSSIA": "러시아 (EO 14024 등) — 원유 가격상한제·그림자 선단",
    "UKRAINE": "우크라이나 관련 (EO 13662)",
    "IRAN": "이란 (EO 13902/13846) — 원유 수출 제재",
    "VENEZUELA": "베네수엘라 (EO 13850) — PdVSA 관련",
    "DPRK": "북한 — 해상 환적(STS) 금지",
    "SDGT": "테러자금 지정",
    "GLOMAG": "글로벌 마그니츠키 (인권)",
}

# 편의치적 — 그림자 선단이 즐겨 쓰는 선적국
FLAG_OF_CONVENIENCE = {
    "Panama", "Liberia", "Marshall Islands", "Cook Islands", "Palau",
    "Comoros", "Gabon", "Cameroon", "Barbados", "Sao Tome and Principe",
    "Tanzania", "Togo", "Sierra Leone", "Guyana", "Eswatini", "San Marino",
}


def _data_path(name: str):
    import pathlib

    return pathlib.Path(__file__).resolve().parent.parent / "data" / name


@lru_cache(maxsize=1)
def load_vessels() -> pd.DataFrame:
    """OFAC 제재 선박 목록 (저장소 동봉 스냅샷)."""
    path = _data_path(VESSEL_CSV)
    if not path.exists():
        return pd.DataFrame(columns=["선박명", "IMO", "제재프로그램", "선종", "선적국", "총톤수"])
    df = pd.read_csv(path, dtype=str).fillna("")
    df["_name_norm"] = df["선박명"].str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    df["_is_tanker"] = df["선종"].str.contains("Tanker|Crude|Oil", case=False, regex=True, na=False)
    return df


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def screen_vessel(query: str) -> dict:
    """선박명 또는 IMO로 제재 목록을 대조한다.

    L/C 개설 심사에서 쓰는 방식 그대로 — 정확 일치 우선, 부분 일치는 '유사' 로 따로 낸다.
    **유사 일치를 무시하면 안 된다.** 그림자 선단은 선박명을 자주 바꾼다.
    """
    df = load_vessels()
    q = str(query).strip()
    if not q or df.empty:
        return {"status": "입력없음", "exact": pd.DataFrame(), "similar": pd.DataFrame(), "query": q}

    if re.fullmatch(r"\d{7}", q):  # IMO
        hit = df[df["IMO"] == q]
        return {
            "status": "제재대상" if len(hit) else "해당없음",
            "match_by": "IMO",
            "exact": hit.drop(columns=["_name_norm", "_is_tanker"], errors="ignore"),
            "similar": pd.DataFrame(),
            "query": q,
        }

    qn = _norm(q)
    exact = df[df["_name_norm"] == qn]
    similar = df[df["_name_norm"].str.contains(qn, na=False) & (df["_name_norm"] != qn)] if len(qn) >= 3 else df.iloc[0:0]
    return {
        "status": "제재대상" if len(exact) else ("유사 일치 — 확인 필요" if len(similar) else "해당없음"),
        "match_by": "선박명",
        "exact": exact.drop(columns=["_name_norm", "_is_tanker"], errors="ignore"),
        "similar": similar.drop(columns=["_name_norm", "_is_tanker"], errors="ignore").head(10),
        "query": q,
    }


def program_summary(tankers_only: bool = True) -> pd.DataFrame:
    """제재 프로그램별 선박 수. 원유 거래에 걸리는 축이 어디인지 보인다."""
    df = load_vessels()
    if df.empty:
        return pd.DataFrame()
    if tankers_only:
        df = df[df["_is_tanker"]]
    rows = []
    for key, label in ENERGY_PROGRAMS.items():
        n = int(df["제재프로그램"].str.contains(key, case=False, na=False).sum())
        if n:
            rows.append({"프로그램": key, "설명": label, "선박 수": n})
    out = pd.DataFrame(rows).sort_values("선박 수", ascending=False)
    return out.reset_index(drop=True)


def flag_risk_profile(tankers_only: bool = True, top: int = 10) -> pd.DataFrame:
    """선적국 분포 — 편의치적 쏠림이 그림자 선단의 서명이다."""
    df = load_vessels()
    if df.empty:
        return pd.DataFrame()
    if tankers_only:
        df = df[df["_is_tanker"]]
    vc = df[df["선적국"] != ""]["선적국"].value_counts().head(top)
    return pd.DataFrame({
        "선적국": vc.index,
        "제재 선박 수": vc.values,
        "편의치적": ["⚠ 예" if f in FLAG_OF_CONVENIENCE else "아니오" for f in vc.index],
    })


def origin_sanctions_note(country: str) -> dict:
    """산지 국가가 제재 축에 걸리는지 — L/C 심사의 1차 관문."""
    df = load_vessels()
    tankers = df[df["_is_tanker"]] if not df.empty else df
    mapping = {
        "러시아": "RUSSIA", "이란": "IRAN", "베네수엘라": "VENEZUELA", "북한": "DPRK",
    }
    key = mapping.get(country)
    if not key:
        return {"sanctioned": False, "country": country,
                "note": "OFAC 에너지 제재 프로그램에 직접 대응하는 산지가 아니다. "
                        "다만 **선박·상대방 단위 제재는 별도**이므로 선박 스크리닝은 그대로 수행해야 한다."}
    n = int(tankers["제재프로그램"].str.contains(key, case=False, na=False).sum()) if len(tankers) else 0
    return {
        "sanctioned": True, "country": country, "program": key, "tanker_count": n,
        "note": f"**{country}**는 OFAC **{key}** 제재 축에 해당한다. 관련 제재 유조선이 **{n}척** 등재돼 있다. "
                "해당 산지 화물은 L/C 개설 전 **선박·선주·용선자 3단 스크리닝**이 필요하다.",
    }


def coverage() -> dict:
    df = load_vessels()
    if df.empty:
        return {"total": 0, "tankers": 0, "with_imo": 0, "date": SNAPSHOT_DATE}
    return {
        "total": len(df),
        "tankers": int(df["_is_tanker"].sum()),
        "with_imo": int((df["IMO"] != "").sum()),
        "date": SNAPSHOT_DATE,
    }

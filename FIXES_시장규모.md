# Geo-Swap — 시장규모·임팩트 패널 추가 지시서 (Cursor용)

> `C:\Users\test\OneDrive\Desktop\GeoSwap`에서 작업. 새 탭/히어로 패널 **"📈 시장규모·임팩트"** 추가.
> 계산은 **이미 검증된 로직**(아래)을 그대로. 새 데이터 다운로드 불필요(기존 `data/국가별_원유수입.csv`만 사용).
> 끝나면 commit + push.

---

## 1. engine.py에 집계 함수 추가 (기존 상수 재사용)

기존 상수 사용: `ROUTE_NM`(Phase E), `COUNTRY_TO_ROUTE`, `CO2_PER_BBL_NM=3e-7`, `FREIGHT_PER_BBL_NM=3.9e-4`, `ETS_EUR`, `EUR_KRW`.
신규 상수(상단, `# 조정가능`):
```python
BASE_ROUTE_NM = 6400          # 안전 인도 기준(중동→한국)
CRUDE_PRICE_USD = 73.0        # 배럴당 기준가(최신 Dubai로 대체 가능)
STRUCTURING_FEE_RATE = 0.005  # 스왑물량 대비 구조화 수수료(가정)
TON_PER_TREE = 0.022          # 나무 1그루 연간 CO2 흡수(톤)
TON_PER_CAR = 4.6             # 승용차 1대 연간 CO2 배출(톤)
```

```python
def market_impact(countries: pd.DataFrame, year: int = 2024,
                  fee_rate: float = STRUCTURING_FEE_RATE,
                  ets_eur: float = ETS_EUR, eur_krw: float = EUR_KRW) -> dict:
    """연간 시장규모·임팩트 집계 (국가별 수입 × 단위경제)."""
    df = countries[countries["연도"] == year]
    total_vol = swap_vol = co2 = freight_usd = carbon_krw = fee_usd = 0.0
    per_country = []
    for _, r in df.iterrows():
        v = int(r["물량_천배럴"]) * 1000
        if v <= 0:
            continue
        total_vol += v
        region = COUNTRY_TO_ROUTE.get(r["국가"])
        dist = ROUTE_NM.get(region, 2500)
        saved = max(dist - BASE_ROUTE_NM, 0)
        c_co2 = saved * v * CO2_PER_BBL_NM
        c_fr = saved * v * FREIGHT_PER_BBL_NM
        c_ck = c_co2 * ets_eur * eur_krw
        if saved > 0:
            swap_vol += v
            fee_usd += v * CRUDE_PRICE_USD * fee_rate
        co2 += c_co2; freight_usd += c_fr; carbon_krw += c_ck
        if saved > 0:
            per_country.append({"국가": r["국가"], "물량_배럴": v, "거리절감_nm": saved,
                                "탄소절감_t": c_co2, "가치_원": c_ck + c_fr*eur_krw})
    freight_krw = freight_usd * eur_krw
    fee_krw = fee_usd * eur_krw
    return {
        "총물량": total_vol, "스왑대상물량": swap_vol,
        "탄소절감_t": co2, "탄소가치_원": carbon_krw,
        "운임절감_원": freight_krw, "수수료_원": fee_krw,
        "사회가치_원": carbon_krw + freight_krw,      # 고객+환경
        "하나수익_원": fee_krw,
        "총시장_원": carbon_krw + freight_krw + fee_krw,
        "per_country": pd.DataFrame(per_country).sort_values("가치_원", ascending=False),
        "나무": co2 / TON_PER_TREE, "승용차": co2 / TON_PER_CAR,
    }
```
**검증 기대값(2024):** 총물량≈10.3억, 스왑대상≈2.6억, 탄소≈26만톤, 탄소가치≈₩306억, 운임≈₩4,894억, 수수료≈₩1,370억, **총시장≈₩6,600억**.

## 2. "📈 시장규모·임팩트" 탭 UI

### 상단 히어로 — 큰 숫자 3개 (st.metric, 강조)
- **연간 시장규모  ₩6,600억**
- **CO₂ 절감  26만 톤**
- **스왑 대상  2.6억 배럴 (도입의 25%)**

### 체감 환산 (눈길 끌기)
- "CO₂ 26만 톤 = 🌳 **나무 1,180만 그루** / 🚗 **승용차 5.6만 대** 1년치"

### 가치 분해 (Win-Win-Win)
- 막대 또는 카드 3개: **정유사 운임절감 ₩4,894억** + **환경 탄소가치 ₩306억** + **하나 신규수익 ₩1,370억**
- 캡션: "고객·지구·하나 3자 모두 이득 — ESG형 미래금융"

### 국가별 기여 Top (수평 막대)
- `per_country` 상위 8개국(미국·브라질·카자흐·멕시코·알제리…) 가치_원 기준.

### 확장 시나리오 한 줄
- "본 추정은 **크루드·한국·1년** 기준. 가스(한국가스공사)·타 수입국·누적 적용 시 **수조 원 규모**로 확대."

### 가정 명시 expander (방어용)
- "거리=sea-distances 근사, 탄소계수=IMO(3e-7 t/배럴·해리), 탄소가격=한국가스공사 EU ETS €81.24, 수수료율 0.5%(가정·조정가능). 모든 계수는 공공데이터·표준 기반의 보수적 추정."

## 3. 완료 기준
- "📈 시장규모·임팩트" 탭에서 총시장 ≈ **₩6,600억**, 탄소 ≈ **26만톤**, 체감단위(나무/승용차), 가치 3분해, 국가별 Top 표시.
- 슬라이더(옵션): 수수료율·탄소가격 조정 시 즉시 반영.
- commit + push.

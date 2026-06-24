# Geo-Swap v1.3 수정 지시서 — 탄소·운임 절감(ESG) 레이어 (Codex/Cursor용)

> v1.2까지 완료된 상태에서, "스왑으로 운송거리를 줄여 탄소·운임을 절감한다"는 ESG 가치를 **계산·시각화**하는 레이어를 추가한다.
> 이 레이어는 **데이터 다운로드 없이** 표준 상수 + 계산으로 구현한다(거리·탄소계수·탄소가격은 아래 상수 사용, 모두 조정 가능 + 출처 표기).
> 작업 후 `git add -A && git commit -m "v1.3: 탄소·운임 절감 ESG 레이어"` → push.

---

## 1. `engine.py` — 거리/탄소/운임 상수 + 계산 함수 추가

```python
# ── 항로 거리: 산지 → 한국(울산), 편도 해리(nm). sea-distances.org 기반 근사치(조정 가능). ──
ROUTE_DISTANCE_NM = {
    "중동":       6400,   # 사우디 라스타누라/UAE/쿠웨이트/카타르/이라크/오만
    "카자흐스탄":  11500,  # 흑해 노보로시스크 → 수에즈 → 한국
    "러시아":      8500,   # (Urals 발틱 기준 근사; 동시베리아 ESPO는 훨씬 짧음)
    "미국":        9500,   # 미걸프 → 파나마 → 한국
    "서아프리카":  10500,  # 나이지리아/앙골라/적도기니/가봉/콩고
    "베네수엘라":  10000,
    "멕시코":      8500,
    "브라질":      11000,
    "유럽":        11000,  # 노르웨이/영국
    "아시아":      2500,   # 호주/동남아 등 근거리
}

# 국가 → 거리 키 매핑(없으면 대륙/지역으로 fallback)
COUNTRY_TO_ROUTE = {
    "사우디아라비아":"중동","아랍에미리트":"중동","쿠웨이트":"중동","이라크":"중동",
    "카타르":"중동","오만":"중동","중립지대":"중동",
    "카자흐스탄":"카자흐스탄","러시아":"러시아","미국":"미국","캐나다":"미국",
    "멕시코":"멕시코","브라질":"브라질","베네수엘라":"베네수엘라","콜롬비아":"베네수엘라",
    "에콰도르":"베네수엘라",
    "나이지리아":"서아프리카","앙골라":"서아프리카","적도기니":"서아프리카",
    "가봉":"서아프리카","콩고":"서아프리카","알제리":"서아프리카","카메룬":"서아프리카",
    "노르웨이":"유럽","영국":"유럽",
}
def route_distance(country: str) -> float:
    key = COUNTRY_TO_ROUTE.get(country)
    return ROUTE_DISTANCE_NM.get(key, ROUTE_DISTANCE_NM.get("아시아", 2500))

# ── 탄소·운임 계수(조정 가능) ──
CO2_PER_BBL_NM   = 0.0003      # ton CO2 / (배럴·해리). VLCC 벙커유 소비 기반 IMO 근사(≈0.3 gCO2/배럴·해리)
FREIGHT_PER_BBL_NM = 3.9e-4    # USD / (배럴·해리). 중동→한국 ≈ $2.5/배럴 수준에 맞춘 근사
CARBON_PRICE_KRW = 9000        # 원/ton, 한국 배출권(KAU) 근사. UI에서 입력 조정.

def voyage_metrics(country_from: str, country_to: str, volume_bbl: float, carbon_price_krw: float = CARBON_PRICE_KRW):
    """위험산지(from) 직도입 대신 안전산지(to)와 스왑 시 절감 효과."""
    d_from = route_distance(country_from)
    d_to   = route_distance(country_to)
    d_saved = max(d_from - d_to, 0.0)
    co2_saved_ton   = d_saved * volume_bbl * CO2_PER_BBL_NM
    freight_saved_usd = d_saved * volume_bbl * FREIGHT_PER_BBL_NM
    carbon_value_krw  = co2_saved_ton * carbon_price_krw
    return {
        "distance_from_nm": d_from, "distance_to_nm": d_to, "distance_saved_nm": d_saved,
        "co2_saved_ton": co2_saved_ton,
        "freight_saved_usd": freight_saved_usd,
        "carbon_value_krw": carbon_value_krw,
    }
```

---

## 2. 새 탭 추가 — "🌱 탄소·운임 절감 (ESG)"

탭 목록 끝에 추가. 구성:
1. **산지 선택 2개**: 위험산지 A(기본 카자흐스탄) / 안전산지 B(기본 사우디아라비아). (탭4와 같은 국가 리스트 재사용)
2. **거래량 입력**: `st.number_input("거래량(배럴)", 1000, 2_000_000, 1_000_000, step=100_000)` (기본 100만 배럴 = VLCC 절반급).
3. **탄소가격 입력**: `st.number_input("탄소배출권 가격(원/톤)", value=9000)`.
4. `voyage_metrics(...)` 호출 후 **st.metric 4개** 큰 숫자로:
   - 운송거리 절감 (해리): `{distance_saved_nm:,.0f} nm` (예: 5,100 nm)
   - 탄소 절감량 (톤 CO₂): `{co2_saved_ton:,.0f} t`
   - 탄소배출권 가치 (원): `₩{carbon_value_krw:,.0f}`
   - 운임 절감액 (USD): `${freight_saved_usd:,.0f}`
5. **경로 비교 막대그래프**: A 직도입 거리 vs B 스왑 거리 (해리) — 빨강 vs 초록.
6. 하단 expander("계산 근거·가정"):
   - "항로 거리는 sea-distances.org 기반 근사. 탄소계수 0.3 gCO₂/배럴·해리는 IMO VLCC 벙커유 소비 기준 추정. 탄소가격은 한국 배출권(KAU) 시세 근사이며 입력으로 조정 가능. 실제 운임(Worldscale)·CII 실측으로 대체 가능."

---

## 3. (선택) 탭4 계산기에 한 줄 연계
탭4 석유 환율 결과 아래에 한 줄 추가:
> "이 스왑은 운송거리 약 {d_saved:,.0f}해리를 줄여 탄소 {co2:,.0f}톤을 절감합니다 → 자세히는 'ESG' 탭"

---

## 4. 출처 푸터에 한 줄 보강
```
... · 운송거리(sea-distances 근사)·탄소계수(IMO)·탄소가격(KAU) 기반 ESG 추정
```

---

## 완료 기준
1. 새 "탄소·운임 절감(ESG)" 탭에서 카자흐→사우디, 100만 배럴 기본값 시:
   - 거리절감 ≈ **5,100 해리**, CO₂ 절감 ≈ **1,530 톤**, 탄소가치 ≈ **₩1,377만**, 운임절감 ≈ **$199만** (대략 이 규모면 정상).
2. 거래량/탄소가격 입력 바꾸면 숫자 즉시 반영.
3. 경로 비교 막대그래프 표시 + 계산근거 expander.
4. `streamlit run app.py` 정상 + commit/push.
```
```

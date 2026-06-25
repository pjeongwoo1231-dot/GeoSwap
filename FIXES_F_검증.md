# Geo-Swap Phase F — 모델 검증 위젯 지시서 (Cursor용)

> 목적: 우리 다요인 모델이 산출한 도입가가 **페트로넷 실제 공공데이터(FOB/CIF)와 일치**함을 보여 "검증된 모델" 확보 → 심사 구체성·문제해결 점수.
> 검증 결과(이미 계산됨): 모델 $73.90 vs 페트로넷 **FOB $72.71(+1.6%)** / CIF $76.76(−3.7%). FOB와 1.6% 일치, CIF와의 차이는 운임(ESG 탭과 정합).
> `C:\Users\test\OneDrive\Desktop\GeoSwap`에서 작업. 끝나면 commit + push. 새 데이터 불필요.

---

## 1. engine.py — 검증 함수 + 상수
```python
# 페트로넷 실제 원유 도입단가 (2025년 1~4월 평균, $/배럴). 출처: 페트로넷 원유도입 통계.
PETRONET_FOB_REF = 72.71
PETRONET_CIF_REF = 76.76
PETRONET_REF_PERIOD = "2025년 1~4월"

def model_validation(countries, prices, ref_year=2025, ref_months=(1, 2, 3, 4), vol_year=2024):
    """모델 산출 수입량 가중평균 도입가 vs 페트로넷 실제 FOB/CIF."""
    q = prices[(prices["연도"] == ref_year) & (prices["월"].isin(ref_months))]
    p_ref = float(q["Dubai"].mean())
    vol = countries[countries["연도"] == vol_year]
    tot = ws = 0.0
    for _, r in vol.iterrows():
        v = int(r["물량_천배럴"])
        if v <= 0:
            continue
        ws += p_ref * quality_adj(r["국가"]) * (1 - geo_discount(r["국가"])) * v
        tot += v
    model_price = ws / tot if tot else 0.0
    return {
        "model_price": model_price,
        "fob_ref": PETRONET_FOB_REF,
        "cif_ref": PETRONET_CIF_REF,
        "fob_err_pct": (model_price - PETRONET_FOB_REF) / PETRONET_FOB_REF * 100,
        "cif_err_pct": (model_price - PETRONET_CIF_REF) / PETRONET_CIF_REF * 100,
        "period": PETRONET_REF_PERIOD,
    }
```

## 2. UI — "✅ 모델 검증" 섹션 (시장규모·임팩트 탭 하단 또는 별도 expander)
```python
v = model_validation(countries, prices)
st.subheader("✅ 모델 검증 — 공공데이터 대조")
c1, c2, c3 = st.columns(3)
c1.metric("모델 추정 도입가", f"${v['model_price']:.2f}")
c2.metric(f"페트로넷 실제 FOB", f"${v['fob_ref']:.2f}", f"오차 {v['fob_err_pct']:+.1f}%")
c3.metric(f"페트로넷 실제 CIF", f"${v['cif_ref']:.2f}", f"오차 {v['cif_err_pct']:+.1f}%")
```
- **막대그래프**: 모델 / FOB / CIF 3개 비교 ($/배럴).
- **설명 캡션**:
  > "본 모델이 산출한 수입량 가중평균 도입가가 페트로넷 실제 **FOB와 1.6% 이내로 일치** → 공공데이터로 모델 타당성 검증. CIF와의 차이(약 3.7%)는 **운임 성분**으로, 이는 ESG 탭의 운임 절감 모델과 정합한다. (기준: {period}, 도입가는 운임 미포함 spot 기준)"

## 3. 완료 기준
1. "✅ 모델 검증" 섹션에 모델가 ≈ **$73.90**, FOB 오차 **+1.6%**, CIF 오차 **−3.7%** 표시 + 막대 비교 + 설명.
2. commit + push + 배포 확인.

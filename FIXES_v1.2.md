# Geo-Swap v1.2 수정 지시서 — K-SURE 국가위험도 연동 (Codex/Cursor용)

> v1.1까지 완료된 상태에서, 지정학 할인율의 근거를 "가정값" → **한국무역보험공사(K-SURE) 공인 국가등급**으로 교체한다.
> 작업 후 `git add -A && git commit -m "v1.2: K-SURE 국가등급 기반 지정학 할인 + 지정학탭 실데이터화"`.

---

## 새 데이터 파일 (이미 `data/`에 있음, UTF-8)

### `data/ksure_국가등급.csv`
- 컬럼: `국가명, 국가등급, 평가일자`
- 국가등급 = **1(최안전) ~ 7(최고위험)** 정수. 306개국. (출처: 한국무역보험공사)
- ⚠️ 국가명 표기가 수입데이터와 다를 수 있음: 예) 수입데이터 `아랍에미리트` ↔ K-SURE `아랍에미리트 연합`. 매칭은 **부분일치(둘 중 하나가 다른 쪽을 포함)** + 아래 ALIAS로 처리.

### `data/ksure_원유광업_위험지수.csv`
- 컬럼: `국가명, 원유광업_위험지수, 기준년월`
- "석탄·원유 및 천연가스 광업" 업종 위험지수. **단 7개국만 존재(희소)** → 메인 산식엔 쓰지 말고 **지정학 탭에 참고 표시만**.

---

## 수정 1. `engine.py` — 등급 기반 할인율로 교체

### 1-1. 등급→할인율 매핑 (기존 GEO_DISCOUNT 하드코딩 대체)
```python
import pandas as pd

# K-SURE 국가등급(1~7) → 지정학 할인율. 고위험일수록 가속(convex).
GRADE_TO_DISCOUNT = {1: 0.00, 2: 0.02, 3: 0.04, 4: 0.06, 5: 0.09, 6: 0.14, 7: 0.22}

# 수입데이터 국가명 → K-SURE 국가명 보정
COUNTRY_ALIAS = {
    "아랍에미리트": "아랍에미리트 연합",
    "중립지대": None,   # K-SURE에 없음 → 할인 0 처리
}

_ksure = pd.read_csv("data/ksure_국가등급.csv")  # 국가명,국가등급,평가일자

def country_grade(country: str):
    """수입데이터 국가명 → K-SURE 등급(int) 또는 None"""
    name = COUNTRY_ALIAS.get(country, country)
    if name is None:
        return None
    # 정확일치 우선, 없으면 부분일치
    exact = _ksure[_ksure["국가명"] == name]
    if len(exact):
        return int(exact.iloc[0]["국가등급"])
    part = _ksure[_ksure["국가명"].str.contains(name) | _ksure["국가명"].apply(lambda x: x in name)]
    return int(part.iloc[0]["국가등급"]) if len(part) else None

def geo_discount(country: str) -> float:
    """K-SURE 등급 기반 지정학 할인율. 등급 없으면 0."""
    g = country_grade(country)
    return GRADE_TO_DISCOUNT.get(g, 0.0)
```
- 기존 `GEO_DISCOUNT` dict 참조를 전부 `geo_discount(country)` 호출로 교체.
- `effective_price`, `swap_rate` 로직은 그대로 (할인 소스만 등급 기반으로 바뀜).

### 1-2. 검증 기대값 (등급 기반 적용 후)
- 카자흐스탄(등급5) → 9% 할인. 카자흐(Brent)→사우디(Dubai) ≈ **0.91** 근처.
- 러시아/이라크/베네수엘라(등급7) → 22%.
- 미국/캐나다/노르웨이(등급1) → 0%.

---

## 수정 2. 탭4 계산기 — 할인 근거를 K-SURE로 표기

1. 슬라이더 기본값 = `geo_discount(선택국)` (등급에서 자동 산출된 값).
2. 계산 근거 caption에 등급 명시:
   ```
   카자흐스탄: K-SURE 국가등급 5 → 지정학 할인 9%
   Brent $73.1 × (1−9%) ÷ Dubai $73.2 × (1−0%) = 0.91
   ```
3. expander("지정학 할인율 산출 근거") 내용 교체:
   - "할인율은 한국무역보험공사(K-SURE) 국가신용등급(1~7)에 기반함. 등급별 할인: 1→0%, 2→2%, 3→4%, 4→6%, 5→9%, 6→14%, 7→22%. 슬라이더로 시나리오 조정 가능."

---

## 수정 3. 탭5 지정학 리스크 — 임시 지표를 실데이터로 교체

기존 "수입량 변동계수(임시 리스크)" 차트를 **K-SURE 국가등급 실데이터**로 교체:
1. **국가별 K-SURE 등급 막대그래프** — 우리 수입국들만, 등급 높을수록(위험) 빨강 그라데이션. 러시아·이라크·베네수엘라(7)가 최상단.
2. **등급→할인율 매핑 표** 표시(수정2의 표).
3. 하단에 `원유광업_위험지수.csv` 참고 표 (있는 7개국만): "K-SURE는 원유광업 업종 특화 위험지수도 제공 — 향후 업종 특화 모델로 확장 가능".
4. 상단 placeholder 문구("K-SURE 연동 예정") → **"K-SURE 국가위험도 연동 완료"**로 교체.

---

## 수정 4. 출처 푸터에 K-SURE 추가
```
데이터 출처 · 한국석유공사[KOSIS TX_31801_A008] · 국제유가[페트로넷] ·
한국무역보험공사 국가신용등급·원유광업 위험지수(지정학 할인 근거)
```

---

## 완료 기준
1. 탭4: 카자흐→사우디 ≈ **0.91**, 슬라이더 기본값이 등급 기반(9%), caption에 "K-SURE 국가등급 5" 표시.
2. 탭5: 임시 변동계수 → **K-SURE 등급 막대그래프**로 교체, 러시아·이라크·베네수엘라가 최고위험.
3. 출처 푸터에 한국무역보험공사 명시.
4. `streamlit run app.py` 정상 + git commit.
```
```

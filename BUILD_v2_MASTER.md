# Hana Geo-Swap v2.0 — 마스터 빌드 브리프 (Cursor/Codex용)

> v1.2까지 배포 완료된 상태(석유공사 데이터 + K-SURE 지정학 할인 + Streamlit 배포).
> 이번엔 **다요인 석유 환율 모델 + 품질/동적지정학/ESG/검증**을 추가한다.
> ⚠️ 데이터 구조는 아래 사전을 **그대로** 따를 것(추측 금지). 작업은 **Phase 단위로** 하고 **각 Phase 끝나면 commit + push**. 라이브 배포가 깨지지 않게 항상 CSV 폴백 유지.

---

## 0. 데이터 사전 (`data/`, 전부 UTF-8) — 파싱 주의점 필독

| 파일 | 단위/주기 | 구조 & 파싱 |
|---|---|---|
| `국가별_원유수입.csv` | 천배럴 · **연도별 2020~2024** | 계층형. col0=대륙("코드 이름"), col1=국가 or "소계". 국가행= col1≠"소계". 국가명=`col1.split(" ",1)[1]`, 대륙명=`col0.split(" ",1)[1]`. 연도열 `Y2020 2020`→2020. 빈칸=0 |
| `유질별_원유수입.csv` | 천배럴 | 행: 합계/경질유/중(中)질유/중(重)질유. 연열 2020~2023 직접, **2024 = 2024.01~2024.12 합산**. 매핑 경질=light/중(中)=medium/중(重)=heavy |
| `국제유가.csv` | $/배럴 · 월별 | 열: 월,유종(빈칸),Dubai,Brent,WTI,Oman. `월`은 1월에만 "20년 01월" 연prefix → **연도 forward-fill**, "20년"=2020 |
| `ksure_국가등급.csv` | 등급 1~7 | 열: 국가명,국가등급,평가일자. 1=최안전,7=최고위험. 국가명 부분일치(아랍에미리트↔아랍에미리트 연합) |
| `원유품질_API황.csv` | API·황% | 열: 국가명,API_비중,황함량_pct,표본물량,출처. 17개국 |
| `gas_EU_ETS_탄소가격.csv` | €/톤 · 연도별 | 열: 연도,최저(Euro),최대(Euro),**연평균(Euro)**. 2008~2022. 최신 2022 연평균 ≈ **81.24** |
| `gpr_oil_region_monthly.csv` | 지수 · 월별 2020~2024 | 열: Date, GPR_OIL, GPR_OIL_MiddleEast/Russia/USA/Venezuela/Africa/Americas/Asia/NorthSea |
| `ksure_원유광업_위험지수.csv` | 지수 | 7개국만(참고용). 지정학 탭에 곁들임만 |

---

## 1. 다요인 석유 환율 모델 (`engine.py` 핵심)

### 1-1. 산식
```
P_eff(c, t) = P_ref(t) × quality_adj(c) × (1 − geo_discount(c, t))
SwapRate(A→B, t) = P_eff(A, t) / P_eff(B, t)
```
- `P_ref(t)` = **Dubai 월별 가격**(중동 인도 기준).
- 결과 의미: "A 원유 1배럴 = B 원유 몇 배럴" (품질·지정학 반영).

### 1-2. 품질 보정 (EIA API/황, 정적)
```python
Q_API, Q_S = 0.007, 0.02          # API 1도당 +0.7%, 황 1%당 −2% (업계 통상 룰, 조정가능)
API_REF, S_REF = 31.0, 2.0        # Dubai 기준 품질
def quality_adj(c):               # 원유품질_API황.csv 사용
    return 1 + Q_API*(API[c]-API_REF) - Q_S*(S[c]-S_REF)
```
- 예: 카자흐(API45.9,황0.85) → ≈ +12.7% 프리미엄 / 베네수(API13.9,황3.6) → ≈ −15%.

### 1-3. 지정학 할인 (K-SURE 정적 + GPR 동적)
```python
GRADE_TO_DISCOUNT = {1:0,2:.02,3:.04,4:.06,5:.09,6:.14,7:.22}   # K-SURE 등급→기본할인
ALPHA = 0.5                                                      # GPR 동적 가중(조정가능)

# 국가 → GPR_OIL 지역 컬럼 매핑
GPR_REGION = {
  "사우디아라비아":"MiddleEast","아랍에미리트":"MiddleEast","쿠웨이트":"MiddleEast",
  "이라크":"MiddleEast","카타르":"MiddleEast","오만":"MiddleEast","중립지대":"MiddleEast",
  "러시아":"Russia",
  "카자흐스탄":"Russia",     # CPC 파이프라인 러시아 영토 경유 의존 → Russia 리스크 연동(의도적·방어가능)
  "베네수엘라":"Venezuela","에콰도르":"Americas","콜롬비아":"Americas",
  "미국":"Americas","캐나다":"Americas","멕시코":"Americas","브라질":"Americas",
  "나이지리아":"Africa","앙골라":"Africa","가봉":"Africa","콩고":"Africa","적도기니":"Africa","알제리":"Africa","카메룬":"Africa",
  "노르웨이":"NorthSea","영국":"NorthSea",
}
# gpr_stress(region,t): 해당 지역 GPR을 자기 분포로 정규화 → median에서 0, p90에서 1, [0,2] clip
def geo_discount(c, t):
    base = GRADE_TO_DISCOUNT[grade(c)]
    region = GPR_REGION.get(c)
    stress = gpr_stress(region, t) if region else 0     # GPR 없으면 정적만
    return base * (1 + ALPHA*stress)
```
- 효과: 평시엔 K-SURE 기본할인, **GPR 폭발(러 2022.03)** 시 그 달 할인이 1.5~2배로 벌어짐 → 스왑환율이 사건에 반응.

> ⚠️ 전부 모듈 상단 상수로. 계수엔 `# 조정가능` 주석. 데이터 로딩은 `@st.cache_data` + `Path(__file__)` 절대경로(클라우드 폴백).

---

## 2. 빌드 Phase (각 Phase 후 commit + push, 배포 확인)

### Phase A — 로더
`loaders.py`에 신규 5개 csv 로딩 함수 추가(품질/EUETS/GPR/K-SURE등급/원유광업). 절대경로 + 캐시.

### Phase B — 다요인 엔진
위 1번 산식 구현. 기존 단순 할인 로직을 `quality_adj × (1−geo_discount)` 구조로 교체. 검증값:
- 카자흐→사우디 (2022-03, GPR 폭발월): 정적보다 **할인 더 커짐** 확인.
- 평시월: 기존과 비슷.

### Phase C — 석유 환율 계산기 업그레이드 (탭4)
- **월 선택 슬라이더**(2020-01~2024-12) 추가.
- 결과 아래 **분해 표시**:
  ```
  P_ref(Dubai) $X
  × 품질보정 1.127 (API45.9·황0.85)
  × (1 − 지정학할인 13.5% = K-SURE5등급 9% × GPR가중 1.5)
  = 유효가격 $Y  →  스왑비율 0.9X
  ```
- 기존 수동 할인 슬라이더는 "시나리오 조정"으로 유지.

### Phase D — 킬러 차트 2개 (신규 탭 "🔍 심층분석")
1. **GPR ↔ 수입 상관**: 이중축 라인 — 좌축 `GPR_OIL_Russia`(월별), 우축 한국 러시아 원유 수입량(연별). 2022-03 GPR=720 스파이크 + 러시아 수입 절벽 동시 표시 + 주석 "독립된 두 공공데이터가 같은 사건을 증명".
2. **품질-지정학 사분면**: 산점도 x=API(품질), y=K-SURE등급(리스크), 버블크기=수입량. **카자흐(고품질+고리스크) 강조** + 주석 "고품질인데 지정학으로 저평가 = 스왑 차익 기회".

### Phase E — 화물·탄소발자국 (ESG) 탭 "🌱 ESG 절감"
```python
ROUTE_NM = {"중동":6400,"카자흐스탄":11500,"러시아":8500,"미국":9500,"서아프리카":10500,
            "베네수엘라":10000,"멕시코":8500,"브라질":11000,"유럽":11000,"아시아":2500}
CO2_PER_BBL_NM = 0.0003     # ton CO2/배럴·해리 (IMO VLCC 근사, 조정가능)
FREIGHT_PER_BBL_NM = 3.9e-4 # $/배럴·해리 (조정가능)
ETS_EUR = 81.24             # gas_EU_ETS_탄소가격.csv 최신 연평균(€/톤)
EUR_KRW = 1450              # 환율(입력 조정)
```
UI: 위험산지 A / 안전산지 B / 거래량(배럴) / 탄소가격(€, 기본 EU ETS) 입력 →
- **st.metric 4개**: 운송거리 절감(해리), **탄소발자국 절감(톤 CO₂)**, 탄소가치(₩=톤×€×환율), 운임 절감($)
- **탄소발자국 비교 막대**: 직도입 경로 vs 스왑 경로 (톤 CO₂, 빨강 vs 초록)
- expander: "거리=sea-distances 근사, 탄소계수=IMO, 탄소가격=한국가스공사 제공 EU ETS"

### Phase F — 모델 검증 위젯 (탭1 하단 or 별도)
우리 모델의 **수입량 가중평균 유효가격**을 계산 → 페트로넷 실제 **CIF 평균단가(≈76.76, 2025)**와 나란히 표시. "공공데이터로 모델 검증" 캡션.

### Phase G — 최신 자동갱신 (맨 마지막, 폴백 필수)
- KOSIS OpenAPI(인증키는 `.streamlit/secrets.toml`, **깃 커밋 금지**)로 수입/유가 월별 최신화.
- **try/except로 실패 시 번들 CSV 폴백** → API 죽어도 앱 안 죽음.
- 화면에 "데이터 최신 갱신: YYYY-MM" 뱃지.
- (옵션) 일별 유가는 EIA API `RWTC`/`RBRTE`. 없어도 됨.

---

## 3. 출처 푸터 (전 페이지 하단)
```
데이터: 산업통상부 — 한국석유공사(국가별·유질별 원유수입·국제유가) · 한국무역보험공사(국가신용등급) ·
한국가스공사(EU ETS 탄소가격) | 연계: EIA(원유품질 API·황), GPR 지정학지수 | 모델 검증: 페트로넷 CIF 도입단가
```

## 4. 완료 기준
- 계산기에 다요인 분해 표시 + 월 선택.
- 심층분석 탭에 GPR↔수입 상관 + 품질-지정학 사분면.
- ESG 탭에 탄소발자국·운임 절감(EU ETS 가치).
- 검증 위젯(모델가 vs CIF).
- 전부 commit/push + 배포 URL 정상.

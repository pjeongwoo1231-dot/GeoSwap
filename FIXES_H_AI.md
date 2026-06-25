# Geo-Swap Phase H — AI 연계 (Claude API) 지시서 (Cursor용)

> 목적: 공모 주제 **"AI 데이터로 도약"** 정합 + 심사 가산점 **"AI 활용 확산성(+5): AI 연계 구조(API·에이전트)"** 확보.
> 핵심 셀링: 우리 지정학지수가 이미 **AI-GPR(LLM 생성 데이터)** → 여기에 **Claude API 분석 레이어**를 얹어 "AI 데이터 + AI 분석" 이중 충족.
> `C:\Users\test\OneDrive\Desktop\GeoSwap`에서 작업. 끝나면 commit + push.
> ⚠️ **API 키 없이도 앱이 안 깨지게** graceful fallback 필수(배포 보호). 키는 절대 커밋 금지.

---

## H-1. LLM 지정학 브리핑 (핵심 — 반드시)

### 0) 의존성·키
- `requirements.txt`에 `anthropic` 추가.
- 키 저장: `.streamlit/secrets.toml` (이미 .gitignore됨):
  ```toml
  ANTHROPIC_API_KEY = "sk-ant-..."
  ```
- Streamlit Cloud 배포: App → **Settings → Secrets**에 같은 줄 붙여넣기.

### 1) `src/ai_brief.py` 신규 (정확한 SDK 문법 — 추측 금지, 아래 그대로)
```python
import anthropic
import streamlit as st

MODEL = "claude-opus-4-8"   # 기본 최상급. 호출 잦아 비용 줄이려면 "claude-haiku-4-5"로 교체 가능(사용자 선택)

def _client():
    key = st.secrets.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key) if key else None

SYSTEM = (
    "당신은 에너지 안보·지정학 리스크를 다루는 금융 애널리스트입니다. "
    "주어진 공공데이터 지표(한국석유공사 원유수입, 한국무역보험공사 국가신용등급, "
    "LLM이 생성한 지정학지수 AI-GPR, 한국가스공사 EU ETS 탄소가격)만을 근거로, "
    "정유사·금융기관 의사결정자를 위한 간결하고 단정한 한국어 브리핑을 작성하세요. "
    "추측·과장 금지, 숫자에 근거할 것."
)

@st.cache_data(show_spinner=False)
def generate_briefing(country_a, country_b, month, grade_a, api_a, sulfur_a,
                      gpr_stress, geo_discount_a, swap_rate, volume, co2, freight):
    """현재 엔진 상태를 받아 Claude가 지정학 브리핑 생성. (입력 동일하면 캐시→재과금 방지)"""
    client = _client()
    if client is None:
        return None  # 키 없음 → UI에서 안내
    user = f"""다음은 Geo-Swap 플랫폼의 현재 분석 상태입니다.
- 위험 산지(A): {country_a} (K-SURE 등급 {grade_a}/7, 품질 API {api_a}/황 {sulfur_a}%)
- 안전 산지(B): {country_b}
- 기준 시점: {month}
- AI-GPR 지정학 스트레스(A 지역): {gpr_stress:.2f} (0=평시, 1=p90, 2=극단)
- 지정학 할인율(A): {geo_discount_a:.1%}
- 석유 환율(스왑비율 A→B): {swap_rate:.4f} → A 1배럴 = B {swap_rate:.3f}배럴
- 스왑 ESG 효과(거래량 {volume:,}배럴): 탄소 {co2:,.0f}톤 절감, 운임 ${freight:,.0f} 절감

아래 3가지를 각각 2~3문장으로, 소제목 달아 작성:
1) **현황 진단** — 지정학 리스크와 가격(품질-할인) 괴리
2) **스왑 추천** — 방향과 정량 근거(배럴 환산·차익)
3) **핵심 리스크 1가지**"""
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")
```

### 2) 계산기 탭(탭4)에 버튼 추가
선택된 A/B·월·스왑비율·할인·ESG 값을 그대로 넘겨 호출:
```python
from src.ai_brief import generate_briefing

st.divider()
st.subheader("🤖 AI 지정학 브리핑")
st.caption("Claude(claude-opus-4-8)가 공공데이터 지표를 해석해 스왑 추천을 생성합니다. "
           "지정학지수는 LLM 생성 데이터(AI-GPR) 기반.")
if st.button("브리핑 생성"):
    with st.spinner("Claude가 지정학 리스크를 분석 중…"):
        text = generate_briefing(country_a, country_b, month, grade_a, api_a, sulfur_a,
                                  gpr_stress, geo_discount_a, swap_rate, volume_bbl, co2_saved, freight_saved)
    if text is None:
        st.info("AI 브리핑을 쓰려면 Streamlit Secrets에 ANTHROPIC_API_KEY를 설정하세요. "
                "(설정 전에도 나머지 기능은 정상 작동)")
    else:
        st.markdown(text)
```
> 위에서 필요한 값(grade_a, api_a, gpr_stress 등)은 engine 함수에서 이미 산출됨 — 재사용해서 넘길 것.

### 3) 안전장치
- 키 없으면 `generate_briefing`이 `None` 반환 → 안내 메시지만, **앱 안 죽음.**
- `try/except anthropic.APIError`로 감싸 네트워크/한도 오류 시 친절 메시지.

---

## H-2. (가산점 강화·선택) 엔진을 "AI 에이전트 도구"로 노출

심사기준이 **"AI 연계 구조(API·에이전트)"**를 명시 → 우리 석유환율 엔진을 **AI가 호출 가능한 도구**로 제공.

- **간단 버전(권장):** `src/engine.py`의 `country_swap_rate`·`market_impact`를 감싼 **함수형 도구 스키마**를 정의하고, Claude **tool use**로 "AI 에이전트가 우리 엔진을 호출해 스왑비율을 계산"하는 데모 1개. (anthropic tool use — 필요시 Cursor가 `shared/tool-use` 문서 참조)
- **최소 버전:** 별도 `api.py`(FastAPI) 또는 함수 노출 + 기획서에 "MCP/에이전트 연계 가능 구조" 명시.
- 시간 부족하면 H-2는 **기획서 서술 + H-1 데모로 충분**. 무리하지 말 것.

---

## 완료 기준 (H-1)
1. 계산기 탭 "🤖 AI 지정학 브리핑" 버튼 → 클릭 시 Claude가 **현황진단/스왑추천/리스크** 3단 브리핑 생성·표시.
2. 키 미설정 시 안내만 뜨고 **앱 정상**(배포 안 깨짐).
3. `requirements.txt`에 anthropic 추가, 키는 **커밋 안 됨**.
4. commit + push + 배포 확인.

from google import genai
from google.genai import types
import streamlit as st

MODEL = "gemini-2.5-flash"  # 안정 generate_content API. 미지원 시 "gemini-2.0-flash"로 교체


def _client():
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None
    return genai.Client(api_key=key) if key else None


SYSTEM = (
    "당신은 은행 기업금융 부문의 원유 조달 리스크 애널리스트입니다. "
    "주어진 공공데이터 지표(한국석유공사 원유수입, 한국무역보험공사 국가신용등급, "
    "LLM이 생성한 지정학지수 AI-GPR, 한국가스공사 EU ETS 탄소가격)만을 근거로, "
    "정유사·금융기관 의사결정자를 위한 간결하고 단정한 한국어 브리핑을 작성하세요. "
    "추측·과장 금지, 숫자에 근거할 것. "
    "특히 다음 세 서사는 문헌상 반박됐거나 미해결이므로 절대 쓰지 마세요: "
    "①'유가↑→금리↑→침체'(Kilian·Lewis 2011과 BGW 1997이 정면 대립하는 미해결 논쟁) "
    "②'유가 상승→물가 위기'(Choi 외 2018: +10%→+0.4%p, 2년 내 소멸, 한국은 기대가 앵커됨) "
    "③'에너지 집약 산업이 먼저 다친다'(Bohi 1991: 에너지집약도와 산출 감소에 일관된 관계 없음). "
    "그리고 지정학 사건을 '예측'했다고 쓰지 마세요 — 이 엔진은 대응·가격발견 도구입니다."
)


@st.cache_data(show_spinner=False)
def generate_briefing(
    country_a,
    country_b,
    month,
    grade_a,
    api_a,
    sulfur_a,
    gpr_stress,
    geo_discount_a,
    swap_rate,
    volume,
    co2,
    freight,
    shock_label="판정 없음",
    shock_confidence="-",
    shock_innovation=None,
    dispersion_z=None,
    scarcity_prem_b=0.0,
    band_low=None,
    band_high=None,
    inventory_dir="관측없음",
    inventory_mom=None,
):
    """현재 엔진 상태 → Gemini 지정학 브리핑. 입력 동일하면 캐시(재과금 방지)."""
    client = _client()
    if client is None:
        return None  # 키 없음 → UI에서 안내
    quality_str = (
        f"품질 API {api_a}/황 {sulfur_a}%"
        if api_a and float(api_a) > 0
        else "품질 데이터 미보유(중립 처리)"
    )
    innov_str = "관측없음" if shock_innovation is None else f"{shock_innovation:+.2f}"
    disp_str = "-" if dispersion_z is None else f"{dispersion_z:+.1f}σ"
    band_str = "-" if band_low is None else f"{band_low:.3f} ~ {band_high:.3f}"
    inv_mom_str = "" if inventory_mom is None else f" (전월비 {inventory_mom:+.1f}%)"
    prompt = f"""다음은 Geo-Swap 플랫폼의 현재 분석 상태입니다.

[국면 판정 — 가장 먼저 읽을 것]
- 충격 유형: {shock_label} (신뢰도 {shock_confidence})
- 지정학 혁신 z(AR(5) 잔차): {innov_str}   ← 지수 '수준'이 아니라 '예상 밖의 정도'
- 벤치마크 분기 z(Brent−Dubai): {disp_str}
- 재고 방향: {inventory_dir}{inv_mom_str}   ← Kilian(2009) 식별자. 축적=예비적 수요, 인출=물리적 교란
- 안전 산지(B)에 부과된 희소성 프리미엄: {scarcity_prem_b:.1%}
- 스왑비율 불확실성 밴드: {band_str}

[산지 정보]
- 위험 산지(A): {country_a} (K-SURE 등급 {grade_a}/7, {quality_str})
- 안전 산지(B): {country_b}
- 기준 시점: {month}
- AI-GPR 지정학 스트레스(A 지역): {gpr_stress:.2f} (0=평시, 1=p90, 2=극단)
- 지정학 할인율(A): {geo_discount_a:.1%}
- 석유 환율(스왑비율 A→B): {swap_rate:.4f} → A 1배럴 = B {swap_rate:.3f}배럴
- 스왑 ESG 효과(거래량 {volume:,}배럴): 탄소 {co2:,.0f}톤 절감, 운임 ${freight:,.0f} 절감

[모델 해석] 본 플랫폼은 지정학적으로 저평가된 위험산지(A)의 원유 '권리'를 확보해 안전산지(B) 실물과 스왑함으로써, 운송 리스크를 회피하고 지정학 할인(Basis)을 차익화한다.
- 스왑비율 < 1.0 → A가 B보다 저평가 → A 권리 확보 후 B로 스왑 시 차익 기회(적극 추천).
- 스왑비율 > 1.0 → A가 (품질 등으로) 프리미엄 → 현 시점 직접 차익은 제한적. 다만 A 지역 지정학 리스크 상승(AI-GPR↑) 시 할인이 확대되는 진입 기회를 주목하라.

[국면별 해석 규칙 — 반드시 따를 것]
- **예비적 수요**: 재고가 쌓이면서 가격이 오른 국면. Kilian·Park(2009) 기준 **세 유형 중 자산가격에
  유의한 음(−) 효과를 갖는 유일한 유형**이다. 스왑 유인 최대이며, 하방 리스크도 함께 경고할 것.
- **공급교란**: 재고를 헐어 쓰는 국면. 물리적 차질이다. 스왑 유인이 크나, 자산가격 효과는
  Kilian·Park 기준 유의하지 않았음을 함께 밝힐 것 — 과장 금지.
- **지역 공급·예비적 충격**(재고 미관측으로 미분리): 두 벤치마크가 갈라진 국면. B(안전 산지)에 희소성 프리미엄이 붙어
  스왑비율이 급락한다. **스왑 유인이 최대인 국면**이며, A 권리를 확보해 B 실물로 교환할 실익이 크다.
- **글로벌 총수요**: 두 산지가 함께 오른다 → 교환비율이 거의 안 바뀐다.
  **스왑 유인이 낮다고 명확히 말할 것.** 억지로 추천하지 마세요.
- **판정 보류 / 지정학 데이터 없음**: 프리미엄을 부과하지 않은 상태다.
  Kilian(2008)에 따라 지정학 사건 대부분은 가격으로 전이되지 않는다 — 관망을 권고할 것.
- **평시**: 구조적 신용·인도 할인만 작동한다. 품질 대비 저평가 여부로만 판단할 것.

아래 4가지를 각각 2~3문장으로, 굵은 소제목 달아 작성(스왑 방향은 항상 'A 권리 → B 실물'):
1) **국면 진단** — 위 충격 유형이 왜 그렇게 판정됐는지를 혁신 z와 분기 z로 설명
2) **현황 진단** — A의 신용·인도 할인, 품질, 그로 인한 가격 괴리
3) **스왑 판단** — 위 국면별 규칙에 따라 실행/관망을 명확히. 밴드 폭도 함께 언급
4) **핵심 리스크 1가지**"""
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=1500,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return response.text
    except Exception as e:  # 한도/네트워크/모델 오류 → 앱 안 죽게
        return f"⚠️ AI 브리핑 생성 중 오류: {e}"

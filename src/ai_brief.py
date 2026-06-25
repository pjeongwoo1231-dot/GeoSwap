from google import genai
import streamlit as st

MODEL = "gemini-3.5-flash"  # 무료·빠름. 만약 모델 미지원 오류 시 "gemini-2.5-flash"로 교체


def _client():
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None
    return genai.Client(api_key=key) if key else None


SYSTEM = (
    "당신은 에너지 안보·지정학 리스크를 다루는 금융 애널리스트입니다. "
    "주어진 공공데이터 지표(한국석유공사 원유수입, 한국무역보험공사 국가신용등급, "
    "LLM이 생성한 지정학지수 AI-GPR, 한국가스공사 EU ETS 탄소가격)만을 근거로, "
    "정유사·금융기관 의사결정자를 위한 간결하고 단정한 한국어 브리핑을 작성하세요. "
    "추측·과장 금지, 숫자에 근거할 것."
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
):
    """현재 엔진 상태 → Gemini 지정학 브리핑. 입력 동일하면 캐시(재과금 방지)."""
    client = _client()
    if client is None:
        return None  # 키 없음 → UI에서 안내
    prompt = f"""다음은 Geo-Swap 플랫폼의 현재 분석 상태입니다.
- 위험 산지(A): {country_a} (K-SURE 등급 {grade_a}/7, 품질 API {api_a}/황 {sulfur_a}%)
- 안전 산지(B): {country_b}
- 기준 시점: {month}
- AI-GPR 지정학 스트레스(A 지역): {gpr_stress:.2f} (0=평시, 1=p90, 2=극단)
- 지정학 할인율(A): {geo_discount_a:.1%}
- 석유 환율(스왑비율 A→B): {swap_rate:.4f} → A 1배럴 = B {swap_rate:.3f}배럴
- 스왑 ESG 효과(거래량 {volume:,}배럴): 탄소 {co2:,.0f}톤 절감, 운임 ${freight:,.0f} 절감

아래 3가지를 각각 2~3문장으로, 굵은 소제목 달아 작성:
1) **현황 진단** — 지정학 리스크와 가격(품질-할인) 괴리
2) **스왑 추천** — 방향과 정량 근거(배럴 환산·차익)
3) **핵심 리스크 1가지**"""
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=SYSTEM,
            input=prompt,
        )
        return interaction.output_text
    except Exception as e:  # 한도/네트워크/모델 오류 → 앱 안 죽게
        return f"⚠️ AI 브리핑 생성 중 오류: {e}"

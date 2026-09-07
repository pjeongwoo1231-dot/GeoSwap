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
    "Caldara·Iacoviello 지정학위험지수 GPR, EIA 원유재고, 한국가스공사 EU ETS 탄소가격)만을 근거로, "
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
    inventory_source="-",
    inventory_conflict=False,
    inv_oecd=None,
    inv_us=None,
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
    disp_str = "-" if dispersion_z is None else f"{dispersion_z:+.1f}%p"
    inv_mom_str = "" if inventory_mom is None else f" (전월비 {inventory_mom:+.1f}%, 출처 {inventory_source})"
    conflict_str = (
        chr(10)
        + f"- ⚠ **재고 괴리**: OECD {inv_oecd:+.2f}% vs 미국 {inv_us:+.2f}% — 부족이 미국이 아니라 "
        + "OECD(한국 포함)에 왔다. 한국 정유사에게는 이것이 헤드라인 유가보다 중요한 정보다."
        if inventory_conflict and inv_oecd is not None and inv_us is not None
        else ""
    )
    prompt = f"""다음은 Geo-Swap 플랫폼의 현재 분석 상태입니다.

[국면 판정 — 가장 먼저 읽을 것]
- 국면: {shock_label} (신뢰도 {shock_confidence})
- 지정학 혁신 z(AR(5) 잔차): {innov_str}   ← 지수 '수준'이 아니라 '예상 밖의 정도'
  ※ **판정 임계는 |z| ≥ 1.5σ다.** |z| < 1.5면 새로운 지정학 충격은 **없거나 이미 소멸한** 것이다.
     그런데도 국면이 유지돼 있다면 그것은 새 사건이 아니라 **지속**이다 —
     할인이 평시로 복귀하지 않았다는 뜻이며, 신뢰도를 한 단계 낮춰 서술한다.
     z가 작은데 '사건이 발생했다' '예상치를 상회했다'고 쓰는 것은 **금지**한다.
- 인도위험 초과할인(중동산이 대서양산 대비 받는 초과 할인): {disp_str}
- 재고 방향: {inventory_dir}{inv_mom_str}   ← 주 지표는 OECD 상업재고, 미국은 보조{conflict_str}

[산지 정보]
- 위험 산지(A): {country_a} (K-SURE 등급 {grade_a}/7, {quality_str})
- 안전 산지(B): {country_b}
- 기준 시점: {month}
- 구조적 신용 할인(A, K-SURE 등급 기반): {geo_discount_a:.1%}
- 석유 환율(스왑비율 A→B): {swap_rate:.4f} → A 1배럴 = B {swap_rate:.3f}배럴
- 스왑 ESG 효과(거래량 {volume:,}배럴): 탄소 {co2:,.0f}톤 절감, 운임 ${freight:,.0f} 절감

[모델 구조] 유효가격 = 벤치마크 × 품질보정 × (1 − 구조적 신용 할인).
국면에 따른 좌초 할인은 **벤치마크 가격 자체에 이미 반영돼 있으므로** 다시 곱하지 않는다.
스왑비율이 1보다 크면 A 1배럴이 B를 그만큼 많이 사는 것이고, 그것은 곧 B가 상대적으로 싸다는 뜻이다.

[국면별 해석 규칙 — 반드시 따를 것]
- **수송로 충격**: 해협·항로가 막혀 봉쇄된 산지의 배럴이 **좌초되어 할인**되는 국면.
  중동산이 대서양산 대비 크게 싸진다. **스왑 유인이 최대**다.
  단 반드시 함께 경고할 것 — **싸진 것은 가격이지 접근권이 아니다.**
  할인폭은 「그 배럴을 실제로 실어낼 수 있는가」에 시장이 매긴 값이며,
  인도를 확보하지 못하면 그 할인은 기회가 아니라 경고다.
- **생산자 충격**: 특정 산유국이 제재·감산으로 막혔지만 수송로는 열린 국면.
  물량이 재배치되며 두 벤치마크가 나란히 오른다 → 교환비율이 거의 안 바뀐다.
  Kilian·Park(2009) 기준 **스왑 유인이 낮다고 명확히 말할 것.** 억지로 추천하지 마세요.
- **글로벌 총수요**: 전면적 이동. 교환비율이 거의 안 바뀐다 → 스왑 유인 낮음.
- **판정 보류 / 지정학 데이터 없음**: 지정학에 귀속할 근거가 없어 판정하지 않은 상태다.
  Kilian(2008)에 따라 지정학 사건 대부분은 가격으로 전이되지 않는다 — 관망을 권고할 것.
- **평시**: 구조적 신용 할인만 작동한다. 품질 대비 저평가 여부로만 판단할 것.

아래 4가지를 각각 2~3문장으로, 굵은 소제목 달아 작성(스왑 방향은 항상 'A 권리 → B 실물'):
1) **국면 진단** — 위 국면이 왜 그렇게 판정됐는지를 혁신 z와 인도위험 초과할인으로 설명.
   혁신 z가 1.5σ 미만이면 '새 충격'이 아니라 '기존 국면의 지속'으로 쓸 것
2) **현황 진단** — A의 신용·인도 할인, 품질, 그로 인한 가격 괴리
3) **스왑 판단** — 위 국면별 규칙에 따라 실행/관망을 명확히. 수송로 충격이면 접근권 경고를 반드시 포함
4) **핵심 리스크 1가지**
   ※ 위에 '재고 괴리'가 표시돼 있으면, 그 괴리가 한국 정유사에게 무엇을 뜻하는지를 반드시 이 항목에 넣을 것."""
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

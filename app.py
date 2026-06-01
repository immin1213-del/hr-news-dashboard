import streamlit as st
import json
import re
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────
# 페이지 기본 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="HR 뉴스 모니터링",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────
# 전역 CSS 스타일
# ─────────────────────────────────────────
st.markdown("""
<style>
    /* ── 기본 배경/폰트 ── */
    .stApp {
        background-color: #F4F6FA;
        font-family: 'Noto Sans KR', -apple-system, sans-serif;
    }

    /* ── 헤더 배너 ── */
    .hero-banner {
        background: linear-gradient(135deg, #0A2342 0%, #1A4A7A 60%, #2563B0 100%);
        border-radius: 16px;
        padding: 36px 48px;
        margin-bottom: 28px;
        color: white;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .hero-title {
        font-size: 28px;
        font-weight: 700;
        letter-spacing: -0.5px;
        margin: 0 0 6px 0;
    }
    .hero-subtitle {
        font-size: 14px;
        opacity: 0.75;
        margin: 0;
    }
    .hero-right {
        text-align: right;
    }
    .hero-date {
        font-size: 13px;
        opacity: 0.7;
        margin-bottom: 4px;
    }
    .hero-count {
        font-size: 48px;
        font-weight: 800;
        line-height: 1;
        color: #7DD3FC;
    }
    .hero-count-label {
        font-size: 13px;
        opacity: 0.75;
        margin-top: 2px;
    }

    /* ── 구분선 ── */
    .divider {
        border: none;
        border-top: 1px solid #E2E8F0;
        margin: 4px 0 20px 0;
    }

    /* ── 카테고리 배지 ── */
    .badge {
        display: inline-block;
        background-color: #1A4A7A;
        color: #E0EFFF;
        font-size: 11px;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 20px;
        margin-right: 8px;
        letter-spacing: 0.3px;
    }
    .badge-alt {
        background-color: #2563B0;
    }

    /* ── expander 제목 스타일 오버라이드 ── */
    .streamlit-expanderHeader {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        padding: 14px 20px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        color: #1E293B !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
        transition: box-shadow 0.2s !important;
    }
    .streamlit-expanderHeader:hover {
        box-shadow: 0 4px 12px rgba(26, 74, 122, 0.15) !important;
    }
    .streamlit-expanderContent {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-top: none !important;
        border-radius: 0 0 12px 12px !important;
        padding: 20px 28px !important;
    }

    /* ── 섹션 라벨 ── */
    .section-label {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #64748B;
        margin: 18px 0 6px 0;
    }

    /* ── 핵심 요약 박스 ── */
    .summary-box {
        background-color: #F8FAFF;
        border-left: 4px solid #2563B0;
        border-radius: 0 8px 8px 0;
        padding: 14px 18px;
        font-size: 14.5px;
        line-height: 1.75;
        color: #1E293B;
        margin: 8px 0;
    }

    /* ── New Impact 경고 박스 ── */
    .impact-box {
        background: linear-gradient(135deg, #FFF7ED 0%, #FEF3E2 100%);
        border: 1px solid #FCD34D;
        border-left: 4px solid #F59E0B;
        border-radius: 0 8px 8px 0;
        padding: 14px 18px;
        font-size: 14px;
        line-height: 1.75;
        color: #78350F;
        margin: 8px 0;
    }

    /* ── Action Point 항목 ── */
    .action-item {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 10px 14px;
        background-color: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 8px;
        margin-bottom: 8px;
        font-size: 14px;
        color: #14532D;
        line-height: 1.65;
    }
    .action-icon {
        font-size: 16px;
        flex-shrink: 0;
        margin-top: 1px;
    }

    /* ── 출처 링크 영역 ── */
    .source-box {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: #475569;
        margin: 6px 0 2px 0;
    }
    .source-box a {
        color: #2563B0;
        text-decoration: none;
        font-weight: 500;
    }
    .source-box a:hover {
        text-decoration: underline;
    }

    /* ── 빈 상태 ── */
    .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #94A3B8;
        font-size: 15px;
    }

    /* ── 반응형 조정 ── */
    @media (max-width: 768px) {
        .hero-banner { flex-direction: column; gap: 20px; text-align: center; }
        .hero-right { text-align: center; }
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────
def load_news(path: str = "news_data.json") -> tuple[str, list[dict]]:
    """JSON 파일에서 업데이트 시간과 뉴스 데이터를 로드합니다."""
    file = Path(path)
    if not file.exists():
        return "", []
    
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # 데이터 구조 대응 (crawl_news.py는 딕셔너리로 저장함)
    if isinstance(data, dict) and "articles" in data:
        last_updated = data.get("last_updated", "")
        articles = data.get("articles", [])
        return last_updated, articles
    elif isinstance(data, list): # 혹시 모를 구버전 데이터 호환
        return "", data
    else:
        raise ValueError("JSON 최상위 구조가 'articles' 키를 포함한 딕셔너리거나 리스트여야 합니다.")


def extract_categories(item: dict) -> tuple[list[str], str]:
    """아이템의 카테고리 필드 및 제목에서 [카테고리] 태그를 추출합니다."""
    title = item.get("title", "")
    feed_category = item.get("category", "")
    
    brackets = re.findall(r"\[([^\]]+)\]", title)
    clean_title = re.sub(r"\[[^\]]+\]\s*", "", title).strip(" —–-").strip()
    
    categories = []
    if feed_category:
        categories.append(feed_category)
        
    for b in brackets:
        categories.extend([c.strip() for c in b.split("/")])
        
    # 중복 제거 및 최대 2개 반환
    unique_categories = list(dict.fromkeys(categories))
    return unique_categories[:2], clean_title


def render_hero(news_count: int, last_updated: str):
    """상단 히어로 배너를 렌더링합니다."""
    # last_updated가 없으면 현재 시간 사용
    display_date = last_updated if last_updated else datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST")
    
    st.markdown(f"""
    <div class="hero-banner">
        <div class="hero-left">
            <p class="hero-title">📋 HR 뉴스 모니터링 대시보드</p>
            <p class="hero-subtitle">고용노동부 · 대법원 · 글로벌 컨설팅 — 인사 실무자를 위한 핵심 이슈 브리핑</p>
        </div>
        <div class="hero-right">
            <p class="hero-date">🗓 최종 업데이트: {display_date}</p>
            <p class="hero-count">{news_count}</p>
            <p class="hero-count-label">수집된 뉴스 건수</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_news_card(item: dict, index: int):
    """단일 뉴스 아이템을 expander 카드로 렌더링합니다."""
    # crawl_news.py의 필드명 매핑 (link, source 사용)
    source_name = item.get("source", "알 수 없는 출처")
    source_url  = item.get("link", "")
    summary     = item.get("summary", "")
    
    # 향후 AI 분석 단계에서 추가될 수 있는 필드 (없을 경우를 위한 안전한 기본값)
    novelty     = item.get("novelty_impact", "")
    actions     = item.get("action_point", [])

    categories, clean_title = extract_categories(item)

    # ── 배지 HTML ──
    badge_html = "".join(
        f'<span class="badge {"badge-alt" if i % 2 else ""}">{cat}</span>'
        for i, cat in enumerate(categories)
    )
    expander_label = f"{badge_html} {clean_title}" if categories else clean_title

    with st.expander(expander_label, expanded=False):
        # 출처 및 발행일
        pub_date = item.get("pubDate", "")
        date_str = f" | 🕒 {pub_date}" if pub_date else ""
        
        st.markdown('<p class="section-label">📅 출처 및 링크</p>', unsafe_allow_html=True)
        if source_url:
            st.markdown(
                f'<div class="source-box">🔗 <a href="{source_url}" target="_blank">{source_name}</a>{date_str}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f'<div class="source-box">📌 {source_name}{date_str}</div>', unsafe_allow_html=True)

        st.markdown('<hr class="divider">', unsafe_allow_html=True)

        # 핵심 요약
        if summary:
            st.markdown('<p class="section-label">📝 핵심 요약</p>', unsafe_allow_html=True)
            summary_html = summary.replace(". ", ".<br>").replace("됨.", "됨.<br>").replace("함.", "함.<br>")
            st.markdown(f'<div class="summary-box">{summary_html}</div>', unsafe_allow_html=True)
            st.markdown('<hr class="divider">', unsafe_allow_html=True)

        # 향후 LLM 분석 필드가 데이터에 존재할 때만 렌더링하도록 조건부 처리
        if novelty:
            st.markdown('<p class="section-label">🚨 기존과 다른 점 (New Impact)</p>', unsafe_allow_html=True)
            st.markdown(f'<div class="impact-box">{novelty}</div>', unsafe_allow_html=True)
            st.markdown('<hr class="divider">', unsafe_allow_html=True)

        if actions:
            st.markdown('<p class="section-label">💡 HR Action Point</p>', unsafe_allow_html=True)
            for action in actions:
                st.markdown(
                    f'<div class="action-item"><span class="action-icon">☑️</span><span>{action}</span></div>',
                    unsafe_allow_html=True,
                )


# ─────────────────────────────────────────
# 사이드바 — 필터 & 검색
# ─────────────────────────────────────────
def render_sidebar(news_list: list[dict]) -> list[dict]:
    with st.sidebar:
        st.markdown("## 🔍 필터 & 검색")
        st.markdown("---")

        keyword = st.text_input("키워드 검색", placeholder="예: 불법파견, AI, 육아")

        # 카테고리 수집
        all_cats: list[str] = []
        for item in news_list:
            cats, _ = extract_categories(item)
            all_cats.extend(cats)
        unique_cats = sorted(set(all_cats))

        selected_cats = st.multiselect(
            "카테고리 필터",
            options=unique_cats,
            default=[],
            placeholder="전체 보기",
        )

        st.markdown("---")
        st.markdown(f"**전체 뉴스:** {len(news_list)}건")

    # ── 필터 적용 ──
    filtered = news_list
    if keyword:
        kw = keyword.lower()
        filtered = [
            n for n in filtered
            if kw in n.get("title", "").lower()
            or kw in n.get("summary", "").lower()
            or kw in n.get("novelty_impact", "").lower()
        ]
    if selected_cats:
        def has_cat(item):
            cats, _ = extract_categories(item)
            return any(c in selected_cats for c in cats)
        filtered = [n for n in filtered if has_cat(n)]

    return filtered


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    try:
        last_updated, news_list = load_news("news_data.json")
    except json.JSONDecodeError as e:
        st.error(f"❌ JSON 파싱 오류: {e}")
        st.stop()
    except ValueError as e:
        st.error(f"❌ 데이터 형식 오류: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ 데이터 로딩 실패: {e}")
        st.stop()

    filtered = render_sidebar(news_list)
    render_hero(len(filtered), last_updated)

    # ── 정렬 & 필터 상태 표시 ──
    col_info, col_sort = st.columns([4, 1])
    with col_info:
        if len(filtered) < len(news_list):
            st.info(f"🔎 필터 결과: 전체 {len(news_list)}건 중 **{len(filtered)}건** 표시 중")
    with col_sort:
        pass  # 향후 정렬 옵션 확장 가능

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # ── 뉴스 카드 렌더링 ──
    if not filtered:
        st.markdown(
            '<div class="empty-state">😕 조건에 맞는 뉴스가 없습니다.<br>키워드 또는 카테고리 필터를 조정해 보세요.</div>',
            unsafe_allow_html=True,
        )
    else:
        for i, item in enumerate(filtered):
            try:
                render_news_card(item, i)
            except Exception as e:
                st.warning(f"⚠️ {i+1}번째 뉴스 렌더링 중 오류 발생: {e}")

    # ── 푸터 ──
    st.markdown("---")
    st.markdown(
        '<p style="text-align:center; color:#94A3B8; font-size:12px;">'
        '📋 HR 뉴스 모니터링 대시보드 · 자율형 HR 리서치 에이전트 제공 · 사내 배포용</p>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

import streamlit as st
import json
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

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
    
    /* ── 카테고리 헤더 ── */
    .category-header {
        font-size: 20px;
        font-weight: 700;
        color: #0A2342;
        margin: 32px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid #E2E8F0;
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
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────
def load_news(path: str = "news_data.json") -> tuple[str, list[dict]]:
    file = Path(path)
    if not file.exists():
        return "", []
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "articles" in data:
        return data.get("last_updated", ""), data.get("articles", [])
    elif isinstance(data, list):
        return "", data
    else:
        raise ValueError("JSON 최상위 구조가 'articles' 키를 포함한 딕셔너리거나 리스트여야 합니다.")

def extract_categories(item: dict) -> tuple[list[str], str]:
    title = item.get("title", "")
    feed_category = item.get("category", "")
    
    brackets = re.findall(r"\[([^\]]+)\]", title)
    clean_title = re.sub(r"\[[^\]]+\]\s*", "", title).strip(" —–-").strip()
    
    categories = []
    if feed_category:
        categories.append(feed_category)
    for b in brackets:
        categories.extend([c.strip() for c in b.split("/")])
        
    unique_categories = list(dict.fromkeys(categories))
    return unique_categories[:2], clean_title


def render_news_card(item: dict, index: int):
    source_name = item.get("source", "알 수 없는 출처")
    source_url  = item.get("link", "")
    summary     = item.get("summary", "")
    categories, clean_title = extract_categories(item)

    # 🚨 수정된 부분: expander 제목은 HTML을 지원하지 않으므로 순수 텍스트(대괄호)로 처리합니다.
    cat_str = "".join(f"[{cat}] " for cat in categories)
    expander_label = f"{cat_str}{clean_title} - {source_name}"

    with st.expander(expander_label, expanded=False):
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

        if summary:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown('<p class="section-label">📝 원문 요약(발췌)</p>', unsafe_allow_html=True)
            summary_html = summary.replace(". ", ".<br>").replace("됨.", "됨.<br>").replace("함.", "함.<br>")
            st.markdown(f'<div class="summary-box">{summary_html}</div>', unsafe_allow_html=True)

def render_news_card(item: dict, index: int):
    source_name = item.get("source", "알 수 없는 출처")
    source_url  = item.get("link", "")
    summary     = item.get("summary", "")
    categories, clean_title = extract_categories(item)

    # expander 제목에 배지와 언론사를 함께 표기 (제안해주신 아이디어 반영)
    badge_html = "".join(
        f'<span class="badge {"badge-alt" if i % 2 else ""}">{cat}</span>'
        for i, cat in enumerate(categories)
    )
    expander_label = f"{badge_html} {clean_title} - <b>{source_name}</b>" if categories else f"{clean_title} - <b>{source_name}</b>"

    with st.expander(expander_label, expanded=False):
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

        if summary:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown('<p class="section-label">📝 원문 요약(발췌)</p>', unsafe_allow_html=True)
            summary_html = summary.replace(". ", ".<br>").replace("됨.", "됨.<br>").replace("함.", "함.<br>")
            st.markdown(f'<div class="summary-box">{summary_html}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────
# 사이드바 — 필터 & 검색
# ─────────────────────────────────────────
def render_sidebar(news_list: list[dict]) -> list[dict]:
    with st.sidebar:
        st.markdown("## 🔍 필터 & 검색")
        st.markdown("---")
        keyword = st.text_input("키워드 검색", placeholder="예: 불법파견, AI, 육아")

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

    filtered = news_list
    if keyword:
        kw = keyword.lower()
        filtered = [
            n for n in filtered
            if kw in n.get("title", "").lower() or kw in n.get("summary", "").lower()
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
    except Exception as e:
        st.error(f"❌ 데이터 로딩 실패: {e}")
        st.stop()

    filtered = render_sidebar(news_list)
    render_hero(len(filtered), last_updated)

    if not filtered:
        st.markdown(
            '<div class="empty-state">😕 조건에 맞는 뉴스가 없습니다.<br>키워드 또는 카테고리 필터를 조정해 보세요.</div>',
            unsafe_allow_html=True,
        )
    else:
        # 1. 뉴스를 메인 카테고리별로 그룹화 (제안하신 로직 반영)
        grouped_news = defaultdict(list)
        for item in filtered:
            cats, _ = extract_categories(item)
            # 카테고리가 없으면 '기타'로 분류
            primary_cat = cats[0] if cats else "기타"
            grouped_news[primary_cat].append(item)

        # 2. 카테고리별로 섹션을 나누어 출력
        for category in sorted(grouped_news.keys()):
            # 카테고리 헤더
            st.markdown(f'<div class="category-header">📁 {category} 뉴스</div>', unsafe_allow_html=True)
            
            # 해당 카테고리의 뉴스 출력
            for i, item in enumerate(grouped_news[category]):
                try:
                    render_news_card(item, i)
                except Exception as e:
                    st.warning(f"⚠️ 뉴스 렌더링 중 오류 발생: {e}")

    # ── 푸터 ──
    st.markdown("---")
    st.markdown(
        '<p style="text-align:center; color:#94A3B8; font-size:12px;">'
        '📋 HR 뉴스 모니터링 대시보드 · 자율형 HR 리서치 에이전트 제공</p>',
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()

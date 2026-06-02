import streamlit as st
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# 페이지 기본 설정
st.set_page_config(
    page_title="HR 뉴스 모니터링",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 카테고리 표시 순서 (crawler 의 CATEGORIES 와 동일하게 유지)
CATEGORY_ORDER = [
    "고용노동부 정책",
    "노동법/판례",
    "보상/평가",
    "채용/조직문화",
    "HR테크/AI",
    "글로벌 HR 트렌드",
]

CATEGORY_ICON = {
    "고용노동부 정책": "🏛️",
    "노동법/판례": "⚖️",
    "보상/평가": "💰",
    "채용/조직문화": "🤝",
    "HR테크/AI": "🤖",
    "글로벌 HR 트렌드": "🌐",
    "기타": "📰",
}

# 전역 CSS
st.markdown("""
<style>
.stApp { background-color: #F4F6FA; font-family: 'Noto Sans KR', -apple-system, sans-serif; }
.hero-banner { background: linear-gradient(135deg, #0A2342 0%, #1A4A7A 60%, #2563B0 100%); border-radius: 16px; padding: 36px 48px; margin-bottom: 28px; color: white; display: flex; justify-content: space-between; align-items: center; }
.hero-title { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin: 0 0 6px 0; }
.hero-subtitle { font-size: 14px; opacity: 0.75; margin: 0; }
.hero-right { text-align: right; }
.hero-date { font-size: 13px; opacity: 0.7; margin-bottom: 4px; }
.hero-count { font-size: 48px; font-weight: 800; line-height: 1; color: #7DD3FC; }
.hero-count-label { font-size: 13px; opacity: 0.75; margin-top: 2px; }
.category-header { font-size: 20px; font-weight: 700; color: #0A2342; margin: 32px 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #E2E8F0; }
.badge { display: inline-block; background-color: #1A4A7A; color: #E0EFFF; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-right: 8px; letter-spacing: 0.3px; }
.badge-global { background-color: #0E7490; }
.section-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #64748B; margin: 14px 0 6px 0; }
.summary-box { background-color: #F8FAFF; border-left: 4px solid #2563B0; border-radius: 0 8px 8px 0; padding: 14px 18px; font-size: 14.5px; line-height: 1.75; color: #1E293B; margin: 8px 0; }
.impact-box { background-color: #FFFBEB; border-left: 4px solid #F59E0B; border-radius: 0 8px 8px 0; padding: 12px 18px; font-size: 14px; line-height: 1.7; color: #1E293B; margin: 8px 0; }
.source-box { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #475569; margin: 10px 0 2px 0; }
.source-box a { color: #2563B0; text-decoration: none; font-weight: 500; }
.source-box a:hover { text-decoration: underline; }
.empty-state { text-align: center; padding: 60px 20px; color: #94A3B8; font-size: 15px; }
</style>
""", unsafe_allow_html=True)


def load_news(path: str = "news_data.json"):
    file = Path(path)
    if not file.exists():
        return "", []
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "articles" in data:
        return data.get("last_updated", ""), data.get("articles", [])
    if isinstance(data, list):
        return "", data
    return "", []


def get_category(item):
    cat = item.get("category", "").strip()
    return cat if cat in CATEGORY_ORDER else "기타"


def render_hero(news_count, last_updated):
    display_date = last_updated or datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST")
    st.markdown(f"""
    <div class="hero-banner">
      <div class="hero-left">
        <p class="hero-title">📋 HR 뉴스 모니터링 대시보드</p>
        <p class="hero-subtitle">국내외 정책·판례·HR테크·글로벌 트렌드 — 인사 실무자를 위한 핵심 이슈 브리핑</p>
      </div>
      <div class="hero-right">
        <p class="hero-date">🗓 최종 업데이트: {display_date}</p>
        <p class="hero-count">{news_count}</p>
        <p class="hero-count-label">수집된 뉴스 건수</p>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_news_card(item):
    title = item.get("title", "제목 없음")
    region = item.get("region", "")
    source = item.get("source", "알 수 없는 출처")
    link = item.get("link", "")
    summary = item.get("summary", "")
    impact = item.get("novelty_impact", "")
    actions = item.get("action_point", [])

    badge_cls = "badge badge-global" if region == "해외" else "badge"
    label = f"[{region}] {title}" if region else title

    with st.expander(label):
        if region:
            st.markdown(f'<span class="{badge_cls}">{region}</span>', unsafe_allow_html=True)
        if summary:
            st.markdown('<p class="section-label">핵심 요약</p>', unsafe_allow_html=True)
            st.markdown(f'<div class="summary-box">{summary}</div>', unsafe_allow_html=True)
        if impact:
            st.markdown('<p class="section-label">실무 임팩트</p>', unsafe_allow_html=True)
            st.markdown(f'<div class="impact-box">{impact}</div>', unsafe_allow_html=True)
        if actions:
            st.markdown('<p class="section-label">실무 체크포인트</p>', unsafe_allow_html=True)
            for a in actions:
                st.markdown(f"- {a}")
        if link:
            st.markdown(
                f'<div class="source-box">🔗 출처: {source} · <a href="{link}" target="_blank">원문 보기</a></div>',
                unsafe_allow_html=True,
            )


def main():
    last_updated, articles = load_news()
    render_hero(len(articles), last_updated)

    if not articles:
        st.markdown('<div class="empty-state">아직 수집된 뉴스가 없습니다. 크롤러 실행 후 자동으로 채워집니다.</div>', unsafe_allow_html=True)
        return

    # 카테고리별 그룹화
    grouped = defaultdict(list)
    for item in articles:
        grouped[get_category(item)].append(item)

    order = CATEGORY_ORDER + ["기타"]
    for cat in order:
        items = grouped.get(cat)
        if not items:
            continue
        icon = CATEGORY_ICON.get(cat, "📰")
        st.markdown(f'<div class="category-header">{icon} {cat} <span style="color:#94A3B8;font-size:14px;">({len(items)}건)</span></div>', unsafe_allow_html=True)
        for item in items:
            render_news_card(item)


if __name__ == "__main__":
    main()

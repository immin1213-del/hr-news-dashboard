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
    "고용노동부 정책": "🏛",
    "노동법/판례": "⚖",
    "보상/평가": "💰",
    "채용/조직문화": "🤝",
    "HR테크/AI": "🤖",
    "글로벌 HR 트렌드": "🌐",
    "기타": "📰",
}


# 전역 CSS — McKinsey 풍의 절제된 모던 디자인
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=Libre+Franklin:wght@400;600;700&display=swap');

.stApp { background-color: #FFFFFF; font-family: 'Noto Sans KR', -apple-system, sans-serif; color: #1A1A1A; }
.block-container { max-width: 1080px; padding-top: 2.5rem; }
#MainMenu, footer, header { visibility: hidden; }

/* 헤더 */
.masthead { border-top: 3px solid #051C2C; padding: 28px 0 22px 0; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: flex-end; }
.mh-eyebrow { font-family: 'Libre Franklin', sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 2.5px; text-transform: uppercase; color: #0066B2; margin: 0 0 14px 0; }
.mh-title { font-size: 34px; font-weight: 900; letter-spacing: -0.8px; line-height: 1.18; color: #051C2C; margin: 0; }
.mh-title .accent { color: #0066B2; }
.mh-sub { font-size: 15px; font-weight: 400; color: #5A6B7B; margin: 12px 0 0 0; letter-spacing: -0.2px; }
.mh-right { text-align: right; padding-bottom: 4px; min-width: 150px; }
.mh-count { font-size: 52px; font-weight: 900; line-height: 1; color: #051C2C; letter-spacing: -1.5px; }
.mh-count-label { font-family: 'Libre Franklin', sans-serif; font-size: 10.5px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #8A97A4; margin-top: 6px; }
.mh-date { font-size: 12px; color: #8A97A4; margin-top: 10px; letter-spacing: 0.2px; }
.masthead-rule { height: 1px; background: #E3E8EC; margin: 0 0 8px 0; }

/* 카테고리 섹션 헤더 */
.category-header { display: flex; align-items: baseline; gap: 12px; margin: 44px 0 14px 0; padding-bottom: 12px; border-bottom: 1px solid #E3E8EC; }
.category-header .ch-icon { font-size: 18px; }
.category-header .ch-name { font-size: 20px; font-weight: 700; color: #051C2C; letter-spacing: -0.4px; }
.category-header .ch-count { font-family: 'Libre Franklin', sans-serif; font-size: 12px; font-weight: 600; color: #0066B2; letter-spacing: 0.5px; }

/* 카드 / expander */
div[data-testid="stExpander"] { border: 1px solid #E3E8EC !important; border-radius: 0 !important; box-shadow: none !important; margin-bottom: 0 !important; border-bottom: none !important; }
div[data-testid="stExpander"]:last-child { border-bottom: 1px solid #E3E8EC !important; }
div[data-testid="stExpander"] details { border: none !important; }
div[data-testid="stExpander"] summary { padding: 16px 20px !important; font-size: 15.5px !important; font-weight: 500 !important; color: #1A2733 !important; transition: background 0.15s; }
div[data-testid="stExpander"] summary:hover { background: #F7F9FB !important; color: #0066B2 !important; }

/* 배지 */
.badge { display: inline-block; background-color: #051C2C; color: #FFFFFF; font-family: 'Libre Franklin', sans-serif; font-size: 10px; font-weight: 600; padding: 3px 11px; border-radius: 2px; margin-right: 8px; letter-spacing: 1px; text-transform: uppercase; }
.badge-global { background-color: #0066B2; }

/* 라벨 / 박스 */
.section-label { font-family: 'Libre Franklin', sans-serif; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #0066B2; margin: 18px 0 6px 0; }
.summary-box { background-color: #F7F9FB; border-left: 2px solid #0066B2; padding: 14px 18px; font-size: 14.5px; line-height: 1.8; color: #2A3744; margin: 6px 0; }
.impact-box { background-color: #FBF9F5; border-left: 2px solid #C9A227; padding: 14px 18px; font-size: 14px; line-height: 1.75; color: #2A3744; margin: 6px 0; }
.source-box { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: #5A6B7B; margin: 16px 0 4px 0; padding-top: 12px; border-top: 1px solid #EEF1F4; }
.source-box a { color: #0066B2; text-decoration: none; font-weight: 600; }
.source-box a:hover { text-decoration: underline; }
.empty-state { text-align: center; padding: 80px 20px; color: #8A97A4; font-size: 15px; }
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
    <div class="masthead">
      <div class="mh-left">
        <p class="mh-eyebrow">HR Intelligence Briefing</p>
        <p class="mh-title">국내외 정책 · 판례 · HR테크 · <span class="accent">글로벌 트렌드</span><br>인사 실무자를 위한 핵심 이슈 브리핑</p>
      </div>
      <div class="mh-right">
        <div class="mh-count">{news_count}</div>
        <div class="mh-count-label">Articles Tracked</div>
        <div class="mh-date">{display_date}</div>
      </div>
    </div>
    <div class="masthead-rule"></div>
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

    grouped = defaultdict(list)
    for item in articles:
        grouped[get_category(item)].append(item)

    order = CATEGORY_ORDER + ["기타"]
    for cat in order:
        items = grouped.get(cat)
        if not items:
            continue
        icon = CATEGORY_ICON.get(cat, "📰")
        st.markdown(
            f'<div class="category-header"><span class="ch-icon">{icon}</span>'
            f'<span class="ch-name">{cat}</span>'
            f'<span class="ch-count">{len(items)}건</span></div>',
            unsafe_allow_html=True,
        )
        for item in items:
            render_news_card(item)


if __name__ == "__main__":
    main()

import streamlit as st
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# 페이지 기본 설정
st.set_page_config(
    page_title="HR 뉴스 모니터링",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

CATEGORY_ORDER = [
    "고용노동부 정책",
    "노동법/판례",
    "노사관계/노동계",
    "보상/평가",
    "채용/조직문화",
    "HR테크/AI",
    "글로벌 HR 트렌드",
]

CATEGORY_ICON = {
    "고용노동부 정책": "🏛",
    "노동법/판례": "⚖",
    "노사관계/노동계": "✊",
    "보상/평가": "💰",
    "채용/조직문화": "🤝",
    "HR테크/AI": "🤖",
    "글로벌 HR 트렌드": "🌐",
    "기타": "📰",
}

# 정책·입법 통합 슬롯: 고용노동부 정책 + 국회 입법/노동법은 HR 실무 필수 영역으로 최상단 묶음 표시
POLICY_SLOT_CATEGORIES = ("고용노동부 정책", "노동법/판례")

# 국회 입법 '통과/확정' 신호 — 매일 아침 확인해 별도 배지로 강조
LEGISLATION_PASSED_KEYWORDS = ("본회의", "의결", "가결", "통과", "공포", "국회 통과", "법사위 통과")

def is_legislation_passed(item):
        """국회 본회의 통과·의결·공포 등 입법 확정 단계 기사인지 판정."""
        blob = " ".join([
                    str(item.get("title", "")),
                    str(item.get("summary", "")),
                    str(item.get("novelty_impact", "")),
        ])
        has_assembly = ("국회" in blob) or ("본회의" in blob) or ("법사위" in blob) or ("환노위" in blob)
        has_passed = any(k in blob for k in ("의결", "가결", "통과", "공포"))
        return has_assembly and has_passed

# 전역 CSS — McKinsey 풍의 절제된 모던 디자인 (본문 + 사이드바 통일)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=Libre+Franklin:wght@400;600;700&display=swap');

.stApp { background-color: #FFFFFF; font-family: 'Noto Sans KR', -apple-system, sans-serif; color: #1A1A1A; }
.block-container { max-width: 1080px; padding-top: 2.5rem; }
#MainMenu, footer, header { visibility: hidden; }

/* ===================== 사이드바 모던 리디자인 ===================== */
section[data-testid="stSidebar"] { background-color: #051C2C; border-right: none; }
section[data-testid="stSidebar"] > div { padding-top: 0; }
section[data-testid="stSidebar"] * { color: #DCE3EA; }

/* 사이드바 브랜드 헤더 밴드 */
.sb-brand { border-top: 3px solid #0066B2; padding: 22px 4px 18px 4px; margin-bottom: 6px; }
.sb-brand .sb-eyebrow { font-family: 'Libre Franklin', sans-serif; font-size: 10px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; color: #4D9FD6; margin: 0 0 8px 0; }
.sb-brand .sb-title { font-size: 17px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.3px; margin: 0; }
.sb-rule { height: 1px; background: rgba(255,255,255,0.12); margin: 4px 0 14px 0; }

/* 사이드바 섹션 라벨 */
.sb-label { font-family: 'Libre Franklin', sans-serif; font-size: 10.5px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #7E93A6; margin: 18px 0 8px 0; }

/* 사이드바 미니 통계 카드 (지역 분포) */
.sb-stats { display: flex; gap: 8px; margin: 2px 0 6px 0; }
.sb-stat { flex: 1; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; padding: 10px 8px; text-align: center; }
.sb-stat .num { font-size: 20px; font-weight: 900; color: #FFFFFF; line-height: 1; letter-spacing: -0.5px; }
.sb-stat .lab { font-family: 'Libre Franklin', sans-serif; font-size: 9px; font-weight: 600; letter-spacing: 0.8px; text-transform: uppercase; color: #7E93A6; margin-top: 5px; }

/* 입력 위젯 톤 통일 */
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea { background-color: rgba(255,255,255,0.06) !important; color: #FFFFFF !important; border: 1px solid rgba(255,255,255,0.14) !important; border-radius: 4px !important; }
section[data-testid="stSidebar"] input::placeholder { color: #6E8499 !important; }
section[data-testid="stSidebar"] .stTextInput input:focus { border-color: #0066B2 !important; box-shadow: 0 0 0 1px #0066B2 !important; }

/* multiselect 칩 */
section[data-testid="stSidebar"] div[data-baseweb="select"] > div { background-color: rgba(255,255,255,0.06) !important; border: 1px solid rgba(255,255,255,0.14) !important; border-radius: 4px !important; }
section[data-testid="stSidebar"] span[data-baseweb="tag"] { background-color: #0066B2 !important; border-radius: 3px !important; }
section[data-testid="stSidebar"] span[data-baseweb="tag"] span { color: #FFFFFF !important; }

/* 라디오 — 세그먼트 느낌 */
section[data-testid="stSidebar"] div[role="radiogroup"] label { color: #DCE3EA !important; }
section[data-testid="stSidebar"] .stRadio > label { color: #7E93A6 !important; }

/* 캡션 */
section[data-testid="stSidebar"] .sb-tip { font-size: 11.5px; color: #6E8499; line-height: 1.6; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 12px; margin-top: 18px; }

/* ===================== 본문(우측) ===================== */
.masthead { border-top: 3px solid #051C2C; padding: 28px 0 22px 0; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: flex-end; }
.mh-eyebrow { font-family: 'Libre Franklin', sans-serif; font-size: 11px; font-weight: 600; letter-spacing: 2.5px; text-transform: uppercase; color: #0066B2; margin: 0 0 14px 0; }
.mh-title { font-size: 34px; font-weight: 900; letter-spacing: -0.8px; line-height: 1.18; color: #051C2C; margin: 0; }
.mh-title .accent { color: #0066B2; }
.mh-right { text-align: right; padding-bottom: 4px; min-width: 150px; }
.mh-count { font-size: 52px; font-weight: 900; line-height: 1; color: #051C2C; letter-spacing: -1.5px; }
.mh-count-label { font-family: 'Libre Franklin', sans-serif; font-size: 10.5px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #8A97A4; margin-top: 6px; }
.mh-date { font-size: 12px; color: #8A97A4; margin-top: 10px; letter-spacing: 0.2px; }
.masthead-rule { height: 1px; background: #E3E8EC; margin: 0 0 8px 0; }

.result-bar { font-family: 'Libre Franklin', sans-serif; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; color: #5A6B7B; margin: 18px 0 4px 0; text-transform: uppercase; }
.result-bar b { color: #0066B2; }

.category-header { display: flex; align-items: baseline; gap: 12px; margin: 40px 0 14px 0; padding-bottom: 12px; border-bottom: 1px solid #E3E8EC; }
.category-header .ch-icon { font-size: 18px; }
.category-header .ch-name { font-size: 20px; font-weight: 700; color: #051C2C; letter-spacing: -0.4px; }
.category-header .ch-count { font-family: 'Libre Franklin', sans-serif; font-size: 12px; font-weight: 600; color: #0066B2; letter-spacing: 0.5px; }

div[data-testid="stExpander"] { border: 1px solid #E3E8EC !important; border-radius: 0 !important; box-shadow: none !important; margin-bottom: 0 !important; border-bottom: none !important; }
div[data-testid="stExpander"]:last-child { border-bottom: 1px solid #E3E8EC !important; }
div[data-testid="stExpander"] details { border: none !important; }
div[data-testid="stExpander"] summary { padding: 16px 20px !important; font-size: 15.5px !important; font-weight: 500 !important; color: #1A2733 !important; transition: background 0.15s; }
div[data-testid="stExpander"] summary:hover { background: #F7F9FB !important; color: #0066B2 !important; }

.badge { display: inline-block; background-color: #051C2C; color: #FFFFFF; font-family: 'Libre Franklin', sans-serif; font-size: 10px; font-weight: 600; padding: 3px 11px; border-radius: 2px; margin-right: 8px; letter-spacing: 1px; text-transform: uppercase; }
.badge-global { background-color: #0066B2; }
.badge-date { background-color: #EEF2F6; color: #5A6B7B; }
.badge-new { background-color: #D6202B; color: #FFFFFF; }
.badge-rev { background-color: #C9A227; color: #FFFFFF; }
.badge-pass { background-color: #B91C1C; color: #FFFFFF; }
.badge-policy { background-color: #065F46; color: #FFFFFF; }

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


def parse_scraped(item):
    raw = item.get("scraped_at") or item.get("collected_at") or ""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:16] if len(raw) >= 16 else raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def freshness_badges(item):
    dt = parse_scraped(item)
    html = ""
    if dt:
        age = datetime.now() - dt
        date_str = dt.strftime("%m.%d")
        if age <= timedelta(hours=48):
            html += '<span class="badge badge-new">NEW</span>'
        html += f'<span class="badge badge-date">📅 {date_str}</span>'
    rev = int(item.get("revision", 0) or 0)
    if rev > 0:
        html += f'<span class="badge badge-rev">↑ 심화 업데이트 ×{rev}</span>'
        cat = item.get("category", "")
        html += '<span class="badge badge-pass">🏛 입법통과</span>' if is_legislation_passed(item) else ('<span class="badge badge-policy">📌 정책</span>' if cat == "고용노동부 정책" else "")
    return html


def render_hero(filtered_count, total_count, last_updated):
    display_date = last_updated or datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST")
    st.markdown(f"""
    <div class="masthead">
      <div class="mh-left">
        <p class="mh-eyebrow">HR Intelligence Briefing</p>
        <p class="mh-title">국내외 정책 · 판례 · HR테크 · <span class="accent">글로벌 트렌드</span><br>인사 실무자를 위한 핵심 이슈 브리핑</p>
      </div>
      <div class="mh-right">
        <div class="mh-count">{total_count}</div>
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
    dt = parse_scraped(item)
    date_prefix = f"[{dt.strftime('%m.%d')}] " if dt else ""
    label = f"{date_prefix}[{region}] {title}" if region else f"{date_prefix}{title}"

    with st.expander(label):
        head = freshness_badges(item)
        if region:
            head += f'<span class="{badge_cls}">{region}</span>'
        if head:
            st.markdown(head, unsafe_allow_html=True)
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


def matches_query(item, query):
    if not query:
        return True
    q = query.lower()
    blob = " ".join([
        item.get("title", ""),
        item.get("summary", ""),
        item.get("novelty_impact", ""),
        " ".join(item.get("action_point", [])),
        item.get("source", ""),
    ]).lower()
    return q in blob


def within_days(item, days):
    if days <= 0:
        return True
    dt = parse_scraped(item)
    if dt is None:
        return True
    return (datetime.now() - dt) <= timedelta(days=days)


def region_of(item):
    r = item.get("region", "")
    return r if r in ("국내", "해외") else "국내"


# ---------------------------------------------------------
# 모던 사이드바: 브랜드 헤더 + 지역 분포 통계 + 검색/필터/정렬
# ---------------------------------------------------------
def render_sidebar(articles):
    sb = st.sidebar
    sb.markdown(
        '<div class="sb-brand"><p class="sb-eyebrow">HR Intelligence</p>'
        '<p class="sb-title">탐색 &amp; 큐레이션 콘솔</p></div>'
        '<div class="sb-rule"></div>',
        unsafe_allow_html=True,
    )

    dom = sum(1 for a in articles if region_of(a) == "국내")
    ov = sum(1 for a in articles if region_of(a) == "해외")
    sb.markdown('<p class="sb-label">Coverage</p>', unsafe_allow_html=True)
    sb.markdown(
        f'<div class="sb-stats">'
        f'<div class="sb-stat"><div class="num">{dom}</div><div class="lab">국내</div></div>'
        f'<div class="sb-stat"><div class="num">{ov}</div><div class="lab">해외</div></div>'
        f'<div class="sb-stat"><div class="num">{len(articles)}</div><div class="lab">Total</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    sb.markdown('<p class="sb-label">검색</p>', unsafe_allow_html=True)
    query = sb.text_input("키워드 검색", placeholder="예: 통상임금, AI 채용, 임금체불", label_visibility="collapsed")

    sb.markdown('<p class="sb-label">카테고리</p>', unsafe_allow_html=True)
    cats_present = [c for c in CATEGORY_ORDER if any(get_category(a) == c for a in articles)]
    if any(get_category(a) == "기타" for a in articles):
        cats_present.append("기타")
    sel_cats = sb.multiselect("카테고리", cats_present, default=cats_present, label_visibility="collapsed")

    sb.markdown('<p class="sb-label">지역</p>', unsafe_allow_html=True)
    region_choice = sb.radio("지역", ["전체", "국내", "해외"], index=0, horizontal=True, label_visibility="collapsed")

    sb.markdown('<p class="sb-label">수집 기간</p>', unsafe_allow_html=True)
    period_map = {"전체": 0, "7일": 7, "30일": 30, "90일": 90}
    period = sb.radio("수집 기간", list(period_map.keys()), index=0, horizontal=True, label_visibility="collapsed")

    sb.markdown('<p class="sb-label">정렬</p>', unsafe_allow_html=True)
    sort_newest = sb.radio("정렬", ["최신순", "오래된순"], index=0, horizontal=True, label_visibility="collapsed") == "최신순"

    sb.markdown(
        '<div class="sb-tip">💡 키워드는 제목·요약·실무 임팩트·체크포인트를 모두 검색합니다. '
        '국내외 소스가 매일 자동 수집·병합됩니다.</div>',
        unsafe_allow_html=True,
    )
    return query, sel_cats, region_choice, period_map[period], sort_newest


def main():
    last_updated, articles = load_news()
    query, sel_cats, region_choice, period_days, sort_newest = render_sidebar(articles)

    filtered = [
        a for a in articles
        if matches_query(a, query)
        and get_category(a) in sel_cats
        and (region_choice == "전체" or region_of(a) == region_choice)
        and within_days(a, period_days)
    ]

    render_hero(len(filtered), len(articles), last_updated)

    if not articles:
        st.markdown('<div class="empty-state">아직 수집된 뉴스가 없습니다. 크롤러 실행 후 자동으로 채워집니다.</div>', unsafe_allow_html=True)
        return

    st.markdown(
        f'<div class="result-bar">필터 결과 <b>{len(filtered)}</b>건 / 전체 {len(articles)}건</div>',
        unsafe_allow_html=True,
    )

    if not filtered:
        st.markdown('<div class="empty-state">조건에 맞는 뉴스가 없습니다. 검색어나 필터를 조정해 보세요.</div>', unsafe_allow_html=True)
        return

    def sort_key(a):
        return parse_scraped(a) or datetime.min

    filtered = sorted(filtered, key=sort_key, reverse=sort_newest)

    grouped = defaultdict(list)
    for item in filtered:
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
        INITIAL_VISIBLE = 10
        state_key = f"show_all_{cat}"
        if state_key not in st.session_state:
            st.session_state[state_key] = False

        show_all = st.session_state[state_key]
        visible_items = items if show_all else items[:INITIAL_VISIBLE]

        for item in visible_items:
            render_news_card(item)

        remaining = len(items) - INITIAL_VISIBLE
        if remaining > 0:
            if not show_all:
                if st.button(
                    f"＋ 더보기 ({remaining}개 더 보기)",
                    key=f"more_{cat}",
                    use_container_width=True,
                ):
                    st.session_state[state_key] = True
                    st.rerun()
            else:
                if st.button(
                    "− 접기",
                    key=f"less_{cat}",
                    use_container_width=True,
                ):
                    st.session_state[state_key] = False
                    st.rerun()


if __name__ == "__main__":
    main()

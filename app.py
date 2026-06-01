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
    .stApp { background-color: #F4F6FA; font-family: 'Noto Sans KR', -apple-system, sans-serif; }
    
    /* ── 헤더 배너 ── */
    .hero-banner { background: linear-gradient(135deg, #0A2342 0%, #1A4A7A 60%, #2563B0 100%); border-radius: 16px; padding: 36px 48px; margin-bottom: 28px; color: white; display: flex; justify-content: space-between; align-items: center; }
    .hero-title { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin: 0 0 6px 0; }
    .hero-subtitle { font-size: 14px; opacity: 0.75; margin: 0; }
    .hero-right { text-align: right; }
    .hero-date { font-size: 13px; opacity: 0.7; margin-bottom: 4px; }
    .hero-count { font-size: 48px; font-weight: 800; line-height: 1; color: #7DD3FC; }
    .hero-count-label { font-size: 13px; opacity: 0.75; margin-top: 2px; }
    
    /* ── 구분선 ── */
    .divider { border: none; border-top: 1px solid #E2E8F0; margin: 4px 0 20px 0; }
    
    /* ── 카테고리 헤더 ── */
    .category-header { font-size: 20px; font-weight: 700; color: #0A2342; margin: 32px 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #E2E8F0; }
    
    /* ── 카테고리 배지 ── */
    .badge { display: inline-block; background-color: #1A4A7A; color: #E0EFFF; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; margin-right: 8px; letter-spacing: 0.3px; }
    .badge-alt { background-color: #2563B0; }
    
    /* ── expander 제목 스타일 오버라이드 ── */
    .streamlit-expanderHeader { background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 12px !important; padding: 14px 20px !important; font-size: 15px !important; font-weight: 600 !important; color: #1E293B !important; box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important; transition: box-shadow 0.2s !important; }
    .streamlit-expanderHeader:hover { box-shadow: 0 4px 12px rgba(26, 74, 122, 0.15) !important; }
    .streamlit-expanderContent { background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-top: none !important; border-radius: 0 0 12px 12px !important; padding: 20px 28px !important; }
    
    /* ── 섹션 라벨 ── */
    .section-label { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #64748B; margin: 18px 0 6px 0; }
    
    /* ── 핵심 요약 박스 ── */
    .summary-box { background-color: #F8FAFF; border-left: 4px solid #2563B0; border-radius: 0 8px 8px 0; padding: 14px 18px; font-size: 14.5px; line-height: 1.75; color: #1E293B; margin: 8px 0; }
    
    /* ── 출처 링크 영역 ── */
    .source-box { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #475569; margin: 6px 0 2px 0; }
    .source-box a { color: #2563B0; text-decoration: none; font-weight: 500; }
    .source-box a:hover { text-decoration: underline; }
    
    /* ── 빈 상태 ── */
    .empty-state { text-align: center; padding: 60px 20px; color: #94A3B8; font-size: 15px; }
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

def render_hero(news_count: int, last_updated: str):
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
            <p class="hero

import streamlit as st
import json
import pandas as pd
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="HR 뉴스 대시보드",
    page_icon="📰",
    layout="wide"
)

st.title("📰 HR 뉴스 대시보드")
st.markdown("GitHub Actions가 매일 자동으로 수집한 HR 관련 업계 뉴스")

# 데이터 로드
@st.cache_data(ttl=3600)
def load_data():
    try:
        with open("news_data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except FileNotFoundError:
        return {"last_updated": "", "articles": []}

data = load_data()
last_updated = data.get("last_updated", "")
articles = data.get("articles", [])

# 마지막 업데이트 시간 표시
if last_updated:
    st.info(f"마지막 업데이트: {last_updated}")
else:
    st.warning("아직 수집된 데이터가 없습니다. GitHub Actions를 실행하면 자동으로 채워집니다.")

# 뉴스 목록 표시
if articles:
    st.subheader(f"총 {len(articles)}개의 뉴스")

    # 카테고리 필터
    categories = list(set(a.get("category", "기타") for a in articles))
    categories.sort()
    selected_category = st.selectbox("카테고리 선택", ["전체"] + categories)

    # 필터링
    if selected_category != "전체":
        filtered = [a for a in articles if a.get("category") == selected_category]
    else:
        filtered = articles

    # 카드 형태로 표시
    for i, article in enumerate(filtered):
        with st.expander(article.get("title", "제목 없음"), expanded=(i < 3)):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(article.get("summary", "요약 없음"))
                if article.get("link"):
                    st.markdown(f"[원문 보기]({article.get('link')})")
            with col2:
                st.caption(article.get("pubDate", ""))
                st.caption(article.get("category", "기타"))
                st.caption(article.get("source", ""))
else:
    st.info("뉴스 데이터가 없습니다. GitHub Actions 워크플로우를 실행해주세요.")

# 사이드바
with st.sidebar:
    st.header("정보")
    st.write("이 대시보드는 HR 관련 뉴스를 자동으로 수집합니다.")
    st.write("수집 주기: 매일 오전 8시 (KST)")
    st.write("수집 소스: 다양한 HR/채용 뉴스 RSS")
    if st.button("데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

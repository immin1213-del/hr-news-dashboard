import streamlit as st
import json
import pandas as pd
from datetime import datetime

# 페이지 설정
st.set_page_config(
      page_title="HR 뉴스 대시보드",
      page_icon="📊",
      layout="wide"
)

st.title("📊 HR 뉴스 대시보드")
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
      st.info(f"🕒 마지막 업데이트: {last_updated}")
else:
      st.warning("⚠️ 아직 수집된 데이터가 없습니다. GitHub Actions가 실행되면 자동으로 채워집니다.")

st.divider()

# 뉴스 목록 표시
if articles:
      st.subheader(f"📰 최신 뉴스 ({len(articles)}건)")
      for article in articles:
                with st.expander(f"📌 {article.get('title', '제목 없음')}"):
                              col1, col2 = st.columns([3, 1])
                              with col1:
                                                st.write(article.get("summary", ""))
                                            with col2:
                                  st.write(f"🗓 {article.get('date', '')}")
                                                              if article.get("url"):
                                                                                    st.link_button("기사 보기", article["url"])
else:
      st.info("📬 뉴스 데이터를 기다리는 중입니다. GitHub Actions가 실행되면 자동으로 채워집니다.")

st.divider()
st.caption("© HR News Dashboard | Powered by GitHub Actions + Streamlit Community Cloud")

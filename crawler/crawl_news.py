import requests
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
import feedparser

# ========================================================
# HR 뉴스 크롤러
# 이 파일을 실제 크롤링 대상에 맞게 수정하세요.
# ========================================================

RSS_FEEDS = [
      # HR/노무 관련 RSS 피드 URL을 이골에 추가하세요
      # 예시: "https://www.hrdkorea.or.kr/rss",
]


def fetch_rss_articles(feed_url):
      """RSS 피드에서 기사 수집"""
  articles = []
      try:
  feed = feedparser.parse(feed_url)
  for entry in feed.entries[:10]:  # 최대 10개
    articles.append({
        "title": entry.get("title", ""),
        "url": entry.get("link", ""),
        "summary": entry.get("summary", "")[:300],
        "date": entry.get("published", ""),
        "source": feed.feed.get("title", feed_url)
        })
        except Exception as e:
    print(f"[ERROR] RSS 수집 실패 ({feed_url}): {e}")
        return articles


    def save_data(articles):
          """news_data.json 저장"""
          # 크롤러는 프로젝트 루트에서 실행되므로 경로를 루트 기준으로 설정
      script_dir = os.path.dirname(os.path.abspath(__file__))
      root_dir = os.path.dirname(script_dir)
      output_path = os.path.join(root_dir, "news_data.json")

          data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
                "articles": articles
      }

      with open(output_path, "w", encoding="utf-8") as f:
      json.dump(data, f, ensure_ascii=False, indent=2)

      print(f"[INFO] {len(articles)}개 기사 저장 완료 -> {output_path}")


      def main():
        print("[INFO] HR 뉴스 크롤링 시작...")
        all_articles = []

            for feed_url in RSS_FEEDS:
          print(f"[INFO] 수집 중: {feed_url}")
          articles = fetch_rss_articles(feed_url)
          all_articles.extend(articles)
          print(f"[INFO] {len(articles)}개 수집")

              # 중복 URL 제거
          seen_urls = set()
          unique_articles = []
              for article in all_articles:
            if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

            save_data(unique_articles)
            print(f"[INFO] 크롤링 완료. 전체 {len(unique_articles)}개 기사")


            if __name__ == "__main__":
            main()
            

import requests
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
import feedparser

# ========================================================
# HR 뉴스 크롤러 
# ========================================================
RSS_FEEDS = [
    # 테스트용: 구글 뉴스 RSS (키워드: HR, 인사, 노무)
    "https://news.google.com/rss/search?q=HR+%EC%9D%B8%EC%82%AC+%EB%85%B8%EB%AC%B4&hl=ko&gl=KR&ceid=KR:ko",
    # 테스트용: 구글 뉴스 RSS (키워드: 고용노동부)
    "https://news.google.com/rss/search?q=%EA%B3%A0%EC%9A%A9%EB%85%B8%EB%8F%99%EB%B6%80&hl=ko&gl=KR&ceid=KR:ko"
]

def fetch_rss_articles(feed_url):
    """RSS 피드에서 기사 수집"""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            articles.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),          # app.py와 동기화 (url -> link)
                "summary": entry.get("summary", "")[:300],
                "pubDate": entry.get("published", ""),  # app.py와 동기화 (date -> pubDate)
                "source": feed.feed.get("title", "Google News (HR/노무)"), # 기본 출처명 지정
                "category": "HR/노무" # 기본 카테고리 추가
            })
    except Exception as e:
        print(f"[ERROR] RSS 실패 ({feed_url}): {e}")
    return articles

def save_data(articles):
    """news_data.json 저장"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    output_path = os.path.join(root_dir, "news_data.json")
    
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        "articles": articles
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"[INFO] {len(articles)}개 저장 -> {output_path}")

def main():
    print("[INFO] HR 뉴스 크롤링 시작...")
    all_articles = []
    for feed_url in RSS_FEEDS:
        print(f"[INFO] 수집 중: {feed_url}")
        articles = fetch_rss_articles(feed_url)
        all_articles.extend(articles)
        print(f"[INFO] {len(articles)}개 수집")
        
    seen_urls = set()
    unique_articles = []
    
    for article in all_articles:
        # 중복 검사 로직도 'link' 키를 사용하도록 수정
        if article["link"] not in seen_urls:
            seen_urls.add(article["link"])
            unique_articles.append(article)
            
    save_data(unique_articles)
    print(f"[INFO] 완료. 총 {len(unique_articles)}개의 고유 기사 저장됨")

if __name__ == "__main__":
    main()

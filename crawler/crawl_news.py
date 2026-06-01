import requests
import json
import os
from datetime import datetime
import feedparser
import difflib  # 텍스트 유사도 비교를 위한 라이브러리

# ========================================================
# HR 뉴스 크롤러 (카테고리 자동 분류 & 중복 제거 & 누적 기능)
# ========================================================
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=HR+%EC%9D%B8%EC%82%AC+%EB%85%B8%EB%AC%B4&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=%EA%B3%A0%EC%9A%A9%EB%85%B8%EB%8F%99%EB%B6%80&hl=ko&gl=KR&ceid=KR:ko",
    # 판례 및 테크 관련 결과를 더 잘 가져오기 위해 검색어 추가
    "https://news.google.com/rss/search?q=%EB%85%B8%EB%8F%99+%ED%8C%90%EB%8F%84+%ED%8C%90%EB%A1%80+%EB%8C%80%EB%B2%95%EC%9B%90&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=HR+%ED%85%8C%ED%81%AC+AI+%ED%94%8C%EB%9E%AB%ED%8F%BC&hl=ko&gl=KR&ceid=KR:ko"
]

def categorize_article(title, summary):
    """제목과 요약의 키워드를 분석하여 4가지 카테고리로 자동 분류합니다."""
    text = f"{title} {summary}".lower()
    
    # 1. 판례
    if any(kw in text for kw in ["대법원", "판결", "판례", "소송", "선고", "법원", "위법", "합법", "근로기준법 위반"]):
        return "⚖️ 판례"
    # 2. 테크
    elif any(kw in text for kw in ["ai", "플랫폼", "솔루션", "saas", "디지털", "소프트웨어", "도입", "시스템", "앱", "스타트업", "데이터"]):
        return "💻 테크"
    # 3. 아티클
    elif any(kw in text for kw in ["칼럼", "기고", "트렌드", "전략", "세미나", "리포트", "분석", "인사이트"]):
        return "📝 아티클"
    # 4. 뉴스 (기본값)
    else:
        return "📰 뉴스"

def is_similar(title1, title2, threshold=0.65):
    """두 제목의 유사도가 threshold(기본 65%) 이상이면 True를 반환합니다."""
    return difflib.SequenceMatcher(None, title1, title2).ratio() > threshold

def fetch_rss_articles(feed_url):
    """RSS 피드에서 기사를 수집하고 카테고리를 부여합니다."""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:15]:  # 피드당 상위 15개 수집
            title_raw = entry.get("title", "")
            # 구글 뉴스는 '제목 - 언론사명' 형태이므로 언론사명 분리
            clean_title = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
            summary = entry.get("summary", "")[:300]
            
            # 카테고리 자동 할당
            category = categorize_article(clean_title, summary)
            
            articles.append({
                "title": clean_title.strip(),
                "link": entry.get("link", ""),
                "summary": summary,
                "pubDate": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", "Google 뉴스"),
                "category": category
            })
    except Exception as e:
        print(f"[ERROR] RSS 실패 ({feed_url}): {e}")
    return articles

def load_existing_data(filepath):
    """기존에 누적된 JSON 데이터를 불러옵니다."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("articles", [])
        except Exception:
            return []
    return []

def main():
    print("[INFO] HR 뉴스 크롤링 시작...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    output_path = os.path.join(root_dir, "news_data.json")
    
    # 1. 기존 데이터 로드 (매일 누적을 위해)
    existing_articles = load_existing_data(output_path)
    print(f"[INFO] 기존 저장된 기사 수: {len(existing_articles)}개")
    
    # 2. 새로운 기사 수집
    new_articles = []
    for feed_url in RSS_FEEDS:
        articles = fetch_rss_articles(feed_url)
        new_articles.extend(articles)
        
    # 3. 중복 제거 (기존 데이터 + 신규 데이터 통합)
    # 신규 데이터를 먼저 넣어 최신 상태를 유지
    all_articles = new_articles + existing_articles 
    unique_articles = []
    seen_links = set()
    
    for article in all_articles:
        link = article["link"]
        title = article["title"]
        
        # URL이 완전히 같으면 패스
        if link in seen_links:
            continue
            
        # 제목 유사도 검사로 복붙 도배 기사 걸러내기
        is_duplicate = False
        for unique_art in unique_articles:
            if is_similar(title, unique_art["title"]):
                is_duplicate = True
                break
                
        if not is_duplicate:
            seen_links.add(link)
            unique_articles.append(article)
            
    # 누적 데이터가 무한정 커지는 것을 방지 (최신 150개만 유지)
    unique_articles = unique_articles[:150]

    # 4. JSON 파일 저장
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        "articles": unique_articles
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"[INFO] 완료. 총 {len(unique_articles)}개의 고유 기사가 누적/저장되었습니다.")

if __name__ == "__main__":
    main()

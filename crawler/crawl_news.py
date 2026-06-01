import os
import json
import requests
from datetime import datetime
import feedparser
import difflib
# 최신 Google GenAI SDK 임포트
from google import genai
from google.genai import types

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=HR+%EC%9D%B8%EC%82%AC+%EB%85%B8%EB%AC%B4&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=%EA%B3%A0%EC%9A%A9%EB%85%B8%EB%8F%99%EB%B6%80&hl=ko&gl=KR&ceid=KR:ko"
]

# 클라이언트 초기화 (환경 변수에서 GEMINI_API_KEY를 자동으로 인식합니다)
client = genai.Client()

def analyze_news_with_gemini(title, summary):
    """Gemini API를 활용하여 뉴스를 문맥에 맞게 분류하고 실무 인사이트를 도출합니다."""
    prompt = f"""
    당신은 10년 차 시니어 HR 대기업 인사팀장 및 노무사입니다. 
    다음 뉴스 데이터를 읽고 실무자들을 위한 대시보드용 데이터로 정제해 주세요.
    
    [기사 제목]: {title}
    [기사 요약]: {summary}
    
    반드시 아래 구조의 JSON 포맷으로만 답변하세요. 다른 설명은 생략합니다:
    {{
      "category": "노동법/판례", "HR테크/AI", "채용/조직문화", "보상/평가", "고용노동부 정책" 중 가장 적절한 것 1개 선택,
      "clean_summary": "원문 요약을 바탕으로 실무자가 알기 쉽게 정제한 2~3문장의 핵심 요약",
      "novelty_impact": "기존 제도나 관행과 비교했을 때 이 뉴스가 가지는 실무적 임팩트나 차별점",
      "action_point": ["HR 담당자가 당장 확인하거나 조치해야 할 행동 지침 1", "행동 지침 2"]
    }}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"  # 엄격한 JSON 출력 보장
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[API ERROR] Gemini 분석 실패: {e}")
        return None

def is_similar(title1, title2, threshold=0.65):
    return difflib.SequenceMatcher(None, title1, title2).ratio() > threshold

def fetch_rss_articles():
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:  # 효율적인 API 사용을 위해 상위 10개 타겟팅
                title_raw = entry.get("title", "")
                clean_title = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
                summary = entry.get("summary", "")[:300]
                
                articles.append({
                    "title": clean_title.strip(),
                    "link": entry.get("link", ""),
                    "summary": summary,
                    "pubDate": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", "Google 뉴스")
                })
        except Exception as e:
            print(f"[ERROR] RSS 수집 실패: {e}")
    return articles

def main():
    print("[INFO] Gemini 기반 HR 뉴스 모니터링 크롤러 가동...")
    
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../news_data.json")
    
    # 1. 신규 기사 긁어오기
    raw_articles = fetch_rss_articles()
    
    # 2. 중복 제거 알고리즘 및 Gemini 분석 연동
    unique_articles = []
    seen_links = set()
    
    for art in raw_articles:
        if art["link"] in seen_links: continue
        
        is_duplicate = False
        for unique_art in unique_articles:
            if is_similar(art["title"], unique_art["title"]):
                is_duplicate = True
                break
                
        if not is_duplicate:
            seen_links.add(art["link"])
            
            # 여기서 Gemini API를 호출하여 구조화된 데이터 획득
            print(f"[AI 분석 중] {art['title'][:20]}...")
            ai_analysis = analyze_news_with_gemini(art["title"], art["summary"])
            
            if ai_analysis:
                # 기사 기본 정보와 AI 분석본 결합
                full_data = {
                    "title": f"[{ai_analysis.get('category', '기타')}] {art['title']}",
                    "source": f"{art['source']} | {art['link']}",
                    "summary": ai_analysis.get("clean_summary", art["summary"]),
                    "novelty_impact": ai_analysis.get("novelty_impact", "기존 체제 유지"),
                    "action_point": ai_analysis.get("action_point", ["내부 규정 모니터링"])
                }
                unique_articles.append(full_data)

    # 3. 데이터 저장
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(unique_articles, f, ensure_ascii=False, indent=2)
        
    print(f"[INFO] 완료. 총 {len(unique_articles)}개의 이슈가 Gemini를 통해 자동 가공 및 저장되었습니다.")

if __name__ == "__main__":
    main()

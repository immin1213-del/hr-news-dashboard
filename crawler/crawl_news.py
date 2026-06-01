import os
import json
import time
from datetime import datetime
import feedparser
import difflib
from google import genai
from google.genai import types

# 1. 키워드 오타 수정 및 소스 다변화 (판례, 아티클 검색 최적화)
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=HR+%EC%9D%B8%EC%82%AC+%EB%85%B8%EB%AC%B4+%ED%8A%B8%EB%A0%8C%EB%93%9C&hl=ko&gl=KR&ceid=KR:ko",       # HR 인사 노무 트렌드
    "https://news.google.com/rss/search?q=%EA%B3%A0%EC%9A%A9%EB%85%B8%EB%8F%99%EB%B6%80+%EB%B3%B4%EB%8F%84%EC%9E%A0%EB%A3%8C&hl=ko&gl=KR&ceid=KR:ko", # 고용노동부 보도자료
    "https://news.google.com/rss/search?q=%EB%85%B8%EB%8F%99%EB%B2%95+%EB%8C%85%EB%B2%95%EC%9B%90+%ED%8C%90%EB%A1%80&hl=ko&gl=KR&ceid=KR:ko",         # 노동법 대법원 판례 (오타 수정)
    "https://news.google.com/rss/search?q=HR+%ED%85%8C%ED%81%AC+AI+%ED%94%8C%EB%9E%AB%ED%8F%BC&hl=ko&gl=KR&ceid=KR:ko"                       # HR 테크 AI 플랫폼
]

client = genai.Client()

def load_existing_data(filepath):
    """기존 저장된 뉴스 배열을 안전하게 로드합니다."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def analyze_news_with_gemini(title, summary):
    """Gemini API를 호출하여 카테고리 및 실무 관전 포인트를 추출합니다."""
    prompt = f"""
    당신은 10년 차 대기업 인사팀장 및 노무사입니다. 다음 뉴스를 읽고 인사 실무자를 위한 대시보드용 데이터로 정제하세요.
    [제목]: {title}
    [요약]: {summary}
    
    반드시 아래 구조의 JSON 포맷으로만 답변하세요. 다른 부연 설명은 일절 생략합니다:
    {{
      "category": "노동법/판례", "HR테크/AI", "채용/조직문화", "보상/평가", "고용노동부 정책" 중 가장 적절한 것 1개 선택,
      "clean_summary": "실무자가 알기 쉽게 정제한 2~3문장의 핵심 요약",
      "novelty_impact": "이 뉴스가 가지는 실무적 임팩트나 차별점",
      "action_point": ["HR 담당자가 점검하거나 조치해야 할 가이드 1", "가이드 2"]
    }}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[API ERROR] Gemini 패스 (에러 원인: {e})")
        return None

def is_similar(title1, title2, threshold=0.65):
    return difflib.SequenceMatcher(None, title1, title2).ratio() > threshold

def main():
    print("[INFO] 개선된 Gemini 기반 HR 뉴스 크롤러 가동...")
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../news_data.json")
    
    # 1. 히스토리 유지를 위해 기존 누적 데이터 로드
    existing_articles = load_existing_data(output_path)
    print(f"[INFO] 현재 저장되어 있는 기존 기사: {len(existing_articles)}개")
    
    # 2. 신규 RSS 기사 수집
    new_raw_articles = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]: # 소스가 늘어났으므로 피드당 8개씩 타겟팅
                title_raw = entry.get("title", "")
                clean_title = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
                new_raw_articles.append({
                    "title": clean_title.strip(),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:300],
                    "source": entry.get("source", {}).get("title", "Google 뉴스")
                })
        except Exception as e:
            print(f"[ERROR] RSS 파싱 실패: {e}")

    # 3. 중복 검사 및 순차적 Gemini 분석 진행
    unique_articles = []
    # 중복 체크의 기준 풀(Pool)을 기존 데이터까지 확장
    all_combined = existing_articles.copy() 
    
    for art in new_raw_articles:
        # URL 중복 체크
        if any(art["link"] in item.get("source", "") for item in all_combined):
            continue
            
        # 제목 유사도 중복 체크
        if any(is_similar(art["title"], item["title"]) for item in all_combined):
            continue
            
        print(f"[AI 분석 시작] {art['title'][:25]}...")
        ai_analysis = analyze_news_with_gemini(art["title"], art["summary"])
        
        if ai_analysis:
            full_data = {
                "title": f"[{ai_analysis.get('category', '기타')}] {art['title']}",
                "source": f"{art['source']} | {art['link']}",
                "summary": ai_analysis.get("clean_summary", art["summary"]),
                "novelty_impact": ai_analysis.get("novelty_impact", "기존 체제 유지"),
                "action_point": ai_analysis.get("action_point", ["내부 규정 모니터링"])
            }
            unique_articles.append(full_data)
            all_combined.insert(0, full_data) # 최신 뉴스를 앞쪽에 배치
            
            # 🔥 [핵심] Gemini 무료 티어 RPM 제한(15번)을 피하기 위해 안전하게 4.5초간 대기합니다.
            time.sleep(4.5)

    # 4. 최신 기사 + 기존 기사 통합 후 최대 100개까지만 유지
    final_dataset = (unique_articles + existing_articles)[:100]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_dataset, f, ensure_ascii=False, indent=2)
        
    print(f"[INFO] 완료! 이번 루프에서 {len(unique_articles)}개의 뉴스가 추가되어 총 {len(final_dataset)}개가 저장되었습니다.")

if __name__ == "__main__":
    main()

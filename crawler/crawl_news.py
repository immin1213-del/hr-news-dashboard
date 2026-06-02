import os
import json
import time
from datetime import datetime
import feedparser
import difflib
from google import genai
from google.genai import types

# =========================================================
#  HR 뉴스 종합 크롤러 (Gemini 멀티키 2-Stage Pipeline)
#  - 여러 Gemini API 키를 환경변수로 받아 카테고리별로 분배
#  - 무료 티어(키당 20건/일) 한도를 키 개수만큼 확장
#  - 키가 429(한도초과)면 다음 사용 가능한 키로 자동 폴백
#  ※ 키 값은 코드에 하드코딩하지 않고 환경변수 이름만 참조
# =========================================================

CATEGORIES = [
    "고용노동부 정책",
    "노동법/판례",
    "보상/평가",
    "채용/조직문화",
    "HR테크/AI",
    "글로벌 HR 트렌드",
]

# 소스: (RSS URL, 지역, 기본 카테고리 힌트)
RSS_FEEDS = [
    ("https://news.google.com/rss/search?q=%EA%B3%A0%EC%9A%A9%EB%85%B8%EB%8F%99%EB%B6%80+%EB%B3%B4%EB%8F%84%EC%9E%90%EB%A3%8C&hl=ko&gl=KR&ceid=KR:ko", "국내", "고용노동부 정책"),
    ("https://news.google.com/rss/search?q=%EB%85%B8%EB%8F%99%EB%B2%95+%EB%8C%80%EB%B2%95%EC%9B%90+%ED%8C%90%EA%B2%B0&hl=ko&gl=KR&ceid=KR:ko", "국내", "노동법/판례"),
    ("https://news.google.com/rss/search?q=HR+%EC%9D%B8%EC%82%AC+%EB%85%B8%EB%AC%B4+%ED%8A%B8%EB%A0%8C%EB%93%9C&hl=ko&gl=KR&ceid=KR:ko", "국내", "채용/조직문화"),
    ("https://news.google.com/rss/search?q=%EC%9E%84%EA%B8%88+%EB%B3%B4%EC%83%81+%EC%84%B1%EA%B3%BC%ED%8F%89%EA%B0%80+%EC%9D%B8%EC%82%AC&hl=ko&gl=KR&ceid=KR:ko", "국내", "보상/평가"),
    ("https://news.google.com/rss/search?q=HR%ED%85%8C%ED%81%AC+AI+%EC%9D%B8%EC%82%AC%EA%B4%80%EB%A6%AC+%ED%94%8C%EB%9E%AB%ED%8F%BC&hl=ko&gl=KR&ceid=KR:ko", "국내", "HR테크/AI"),
    ("https://news.google.com/rss/search?q=HR+human+resources+workforce+when:7d&hl=en-US&gl=US&ceid=US:en", "해외", "글로벌 HR 트렌드"),
    ("https://news.google.com/rss/search?q=HR+technology+AI+talent+management&hl=en-US&gl=US&ceid=US:en", "해외", "HR테크/AI"),
    ("https://news.google.com/rss/search?q=recruiting+employee+engagement+leadership&hl=en-US&gl=US&ceid=US:en", "해외", "채용/조직문화"),
]

PER_FEED_LIMIT = 6
MAX_ARTICLES = 100
GEMINI_MODEL = "gemini-2.5-flash"
SLEEP_SEC = 4.5


def load_api_keys():
    """환경변수에서 여러 Gemini 키를 수집한다.
    지원 형식: GEMINI_API_KEY (단일), GEMINI_API_KEY_1 ~ GEMINI_API_KEY_20.
    """
    keys = []
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        keys.append(single)
    for i in range(1, 21):
        v = os.environ.get(f"GEMINI_API_KEY_{i}")
        if v and v not in keys:
            keys.append(v)
    return keys


class KeyPool:
    """카테고리별로 키를 배정하고, 429 발생 시 다음 키로 폴백한다."""

    def __init__(self, keys):
        if not keys:
            raise RuntimeError("사용 가능한 Gemini API 키가 없습니다. Secrets를 확인하세요.")
        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.exhausted = [False] * len(keys)
        # 카테고리 -> 시작 키 인덱스 (라운드로빈 분배)
        self.cat_index = {
            cat: (idx % len(keys)) for idx, cat in enumerate(CATEGORIES)
        }

    def available_count(self):
        return self.exhausted.count(False)

    def generate(self, category, prompt):
        """해당 카테고리의 기본 키부터 시작해 사용 가능한 키를 순회하며 호출."""
        n = len(self.clients)
        start = self.cat_index.get(category, 0)
        for offset in range(n):
            idx = (start + offset) % n
            if self.exhausted[idx]:
                continue
            try:
                resp = self.clients[idx].models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                return json.loads(resp.text), idx
            except Exception as e:
                msg = str(e)
                if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                    print(f"[KEY {idx+1}] 일일 한도 소진 → 다음 키로 폴백")
                    self.exhausted[idx] = True
                    continue
                print(f"[KEY {idx+1}] 호출 오류: {e}")
                time.sleep(SLEEP_SEC)
        return None, -1


def load_existing_data(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "articles" in data:
                    return data.get("articles", [])
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def build_prompt(title, summary, region, hint):
    cat_list = ", ".join(CATEGORIES)
    return f"""당신은 10년 차 대기업 인사팀장이자 노무사입니다.
다음 HR 관련 뉴스를 인사 실무자용 대시보드 데이터로 정제하세요.
원문이 영어 등 외국어이면 반드시 한국어로 번역·요약하세요.

[지역]: {region}
[참고 카테고리 힌트]: {hint}
[제목]: {title}
[요약 원문]: {summary}

아래 JSON 포맷으로만 답변하세요(다른 설명 금지).
"category" 는 반드시 다음 중 정확히 하나만 사용: {cat_list}
{{
  "category": "위 목록 중 가장 적절한 1개",
  "clean_title": "한국어로 정제한 간결한 제목",
  "clean_summary": "실무자가 이해하기 쉬운 2~3문장 한국어 핵심 요약",
  "novelty_impact": "이 뉴스의 실무적 임팩트나 차별점 1문장",
  "action_point": ["HR 담당자 점검/조치 가이드1", "가이드2"]
}}"""


def is_similar(title1, title2, threshold=0.65):
    return difflib.SequenceMatcher(None, title1, title2).ratio() > threshold


def main():
    print("[INFO] Gemini 멀티키 HR 뉴스 종합 크롤러 가동...")
    keys = load_api_keys()
    print(f"[INFO] 로드된 Gemini 키 개수: {len(keys)}개 (이론상 최대 {len(keys)*20}건/일)")
    pool = KeyPool(keys)

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "../news_data.json"
    )

    existing_articles = load_existing_data(output_path)
    print(f"[INFO] 기존 누적 기사: {len(existing_articles)}개")

    new_raw = []
    for feed_url, region, hint in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:PER_FEED_LIMIT]:
                title_raw = entry.get("title", "")
                clean = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
                new_raw.append({
                    "title": clean.strip(),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:400],
                    "source_name": entry.get("source", {}).get("title", "Google 뉴스"),
                    "region": region,
                    "hint": hint,
                })
        except Exception as e:
            print(f"[ERROR] RSS 파싱 실패({region}): {e}")

    print(f"[INFO] 신규 원문 수집: {len(new_raw)}개")

    unique_articles = []
    all_combined = existing_articles.copy()

    for art in new_raw:
        if pool.available_count() == 0:
            print("[STOP] 모든 키의 일일 한도 소진 → 수집 중단")
            break
        if art["link"] and any(art["link"] == item.get("link", "") for item in all_combined):
            continue
        if any(is_similar(art["title"], item.get("title", "")) for item in all_combined):
            continue

        prompt = build_prompt(art["title"], art["summary"], art["region"], art["hint"])
        print(f"[AI 정제] ({art['region']}) {art['title'][:30]}...")
        ai, used_idx = pool.generate(art["hint"], prompt)
        if not ai:
            continue

        category = ai.get("category", art["hint"])
        if category not in CATEGORIES:
            category = art["hint"]
        full = {
            "title": ai.get("clean_title", art["title"]),
            "category": category,
            "region": art["region"],
            "link": art["link"],
            "source": art["source_name"],
            "summary": ai.get("clean_summary", art["summary"]),
            "novelty_impact": ai.get("novelty_impact", ""),
            "action_point": ai.get("action_point", []),
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        unique_articles.append(full)
        all_combined.insert(0, full)
        time.sleep(SLEEP_SEC)

    final_articles = (unique_articles + existing_articles)[:MAX_ARTICLES]
    payload = {
        "last_updated": datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST"),
        "articles": final_articles,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 신규 {len(unique_articles)}개 추가 / 총 {len(final_articles)}개 저장 완료.")


if __name__ == "__main__":
    main()

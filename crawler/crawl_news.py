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

def _gn_ko(query):
    """구글 뉴스 RSS (한국어) 검색 URL 생성"""
    return (
        "https://news.google.com/rss/search?q="
        + query
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )


def _gn_en(query):
    """구글 뉴스 RSS (영어) 검색 URL 생성"""
    return (
        "https://news.google.com/rss/search?q="
        + query
        + "&hl=en-US&gl=US&ceid=US:en"
    )


# 소스: (RSS URL, 지역, 기본 카테고리 힌트)
# ※ HR테크/AI 카테고리는 "해외 아티클의 신규 서비스/솔루션" 중심으로 수집한다.
#   국내 고용노동부 HR플랫폼 지원사업 등은 "고용노동부 정책"으로 분류된다.
RSS_FEEDS = [
    # 고용노동부 보도자료 · 정책 (최근 30일)
    (_gn_ko("고용노동부 보도자료 when:30d"), "국내", "고용노동부 정책"),
    (_gn_ko("고용노동부 정책 지원사업 when:30d"), "국내", "고용노동부 정책"),
    # 노동법/판례 (최근 90일 + 현안 이슈)
    (_gn_ko("노동법 대법원 판결 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("통상임금 판결 근로자성 부당해고 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("직장내괴롭힘 임금체불 판례 노동위원회 when:90d"), "국내", "노동법/판례"),
    # 보상/평가
    (_gn_ko("임금 보상 성과평가 인사"), "국내", "보상/평가"),
    # 채용/조직문화
    (_gn_ko("HR 인사 노무 채용 조직문화 트렌드"), "국내", "채용/조직문화"),
    # 글로벌 HR 트렌드 (해외)
    (_gn_en("HR human resources workforce trend when:7d"), "해외", "글로벌 HR 트렌드"),
    # HR테크/AI - 해외 신규 서비스/솔루션 중심
    (_gn_en("new HR tech AI startup launch product when:14d"), "해외", "HR테크/AI"),
    (_gn_en("HR technology AI talent management platform"), "해외", "HR테크/AI"),
    (_gn_en("recruiting employee engagement leadership"), "해외", "채용/조직문화"),
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

[카테고리 분류 규칙 - 반드시 준수]
- "고용노동부 정책": 고용노동부·정부 부처의 보도자료, 정책·제도·지원사업·공모·선정 발표, 공공기관 사업. 국내 고용노동부 HR플랫폼 구축지원 등 정부 주도 사업은 'HR테크/AI'가 아니라 반드시 이 카테고리에 넣으시오.
- "노동법/판례": 법원 판결·판례, 노동위원회 판정, 법개정, 통상임금·근로자성·직장내괴롭힘 등 법적 쟁점.
- "보상/평가": 임금·보상쳋계·성과평가·인사평가 제도.
- "채용/조직문화": 채용·조직문화·리더십·교육.
- "HR테크/AI": 주로 해외에서 새로 나온 HR 기술·AI 서비스·솔루션·스타트업·제품 출시 등 신규 서비스 중심. 국내 정부/공공기관의 HR플랫폼 지원사업은 제외(이건 '고용노동부 정책').
- "글로벌 HR 트렌드": 해외 HR 동향·문화·제도 트렌드(특정 신규 제품/솔루션이 아닌 경우).

[관련성 필터 - 보도자료 등 선별]
- 고용노동부 보도자료는 HR 실무자(인사·노무 담당자)가 참고할 만한 내용인지 판단하시오. 채용·임금·근로조건·안전보건·지원금·제도변경 등 실무 영향이 있으면 포함.
- 단순 행사·수상·의례적 소식 등 실무 관련성이 낮으면 "relevant": false 로 표시.

아래 JSON 포맷으로만 답변하세요(다른 설명 금지).
"category" 는 반드시 다음 중 정확히 하나만 사용: {cat_list}
{{
  "category": "위 목록 중 가장 적절한 1개",
  "clean_title": "한국어로 정제한 간결한 제목",
  "clean_summary": "실무자가 이해하기 쉬운 2~3문장 한국어 핵심 요약",
  "novelty_impact": "이 뉴스의 실무적 임팩트나 차별점 1문장",
  "action_point": ["HR 담당자 점검/조치 가이돜1", "가이돜2"],
  "relevant": true
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

    # 누적 보존 + 중복/유사 방지
    # all_combined: 기존 + 이번 회차 신규를 합친 전체 (중복 판단용)
    unique_articles = []
    all_combined = existing_articles.copy()
    seen_links = {item.get("link", "") for item in all_combined if item.get("link")}

    for art in new_raw:
        if pool.available_count() == 0:
            print("[STOP] 모든 키의 일일 한도 소진 → 수집 중단")
            break
        # 1) URL 완전 중복 제거
        if art["link"] and art["link"] in seen_links:
            continue
        # 2) 제목 유사도 기반 중복 제거 (기존 누적 분과 비교)
        if any(is_similar(art["title"], item.get("title", "")) for item in all_combined):
            continue
        # 3) 이번 회차 신규분 간 중복도 제거
        if any(is_similar(art["title"], u["title"]) for u in unique_articles):
            continue

        prompt = build_prompt(art["title"], art["summary"], art["region"], art["hint"])
        print(f"[AI 정제] ({art['region']}) {art['title'][:30]}...")
        ai, used_idx = pool.generate(art["hint"], prompt)
        if not ai:
            continue

        # 4) 실무 관련성 필터 (보도자료 등 선별)
        if ai.get("relevant", True) is False:
            print(f"[SKIP] 실무 관련성 낮음 → 제외: {art['title'][:30]}")
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
        if full["link"]:
            seen_links.add(full["link"])
        time.sleep(SLEEP_SEC)

    print(f"[INFO] 이번 회차 신규 누적: {len(unique_articles)}개")

    # 신규를 앞에 두고 기존과 합쳐 누적 (최대 MAX_ARTICLES)
    final_articles = (unique_articles + existing_articles)[:MAX_ARTICLES]
    payload = {
        "last_updated": datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST"),
        "articles": final_articles,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[DONE] 총 {len(final_articles)}개 기사 저장 → {output_path}")


if __name__ == "__main__":
    main()

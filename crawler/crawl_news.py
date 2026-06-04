import os
import re
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import feedparser
import difflib
from google import genai
from google.genai import types

# =========================================================
# HR 뉴스 종합 크롤러 (Gemini 멀티키 2-Stage Pipeline) - v2 고도화
#  1) logging 모듈 기반 추적 시스템 (터미널 + system.log)
#  2) scraped_at 필드 (수집 날짜) 스키마 추가
#  3) 스마트 중복/심화 콘텐츠 업데이트·병합 로직
# =========================================================

# ---------------------------------------------------------
# 1. 로깅 시스템 구축
# ---------------------------------------------------------
def setup_logger():
    log_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "system.log"
    )
    logger = logging.getLogger("hr_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


log = setup_logger()

CATEGORIES = [
    "고용노동부 정책",
    "노동법/판례",
    "보상/평가",
    "채용/조직문화",
    "HR테크/AI",
    "글로벌 HR 트렌드",
]

# 심화(후속) 보도를 시사하는 키워드 - 새 판례 결과/확정/수치 등
ENRICH_KEYWORDS = [
    "선고", "확정", "대법원", "판결", "판정", "최종", "항소", "상고",
    "개정", "시행", "결정", "발표", "추가", "정정", "후속", "속보",
]


def _gn_ko(query):
    return "https://news.google.com/rss/search?q=" + query + "&hl=ko&gl=KR&ceid=KR:ko"


def _gn_en(query):
    return "https://news.google.com/rss/search?q=" + query + "&hl=en-US&gl=US&ceid=US:en"


RSS_FEEDS = [
    (_gn_ko("고용노동부 보도자료 when:30d"), "국내", "고용노동부 정책"),
    (_gn_ko("고용노동부 정책 지원사업 when:30d"), "국내", "고용노동부 정책"),
    (_gn_ko("노동법 대법원 판결 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("통상임금 판결 근로자성 부당해고 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("직장내괴롭힘 임금체불 판례 노동위원회 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("임금 보상 성과평가 인사"), "국내", "보상/평가"),
    (_gn_ko("HR 인사 노무 채용 조직문화 트렌드"), "국내", "채용/조직문화"),
    (_gn_en("HR human resources workforce trend when:7d"), "해외", "글로벌 HR 트렌드"),
    (_gn_en("new HR tech AI startup launch product when:14d"), "해외", "HR테크/AI"),
    (_gn_en("HR technology AI talent management platform"), "해외", "HR테크/AI"),
    (_gn_en("recruiting employee engagement leadership"), "해외", "채용/조직문화"),
]

PER_FEED_LIMIT = 6
MAX_ARTICLES = 100
GEMINI_MODEL = "gemini-2.5-flash"
SLEEP_SEC = 4.5


def load_api_keys():
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
        self.cat_index = {cat: (idx % len(keys)) for idx, cat in enumerate(CATEGORIES)}

    def available_count(self):
        return self.exhausted.count(False)

    def generate(self, category, prompt):
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
                    log.warning(f"[KEY {idx+1}] 일일 한도 소진 -> 다음 키로 폴백")
                    self.exhausted[idx] = True
                    continue
                log.error(f"[KEY {idx+1}] 호출 오류: {e}")
                time.sleep(SLEEP_SEC)
        return None, -1


def load_existing_data(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "articles" in data:
                log.info(f"기존 JSON 로드 성공 -> {len(data.get('articles', []))}건")
                return data.get("articles", [])
            return data if isinstance(data, list) else []
        except Exception as e:
            log.error(f"기존 JSON 파일 I/O 에러 -> 빈 목록으로 시작: {e}")
            return []
    log.info("기존 JSON 파일 없음 -> 신규 생성 모드")
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
- "고용노동부 정책": 정부 부처 보도자료, 정책·제도·지원사업·공모·선정 발표, 공공기관 사업. 정부 주도 HR플랫폼 지원사업은 'HR테크/AI'가 아니라 반드시 이 카테고리.
- "노동법/판례": 법원 판결·판례, 노동위원회 판정, 법개정, 통상임금·근로자성·직장내괴롭힘 등 법적 쟁점.
- "보상/평가": 임금·보상체계·성과평가·인사평가 제도.
- "채용/조직문화": 채용·조직문화·리더십·교육.
- "HR테크/AI": 해외에서 새로 나온 HR 기술·AI 서비스·솔루션·스타트업·제품 출시 등 신규 서비스 중심.
- "글로벌 HR 트렌드": 해외 HR 동향·문화·제도 트렌드.

[관련성 필터]
- 채용·임금·근로조건·안전보건·지원금·제도변경 등 실무 영향이 있으면 포함.
- 단순 행사·수상·의례적 소식 등 실무 관련성이 낮으면 "relevant": false.

아래 JSON 포맷으로만 답변하세요(다른 설명 금지).
"category" 는 반드시 다음 중 정확히 하나만 사용: {cat_list}
{{
  "category": "위 목록 중 가장 적절한 1개",
  "clean_title": "한국어로 정제한 간결한 제목",
  "clean_summary": "실무자가 이해하기 쉬운 2~3문장 한국어 핵심 요약",
  "novelty_impact": "이 뉴스의 실무적 임팩트나 차별점 1문장",
  "action_point": ["HR 담당자 점검/조치 가이드1", "가이드2"],
  "relevant": true
}}"""


# ---------------------------------------------------------
# 3. 스마트 중복 / 심화 콘텐츠 처리 로직
# ---------------------------------------------------------
def _tokens(text):
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", (text or "").lower()))


def title_ratio(a, b):
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def jaccard(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_same_issue(new_item, existing, title_th=0.65, body_th=0.45):
    """기존 항목 중 '같은 이슈'를 다루는 항목의 인덱스를 반환(없으면 -1)."""
    nt, ns = new_item["title"], new_item.get("summary", "")
    for i, old in enumerate(existing):
        t_sim = title_ratio(nt, old.get("title", ""))
        b_sim = jaccard(ns, old.get("summary", ""))
        if t_sim >= title_th:
            return i
        if t_sim >= 0.45 and b_sim >= body_th:
            return i
    return -1


def is_enriched(new_item, old_item):
    """같은 이슈일 때, 신규가 '심화/후속'인지 판정."""
    new_sum = new_item.get("summary", "") or ""
    old_sum = old_item.get("summary", "") or ""
    if len(new_sum) > len(old_sum) * 1.15:
        return True
    if len(new_item.get("action_point", [])) > len(old_item.get("action_point", [])):
        return True
    blob_new = (new_item.get("title", "") + new_sum + new_item.get("novelty_impact", ""))
    blob_old = (old_item.get("title", "") + old_sum + old_item.get("novelty_impact", ""))
    for kw in ENRICH_KEYWORDS:
        if kw in blob_new and kw not in blob_old:
            return True
    return False


def merge_articles(old_item, new_item):
    """심화 판정 시 더 풍부한 필드를 채택해 병합한다(이력 보존)."""
    merged = dict(old_item)
    if len(new_item.get("summary", "")) > len(old_item.get("summary", "")):
        merged["summary"] = new_item["summary"]
    if new_item.get("novelty_impact"):
        merged["novelty_impact"] = new_item["novelty_impact"]
    seen, union = set(), []
    for a in (old_item.get("action_point", []) + new_item.get("action_point", [])):
        if a and a not in seen:
            seen.add(a)
            union.append(a)
    merged["action_point"] = union
    merged["title"] = new_item.get("title", old_item.get("title"))
    if new_item.get("link"):
        merged["link"] = new_item["link"]
    merged["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    merged["revision"] = int(old_item.get("revision", 0)) + 1
    return merged


def main():
    log.info("=" * 60)
    log.info("Gemini 멀티키 HR 뉴스 종합 크롤러(v2) 가동")
    keys = load_api_keys()
    log.info(f"로드된 Gemini 키 개수: {len(keys)}개 (이론상 최대 {len(keys)*20}건/일)")
    try:
        pool = KeyPool(keys)
    except RuntimeError as e:
        log.critical(str(e))
        return

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "../news_data.json"
    )
    existing_articles = load_existing_data(output_path)
    log.info(f"기존 누적 기사: {len(existing_articles)}개")

    new_raw = []
    for feed_url, region, hint in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
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
                count += 1
            log.info(f"RSS 파싱 OK ({region}/{hint}): {count}건")
        except Exception as e:
            log.error(f"RSS 파싱 실패({region}/{hint}): {e}")

    log.info(f"신규 원문 수집 총합: {len(new_raw)}개")

    working = existing_articles.copy()
    seen_links = {it.get("link", "") for it in working if it.get("link")}
    stat = {"new": 0, "merged": 0, "dup": 0, "skip": 0, "ai_fail": 0}

    for art in new_raw:
        if pool.available_count() == 0:
            log.warning("모든 키의 일일 한도 소진 -> 수집 중단")
            break

        if art["link"] and art["link"] in seen_links:
            stat["dup"] += 1
            log.info(f"[DUP-URL] 동일 링크 폐기: {art['title'][:34]}")
            continue

        prompt = build_prompt(art["title"], art["summary"], art["region"], art["hint"])
        log.info(f"[AI 정제] ({art['region']}) {art['title'][:30]}...")
        ai, used_idx = pool.generate(art["hint"], prompt)
        if not ai:
            stat["ai_fail"] += 1
            log.warning(f"[AI 실패] 정제 결과 없음 -> 스킵: {art['title'][:30]}")
            continue

        if ai.get("relevant", True) is False:
            stat["skip"] += 1
            log.info(f"[SKIP] 실무 관련성 낮음 -> 제외: {art['title'][:30]}")
            time.sleep(SLEEP_SEC)
            continue

        category = ai.get("category", art["hint"])
        if category not in CATEGORIES:
            category = art["hint"]

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        candidate = {
            "title": ai.get("clean_title", art["title"]),
            "category": category,
            "region": art["region"],
            "link": art["link"],
            "source": art["source_name"],
            "summary": ai.get("clean_summary", art["summary"]),
            "novelty_impact": ai.get("novelty_impact", ""),
            "action_point": ai.get("action_point", []),
            "collected_at": now_str,
            "scraped_at": now_str,
            "revision": 0,
        }

        idx = find_same_issue(candidate, working)
        if idx == -1:
            working.insert(0, candidate)
            if candidate["link"]:
                seen_links.add(candidate["link"])
            stat["new"] += 1
            log.info(f"[NEW] 신규 기사 추가: {candidate['title'][:34]}")
        else:
            old = working[idx]
            if is_enriched(candidate, old):
                working[idx] = merge_articles(old, candidate)
                if candidate["link"]:
                    seen_links.add(candidate["link"])
                stat["merged"] += 1
                log.info(
                    f"[MERGE] 심화 콘텐츠 병합(rev {working[idx]['revision']}): "
                    f"{candidate['title'][:34]}"
                )
            else:
                stat["dup"] += 1
                log.info(f"[DUP-SAME] 동일 이슈·심화 없음 -> 폐기: {candidate['title'][:30]}")

        time.sleep(SLEEP_SEC)

    log.info(
        f"처리 통계 -> 신규 {stat['new']} / 병합 {stat['merged']} / "
        f"중복폐기 {stat['dup']} / 관련성스킵 {stat['skip']} / AI실패 {stat['ai_fail']}"
    )

    final_articles = working[:MAX_ARTICLES]
    payload = {
        "last_updated": datetime.now().strftime("%Y년 %m월 %d일 %H:%M KST"),
        "articles": final_articles,
    }
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info(f"[DONE] 총 {len(final_articles)}개 기사 저장 -> {output_path}")
    except Exception as e:
        log.critical(f"파일 저장 I/O 에러: {e}")


if __name__ == "__main__":
    main()

import os
import re
import json
import time
import logging
import hashlib
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
import feedparser
import difflib
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from google import genai
from google.genai import types

# =========================================================
# HR 뉴스 종합 크롤러 (Gemini 멀티키 2-Stage Pipeline) - v3
# v2 기능: logging / scraped_at / 스마트 중복·심화 병합
# v3 개선:
#   (A) 해외 아티클 미수집 문제 해결
#       - 피드를 '라운드로빈'으로 인터리빙 처리하여 키 소진이
#         특정(해외) 피드를 굶기지 않도록 함
#       - 해외 최소 처리량(MIN_OVERSEAS) 예약
#       - 해외 콘텐츠는 관련성 필터로 자동 폐기하지 않음
#   (B) 다층 데이터 소스 확충 (사용자 요청 반영)
#       - 노동계(매일노동뉴스·경총·양대노총 성명), 법령·입법(국회·중노위),
#         대법원 최신 판례, HR테크(SaaS 동향) 레이어 추가
# =========================================================

# ---------------------------------------------------------
# 1. 로깅 시스템
# ---------------------------------------------------------
def setup_logger():
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system.log")
    logger = logging.getLogger("hr_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger

log = setup_logger()

CATEGORIES = [
    "고용노동부 정책",
    "노동법/판례",
    "노사관계/노동계",
    "보상/평가",
    "채용/조직문화",
    "HR테크/AI",
    "글로벌 HR 트렌드",
]

# =========================================================
# [v10] 분류 후처리 가드: 집단적 노사관계(노조·파업·임단협·경총 등) 기사가
# 다른 카테고리로 새는 것을 코드 레벨에서 강제 교정한다.
# (AI 프롬프트의 최우선 배타 규칙을 결정적 키워드로 한 번 더 보장)
# =========================================================
# 노사관계 '활동/주체' 신호 — 이게 핵심이면 무조건 '노사관계/노동계'
LABOR_RELATIONS_KEYWORDS = (
    "노동조합", "노조", "민주노총", "한국노총", "양대노총", "산별노조",
    "총파업", "파업", "쟁의", "단체교섭", "단체협약", "임단협",
    "노사 갈등", "노사갈등", "집회", "결의대회", "경총",
)
# 법원/입법 '쟁점' 신호 — 이게 핵심이면 노조 언급이 있어도 '노동법/판례' 유지
LEGAL_PRECEDENCE_KEYWORDS = (
    "대법원", "전원합의체", "판결", "판례", "선고", "헌법재판소", "헌재",
    "위헌", "합헌", "법원", "노동위원회 판정",
)

def enforce_labor_relations_category(category, blob):
    """집단적 노사관계 활동이 핵심인 기사를 '노사관계/노동계'로 강제 교정.
    단, 법원 판결·판례·입법 쟁점이 핵심이면 '노동법/판례'를 존중한다."""
    if category == "노사관계/노동계":
        return category
    has_lr = any(k in blob for k in LABOR_RELATIONS_KEYWORDS)
    if not has_lr:
        return category
    # 법령/판례가 본질이면(노동법/판례로 분류된 경우 한정) 교정하지 않음
    if category == "노동법/판례" and any(k in blob for k in LEGAL_PRECEDENCE_KEYWORDS):
        return category
    return "노사관계/노동계"

ENRICH_KEYWORDS = [
    "선고", "확정", "대법원", "판결", "판정", "최종", "항소", "상고",
    "개정", "시행", "결정", "발표", "추가", "정정", "후속", "속보",
]

# =========================================================
# 보완 패치 설정
# =========================================================
FRESHNESS_DAYS = 14          # 발행일이 이보다 오래된 기사는 신규 수집에서 제외
NEW_BADGE_DAYS = 3           # 대시보드 'NEW' 배지를 붙일 최근 일수
TIME_WINDOW_DAYS = 21        # 같은 이슈로 묶을 발행일 허용 시간창
SEEN_INDEX_FILE = "../seen_index.json"   # 영구 dedup 지문 저장소
SEEN_INDEX_MAX = 5000        # 지문 보관 최대 개수(오래된 것부터 정리)

# 트래킹 파라미터(여기 있는 쿼리는 URL 정규화 시 제거)
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "refid", "ref_src", "fbclid", "gclid", "spm", "from", "cmpid",
}

# =========================================================
# 중요(핵심) 뉴스 보호 + 정밀 중복 판정용 사전
# v4: 포괄적 키워드로 누락 방지 + 이슈 시그니처로 중복 정밀화
# =========================================================

# (1) 주요 법령/제도 — 포괄적으로. 누락 시 여기에 한 줄만 추가하면 됨.
IMPORTANT_LAWS = [
    "근로기준법", "노동조합법", "노동조합 및 노동관계조정법", "노조법",
    "노란봉투법", "최저임금법", "최저임금", "남녀고용평등법",
    "기간제법", "파견법", "산업안전보건법", "산안법",
    "중대재해처벌법", "중대재해 처벌법", "고용보험법", "고용보험",
    "퇴직급여보장법", "퇴직연금", "근로자퇴직급여", "임금채권보장법",
    "고령자고용법", "정년연장", "정년 연장", "외국인고용법",
    "직장 내 괴롭힘", "직장내괴롭힘", "통상임금", "주 52시간", "주52시간",
    "육아휴직", "모성보호", "일·가정 양립", "일가정양립", "노동법",
]

# (2) 입법/행정 '단계' 키워드 — 어느 단계의 뉴스인지 구분(중복 판정 핵심)
LEGISLATION_STAGES = [
    "발의", "상정", "소위", "법사위", "환노위", "상임위",
    "본회의", "의결", "통과", "가결", "부결", "재의", "거부권",
    "공포", "개정", "제정", "시행령", "시행규칙", "시행", "입법예고",
]

# (3) 그 외 보호 대상 일반 중요 시그널
IMPORTANT_SIGNALS = [
    "국회", "본회의", "대법원 전원합의체", "전원합의체", "헌법재판소",
    "위헌", "합헌", "정부 발표", "고시", "행정해석",
]

# 보호 판정용 통합 키워드 집합
IMPORTANT_KEYWORDS = IMPORTANT_LAWS + LEGISLATION_STAGES + IMPORTANT_SIGNALS

def _imp_blob(item):
    return " ".join([
        item.get("title", "") or "",
        item.get("summary", "") or "",
        item.get("clean_title", "") or "",
        item.get("clean_summary", "") or "",
        item.get("novelty_impact", "") or "",
    ])

def is_important(item):
    """중요(보호 대상) 기사 여부: 주요 법령 언급 또는 (입법단계어 + 국회/사법 시그널)."""
    blob = _imp_blob(item)
    has_law = any(k in blob for k in IMPORTANT_LAWS)
    has_stage = any(k in blob for k in LEGISLATION_STAGES)
    has_signal = any(k in blob for k in IMPORTANT_SIGNALS)
    return has_law or (has_stage and has_signal)

def issue_signature(item):
    """중요 기사의 '사건 단위' 식별자: (법령명 집합, 단계 집합).
    같은 법령의 같은 단계 = 같은 사건 -> 정밀 중복 처리."""
    blob = _imp_blob(item)
    laws = frozenset(k for k in IMPORTANT_LAWS if k in blob)
    stages = frozenset(k for k in LEGISLATION_STAGES if k in blob)
    return (laws, stages)

def is_important_feed(region, hint):
    """입법/정책성 피드(국내 노동법/판례, 고용노동부 정책)는 더 깊게 수집."""
    return region == "국내" and hint in ("노동법/판례", "고용노동부 정책")

# ---------------------------------------------------------
# (A) 발행일 파싱 / (B) 신선도 / (C) URL·콘텐츠 지문 헬퍼
# ---------------------------------------------------------
def _parse_published(entry):
    """RSS entry에서 실제 발행일(UTC, ISO)을 최대한 복원. 없으면 None."""
    for key in ("published_parsed", "updated_parsed"):
        tp = entry.get(key)
        if tp:
            try:
                dt = datetime(*tp[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return None

def _is_fresh(published_at_iso, max_days=FRESHNESS_DAYS):
    """발행일이 max_days 이내면 True. 발행일을 모르면 보수적으로 True(버리지 않음)."""
    if not published_at_iso:
        return True  # 날짜 불명 기사는 일단 통과시키되 date_basis로 구분
    try:
        dt = datetime.fromisoformat(published_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) <= timedelta(days=max_days)
    except Exception:
        return True

def normalize_url(url):
    """트래킹 파라미터 제거 + 소문자 호스트 + fragment 제거로 URL 정규화."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in _TRACKING_PARAMS]
        return urlunsplit((
            parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
            urlencode(q), ""  # fragment 제거
        ))
    except Exception:
        return url

def _norm_text(s):
    """공백·기호·따옴표 제거 후 소문자화(지문용)."""
    if not s:
        return ""
    return re.sub(r"[\s\W_]+", "", s).lower()

def content_fingerprint(item):
    """제목+요약 정규화 해시. 같은 사건이면 같은 지문이 나오도록."""
    basis = _norm_text(item.get("title", "")) + "|" + _norm_text(item.get("summary", ""))[:120]
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()

def _within_time_window(a, b, days=TIME_WINDOW_DAYS):
    """두 기사의 발행일이 days 이내로 가까운지. 한쪽이라도 날짜 없으면 True(기존 동작 유지)."""
    pa, pb = a.get("published_at"), b.get("published_at")
    if not pa or not pb:
        return True
    try:
        da = datetime.fromisoformat(pa); db = datetime.fromisoformat(pb)
        if da.tzinfo is None: da = da.replace(tzinfo=timezone.utc)
        if db.tzinfo is None: db = db.replace(tzinfo=timezone.utc)
        return abs((da - db).days) <= days
    except Exception:
        return True

# ---------------------------------------------------------
# (D) 영구 dedup 인덱스 로드/저장
# ---------------------------------------------------------
def load_seen_index(base_dir):
    path = os.path.join(base_dir, SEEN_INDEX_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("urls", [])), set(data.get("fps", []))
    except Exception:
        return set(), set()

def save_seen_index(base_dir, seen_urls, seen_fps):
    path = os.path.join(base_dir, SEEN_INDEX_FILE)
    # 최신 것 우선으로 상한 유지
    urls = list(seen_urls)[-SEEN_INDEX_MAX:]
    fps = list(seen_fps)[-SEEN_INDEX_MAX:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"urls": urls, "fps": fps}, f, ensure_ascii=False, indent=2)

def _gn_ko(query):
    return "https://news.google.com/rss/search?q=" + quote(query) + "&hl=ko&gl=KR&ceid=KR:ko"

def _gn_en(query):
    return "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en"

# 소스: (RSS URL, 지역, 기본 카테고리 힌트)
# === (B) 다층 데이터 소스 ===
RSS_FEEDS = [
    # --- 고용노동부 정책 레이어 ---
    (_gn_ko("고용노동부 보도자료 when:30d"), "국내", "고용노동부 정책"),
    (_gn_ko("고용노동부 정책 지원사업 지침 when:30d"), "국내", "고용노동부 정책"),
    # --- 노동법/판례 레이어 (법원·중노위·입법) ---
    # [v4] 핵심 입법 누락 방지: 국회 본회의 통과/주요 법령 개정 전용 쿼리
    (_gn_ko("근로기준법 개정 국회 본회의 통과 when:30d"), "국내", "노동법/판례"),
    (_gn_ko("국회 본회의 노동 법안 의결 통과 when:14d"), "국내", "노동법/판례"),
    # [v9] 매일 아침 입법 확정 트래킹: 환노위·본회의 통과 전용(짧은 기간)
    (_gn_ko("국회 환경노동위원회 고용 노동 법안 통과 when:7d"), "국내", "노동법/판례"),
    (_gn_ko("최저임금 중대재해처벌법 정년연장 노동법 개정 when:60d"), "국내", "노동법/판례"),
    (_gn_ko("노동법 대법원 판결 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("통상임금 판결 근로자성 부당해고 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("직장내괴롭힘 임금체불 판례 노동위원회 판정 when:90d"), "국내", "노동법/판례"),
    (_gn_ko("노란봉투법 노동조합법 개정 입법 when:60d"), "국내", "노동법/판례"),
    (_gn_ko("중앙노동위원회 부당해고 구제 판정 when:90d"), "국내", "노동법/판례"),
    # --- 노사관계/노동계 레이어 (양대노총·경총·쟁의·단체교섭) ---
    # [v9] 노조·총파업·집회 등 집단적 노사관계는 전용 카테고리로 격리
    (_gn_ko("한국노총 민주노총 총파업 집회 when:14d"), "국내", "노사관계/노동계"),
    (_gn_ko("노사 단체교섭 임단협 쟁의 파업 when:14d"), "국내", "노사관계/노동계"),
    (_gn_ko("한국경영자총협회 경총 노동 성명 when:30d"), "국내", "노사관계/노동계"),
    (_gn_ko("매일노동뉴스 노조 노사관계 when:14d"), "국내", "노사관계/노동계"),
    # --- 보상/평가 레이어 ---
    (_gn_ko("임금 보상체계 성과급 인사평가 when:30d"), "국내", "보상/평가"),
    # --- 채용/조직문화 레이어 ---
    (_gn_ko("기업 채용 트렌드 채용 계획 수시채용 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("이직률 리텐션 인재 유지 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("기업문화 사내문화 조직문화 개선 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("온보딩 인재개발 사내교육 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("리더십 조직개발 매니지먼트 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("고용 브랜드 채용 브랜딩 일하기 좋은 기업 when:30d"), "국내", "채용/조직문화"),
    (_gn_ko("유연근무 재택근무 워라밸 사내복지 when:30d"), "국내", "채용/조직문화"),
    # --- HR테크 레이어 (국내 SaaS 동향) ---
    (_gn_ko("플렉스 원티드 HR SaaS 솔루션 도입 when:30d"), "국내", "HR테크/AI"),
    # =====================================================
    # === 해외 레이어 (영어) — v3에서 강화/우선처리 ===
    # =====================================================
    (_gn_en("HR human resources workforce trend when:14d"), "해외", "글로벌 HR 트렌드"),
    (_gn_en("future of work hybrid workplace policy when:14d"), "해외", "글로벌 HR 트렌드"),
    (_gn_en("SHRM HR Dive employee benefits compensation when:14d"), "해외", "글로벌 HR 트렌드"),
    (_gn_en("new HR tech AI startup launch product when:21d"), "해외", "HR테크/AI"),
    (_gn_en("HR technology AI talent management platform when:21d"), "해외", "HR테크/AI"),
    (_gn_en("AI recruiting employee engagement HR software when:21d"), "해외", "HR테크/AI"),
]

PER_FEED_LIMIT = 6
IMPORTANT_FEED_LIMIT = 12  # [v4] 입법/정책 피드는 더 깊게 수집해 핵심 뉴스 누락 방지
MAX_ARTICLES = 120
MIN_OVERSEAS = 8  # (A) 해외 최소 보장 처리량
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"  # [v8] 503 과부하 시 대체 모델
SLEEP_SEC = 0.5
CALL_INTERVAL_SEC = 0.5  # [v6] 유료 티어 전환: RPM 여유로 페이싱 단축
MAX_RETRY_PER_KEY = 2  # [v5] 분당 한도/일시 오류 시 같은 키 재시도 횟수
RETRY_WAIT_SEC = 8  # [v7] 분당 한도(RPM/429) 시 대기(초)
RETRY_BASE_SEC = 2  # [v7] 503(모델 과부하) 지수 백오프 기본값(초)

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
    def __init__(self, keys):
        if not keys:
            raise RuntimeError("사용 가능한 Gemini API 키가 없습니다. Secrets를 확인하세요.")
        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.exhausted = [False] * len(keys)
        self.last_call = [0.0] * len(keys)  # [v5] 키별 마지막 호출 시각(RPM 페이싱)
        self.cat_index = {cat: (idx % len(keys)) for idx, cat in enumerate(CATEGORIES)}

    def available_count(self):
        return self.exhausted.count(False)

    @staticmethod
    def _is_per_minute_limit(msg):
        # 429 메시지가 분당 한도(RPM)인지 일일 한도(RPD)인지 구분
        low = msg.lower()
        compact = low.replace(" ", "")
        # 강한 일일 신호: Gemini quotaId/메트릭에 들어오는 PerDay 계열은 명시적 일일 한도.
        # (예: GenerateRequestsPerDayPerProjectPerModel-FreeTier, *_per_day,
        #  free_tier_requests 일일 카운터) -> retryDelay 힌트보다 우선.
        strong_per_day = ("perday" in compact or "requestsperday" in compact or
                          "perdayperproject" in compact or
                          "free_tier_requests" in compact or
                          "freetierrequests" in compact)
        if strong_per_day:
            return False
        # 강한 분당 신호
        strong_per_min = ("perminute" in compact or "requestsperminute" in compact or
                          "perminuteperproject" in compact or "/min" in low)
        if strong_per_min:
            return True
        # 약한 신호(일일/분당 키워드만 등장)
        weak_per_day = ("daily" in low or "/day" in low)
        weak_per_min = ("retrydelay" in compact or "retry in" in low)
        if weak_per_day and not weak_per_min:
            return False
        # 그 외 모호한 429: 보수적으로 분당으로 간주(키 보존)
        return True

    def _pace(self, idx):
        # [v5] 분당 한도(RPM) 보호: 같은 키 호출 간 최소 간격 확보
        wait = CALL_INTERVAL_SEC - (time.time() - self.last_call[idx])
        if wait > 0:
            time.sleep(wait)

    def generate(self, category, prompt):
        n = len(self.clients)
        start = self.cat_index.get(category, 0)
        for offset in range(n):
            idx = (start + offset) % n
            if self.exhausted[idx]:
                continue
            give_up_key = False
            # [v8] 503(모델 과부하)는 키가 아니라 모델 문제 -> 기본 실패 시 라이트로 폴백
            for model in (GEMINI_MODEL, GEMINI_MODEL_FALLBACK):
                last_was_503 = False
                for attempt in range(MAX_RETRY_PER_KEY + 1):
                    self._pace(idx)
                    try:
                        resp = self.clients[idx].models.generate_content(
                            model=model,
                            contents=prompt,
                            config=types.GenerateContentConfig(response_mime_type="application/json"),
                        )
                        self.last_call[idx] = time.time()
                        return json.loads(resp.text), idx
                    except Exception as e:
                        self.last_call[idx] = time.time()
                        msg = str(e)
                        is_429 = ("RESOURCE_EXHAUSTED" in msg or "429" in msg)
                        is_503 = ("UNAVAILABLE" in msg or "503" in msg)
                        last_was_503 = is_503
                        if is_429 and not self._is_per_minute_limit(msg):
                            log.warning(f"[KEY {idx+1}] 일일 한도(RPD) 소진 -> 키 폐기 후 폴백")
                            self.exhausted[idx] = True
                            give_up_key = True
                            break
                        if (is_429 or is_503) and attempt < MAX_RETRY_PER_KEY:
                            wait_sec = RETRY_WAIT_SEC if is_429 else RETRY_BASE_SEC * (2 ** attempt)
                            kind = "분당 한도(RPM)" if is_429 else "일시 오류(503)"
                            log.warning(f"[KEY {idx+1}] {kind}[{model}] -> {wait_sec}s 대기 후 재시도 ({attempt+1}/{MAX_RETRY_PER_KEY})")
                            time.sleep(wait_sec)
                            continue
                        log.error(f"[KEY {idx+1}] 호출 오류[{model}]: {e}")
                        break
                if give_up_key:
                    break
                if last_was_503 and model == GEMINI_MODEL:
                    log.warning(f"[KEY {idx+1}] 503 과부하 지속 -> 대체 모델({GEMINI_MODEL_FALLBACK}) 전환")
                    time.sleep(0.3)
                    continue
                time.sleep(0.3)
                break
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
    overseas_note = ""
    if region == "해외":
        overseas_note = (
            "\n[해외 콘텐츠 특별 지침]\n"
            "- 이 기사는 해외 소스입니다. 한국 인사담당자가 글로벌 트렌드/기술을 파악하는 용도이므로, "
            "국내 실무 직접 적용성이 낮더라도 'relevant'를 함부로 false 로 두지 마십시오. "
            "명백한 광고/홍보성 단순 보도가 아니라면 relevant=true 로 두십시오.\n"
            "- 카테고리는 신규 제품/솔루션이면 'HR테크/AI', 동향/문화/제도면 '글로벌 HR 트렌드'."
        )
    return f"""당신은 10년 차 대기업 인사팀장이자 노무사입니다.
다음 HR 관련 뉴스를 인사 실무자용 대시보드 데이터로 정제하세요.
원문이 영어 등 외국어이면 반드시 한국어로 번역·요약하세요.

[지역]: {region}
[참고 카테고리 힌트]: {hint}
[제목]: {title}
[요약 원문]: {summary}{overseas_note}

[카테고리 분류 규칙 - 반드시 준수]
- [최우선 배타 규칙] 노동조합·노조·양대노총(한국노총·민주노총)·총파업·파업·집회·쟁의·단체교섭·임단협(노사 협상)·경총 성명 등 '집단적 노사관계'가 기사의 핵심이면, 다른 어떤 카테고리보다 우선해 반드시 "노사관계/노동계"로 분류한다.
- "고용노동부 정책": 오직 고용노동부(및 그 산하·소속기관: 근로복지공단, 산업안전보건공단, 고용센터 등)가 주체인 보도자료·정책·제도·지원사업·공모·선정 발표만 해당.
- [중요] 중소벤처기업부(중기부)·소상공인시장진흥공단 등 다른 부처/기관이 주체인 기사는 절대 "고용노동부 정책"로 분류하지 말 것.
- "노동법/판례": 법원 판결·판례, 노동위원회 판정, 국회의 노동 관련 법개정·입법(노조법 등 법안의 발의·통과·공포), 통상임금·근로자성·직장내괴롭힘 등 법적 쟁점. (※ 노조의 파업·집회 같은 '활동'은 여기가 아니라 "노사관계/노동계".)
- "노사관계/노동계": 노동조합·노동계(양대노총·산별노조)·경영계(경총) 동향, 총파업·파업·집회·쟁의행위, 노사 단체교섭·임단협 협상, 노사 갈등·합의 등 집단적 노사관계 이슈.
- "보상/평가": 개별 기업/직무의 임금·보상체계·성과급·연봉·인사평가 제도 설계.
- "채용/조직문화": 채용·인재확보·온보딩·조직문화·리더십·사내교육·HR 제도 운영 등 '개별 기업 내부' 인사 이슈. (※ 노조·파업·노사관계는 여기에 절대 넣지 말 것.)
- "HR테크/AI": 새로 나온 HR 기술·AI 서비스·솔루션·SaaS·스타트업·제품 출시 등 신규 서비스 중심.
- "글로벌 HR 트렌드": 해외 HR 동향·문화·제도 트렌드(특정 신규 제품/솔루션이 아닌 경우).

[관련성 필터]
- 국내 보도자료는 채용·임금·근로조건·안전보건·지원금·제도변경 등 실무 영향이 있으면 포함.
- 단순 행사·수상·의례적 소식 등 실무 관련성이 낮으면 "relevant": false.
- (단, 해외 콘텐츠는 위 [해외 콘텐츠 특별 지침]을 우선 적용)

[action_point 작성 지침]
- "고용노동부 정책" 및 "노동법/판례"(특히 국회 입법 통과) 기사는 action_point에 반드시 HR 담당자의 사규·근로계약서·취업규칙·노무 실무 점검 포인트(예: 규정 개정 필요 여부, 적용 시점, 대상 근로자)를 1개 이상 포함.

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
# 스마트 중복 / 심화 콘텐츠 처리
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


def find_same_issue(new_item, existing, title_th=0.55, body_th=0.35):
    nt, ns = new_item["title"], new_item.get("summary", "")
    nt_tok = _tokens(nt)
    new_important = is_important(new_item)
    new_sig = issue_signature(new_item) if new_important else None
    for i, old in enumerate(existing):
        ot = old.get("title", "")

        # [v4] 중요 기사: 이슈 시그니처(법령+단계)로 정밀 비교
        if new_important and is_important(old):
            new_laws, new_stages = new_sig
            old_laws, old_stages = issue_signature(old)
            if new_laws & old_laws:
                # 단계가 양쪽에 있는데 서로 겹치지 않으면 서로 다른 사건이므로 병합 금지
                if new_stages and old_stages and not (new_stages & old_stages):
                    continue
                # 같은 법령 + 같은 단계면 제목 표현이 달라도 같은 사건
                if new_stages and (new_stages & old_stages):
                    return i
                # 같은 법령 + 한쪽 단계 미상 + 제목/본문 어느 정도 유사면 같은 사건
                if title_ratio(nt, ot) >= 0.40 or jaccard(ns, old.get("summary", "")) >= 0.25:
                    return i
            # 중요 기사끼리는 느슨한 토큰 겹침 규칙 미적용(과잉 병합 방지)
            continue

        # 일반 기사: 기존 로직 유지
        t_sim = title_ratio(nt, ot)
        b_sim = jaccard(ns, old.get("summary", ""))
        if t_sim >= title_th:
            return i
        if t_sim >= 0.40 and b_sim >= body_th:
            return i
        # 보조 판정: 제목 핵심어가 많이 겹치면 같은 이슈로 간주
        # (한국어 조사로 SequenceMatcher 점수가 낮게 나오는 경우 보완)
        ot_tok = _tokens(ot)
        if nt_tok and ot_tok:
            key_overlap = len(nt_tok & ot_tok) / min(len(nt_tok), len(ot_tok))
            if key_overlap >= 0.6 and (nt_tok & ot_tok):
                return i
    return -1


def is_enriched(new_item, old_item):
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


# ---------------------------------------------------------
# (A) 피드 인터리빙: 해외/국내를 라운드로빈으로 섞어
#     키 소진이 특정 지역을 굶기지 않게 한다.
# ---------------------------------------------------------
def collect_raw():
    buckets = {"해외": [], "국내": []}
    for feed_url, region, hint in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            cnt = 0
            feed_limit = IMPORTANT_FEED_LIMIT if is_important_feed(region, hint) else PER_FEED_LIMIT
            for entry in feed.entries[:feed_limit]:
                title_raw = entry.get("title", "")
                clean = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw
                buckets[region].append({
                    "title": clean.strip(),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:400],
                    "source_name": entry.get("source", {}).get("title", "Google 뉴스"),
                    "region": region,
                    "hint": hint,
                })
                cnt += 1
            log.info(f"RSS 파싱 OK ({region}/{hint}): {cnt}건")
        except Exception as e:
            log.error(f"RSS 파싱 실패({region}/{hint}): {e}")

    # 라운드로빈 인터리빙: 해외를 먼저 배치해 최소 보장
    interleaved = []
    ov, dom = buckets["해외"], buckets["국내"]
    i = j = 0
    while i < len(ov) or j < len(dom):
        if i < len(ov):
            interleaved.append(ov[i]); i += 1
        if j < len(dom):
            interleaved.append(dom[j]); j += 1
    log.info(f"수집 원문 -> 해외 {len(ov)} / 국내 {len(dom)} (인터리빙 적용)")
    return interleaved


def main():
    log.info("=" * 60)
    log.info("Gemini 멀티키 HR 뉴스 종합 크롤러(v3) 가동")
    keys = load_api_keys()
    log.info(f"로드된 Gemini 키 개수: {len(keys)}개 (이론상 최대 {len(keys)*20}건/일)")
    try:
        pool = KeyPool(keys)
    except RuntimeError as e:
        log.critical(str(e))
        return

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../news_data.json")
    existing_articles = load_existing_data(output_path)
    log.info(f"기존 누적 기사: {len(existing_articles)}개")

    new_raw = collect_raw()
    log.info(f"신규 원문 수집 총합: {len(new_raw)}개")

    working = existing_articles.copy()
    seen_links = {it.get("link", "") for it in working if it.get("link")}
    stat = {"new": 0, "merged": 0, "dup": 0, "skip": 0, "ai_fail": 0, "overseas_new": 0, "important": 0}

    for art in new_raw:
        is_overseas = art["region"] == "해외"
        # (A) 키가 소진돼도 해외 최소 보장량은 끝까지 시도
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

        # [v4] 중요 기사 여부: 원문 + AI 정제 결과 모두 반영
        merged_for_check = {**art, **(ai or {})}
        important = is_important(merged_for_check)

        # (A) 관련성 false 처리: 해외 최소보장 + (v4) 국내 핵심 입법/정책 보존
        if ai.get("relevant", True) is False:
            if important:
                log.info(f"[중요 보존] 관련성 낮음이나 핵심 입법/정책 -> 유지: {art['title'][:30]}")
            elif is_overseas and stat["overseas_new"] < MIN_OVERSEAS:
                log.info(f"[해외 보존] 관련성 낮음이나 최소량 미달 -> 유지: {art['title'][:30]}")
            else:
                stat["skip"] += 1
                log.info(f"[SKIP] 실무 관련성 낮음 -> 제외: {art['title'][:30]}")
                time.sleep(SLEEP_SEC)
                continue

        category = ai.get("category", art["hint"])
        if category not in CATEGORIES:
            category = art["hint"]

        # [v10] 노조·파업·임단협·경총 등 집단적 노사관계 기사 강제 교정
        _lr_blob = " ".join([
            ai.get("clean_title", art["title"]) or "",
            ai.get("clean_summary", art["summary"]) or "",
            art.get("title", "") or "",
            art.get("summary", "") or "",
        ])
        _fixed = enforce_labor_relations_category(category, _lr_blob)
        if _fixed != category:
            log.info(f"[분류 교정] {category} -> {_fixed}: {art['title'][:30]}")
            category = _fixed

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
            if is_overseas:
                stat["overseas_new"] += 1
            if important:
                stat["important"] += 1
            log.info(f"[NEW] 신규 기사 추가: {candidate['title'][:34]}")
        else:
            old = working[idx]
            if is_enriched(candidate, old):
                working[idx] = merge_articles(old, candidate)
                if candidate["link"]:
                    seen_links.add(candidate["link"])
                stat["merged"] += 1
                if important:
                    stat["important"] += 1
                log.info(f"[MERGE] 심화 콘텐츠 병합(rev {working[idx]['revision']}): {candidate['title'][:34]}")
            else:
                stat["dup"] += 1
                log.info(f"[DUP-SAME] 동일 이슈·심화 없음 -> 폐기: {candidate['title'][:30]}")

        time.sleep(SLEEP_SEC)

    log.info(
        f"처리 통계 -> 신규 {stat['new']}(해외 {stat['overseas_new']}, 중요 {stat['important']}) / "
        f"병합 {stat['merged']} / 중복폐기 {stat['dup']} / 관련성스킵 {stat['skip']} / AI실패 {stat['ai_fail']}"
    )
    if stat["overseas_new"] == 0:
        log.warning("이번 회차 해외 신규 0건 -> 해외 피드/키 한도 점검 필요")
    if stat["important"] == 0:
        log.warning("이번 회차 핵심 입법/정책(중요) 기사 0건 -> RSS 쿼리/키 한도 점검 필요")

    final_articles = working[:MAX_ARTICLES]

    # 신규/병합이 하나도 없으면 last_updated 만 바뀐 '가짜 성공 커밋'을 만들지 않는다.
    changed = (stat["new"] + stat["merged"]) > 0
    if not changed:
        # [v5] 0건의 원인을 구분: 키 전량 소진(쿼터)이면 정상 무처리(exit 0),
        #      키가 남아있는데 0건이면 진짜 실패(RSS 파싱 등)로 보고 exit 1.
        keys_drained = pool.available_count() == 0
        if keys_drained:
            log.warning(
                "신규/병합 0건 + 모든 키 한도 소진 -> news_data.json 미갱신(정상 무처리). "
                "쿼터 회복 후 다음 실행에서 재수집됩니다."
            )
            raise SystemExit(0)
        log.error(
            "신규/병합 0건(키 잔여 있음) -> news_data.json 미갱신. "
            "RSS 파싱 실패 등 실제 문제 가능성. 로그를 확인하세요."
        )
        # 비정상 종료로 GitHub Actions 에 실패를 노출 (가짜 녹색 체크 방지)
        raise SystemExit(1)

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
        raise SystemExit(1)


if __name__ == "__main__":
    main()

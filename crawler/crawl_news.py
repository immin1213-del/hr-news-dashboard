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
            "\n[해외 콘텐츠 특별 지

"""
P5 메일 트리아지 엔진
메일 → 분류/점수화 → 이슈 반영 → 승인 파이프라인

Usage:
    python p5_email_triage.py process              # 새 메일 처리
    python p5_email_triage.py process --mail-dir PATH  # 특정 디렉토리에서
    python p5_email_triage.py score --subject "..." --sender "..."  # 점수 테스트
    python p5_email_triage.py report               # 주간 예외 보고서
"""

import re
import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yaml

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
INBOX_DIR = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
TRIAGE_RULES_PATH = VAULT_PATH / "_config" / "p5-triage-rules.yaml"
LOG_FILE = SCRIPT_DIR / "p5_email_triage.log"


# ─── Logging Setup ──────────────────────────────────────────
def setup_logging(debug: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("p5_email_triage")


log = setup_logging()


# ─── Data Classes ───────────────────────────────────────────
@dataclass
class TriageResult:
    """트리아지 결과"""

    sender_org: str = ""
    sender_name: str = ""
    sender_weight: int = 0
    categories: List[str] = field(default_factory=list)
    keywords_hit: List[str] = field(default_factory=list)
    keyword_weight: int = 0
    modifier_weight: int = 0
    total_score: int = 0
    priority: str = "medium"
    matched_issue_id: Optional[str] = None
    match_method: str = ""
    match_confidence: float = 0.0
    escalation_level: str = "L2"
    suggested_action: str = ""
    conversation_id: str = ""
    # ─── Phase 1 Ingest Gate fields ───
    actionability: int = 0
    novelty: int = 0
    duplication_penalty: int = 0
    classification: str = ""  # Action | Decision | Reference | Trash


@dataclass
class EmailData:
    """이메일 데이터"""

    file_path: Path
    subject: str = ""
    sender: str = ""
    sender_email: str = ""
    received_at: str = ""
    body: str = ""
    clean_body: str = ""
    has_attachments: bool = False
    ocr_drawing_refs: List[str] = field(default_factory=list)
    ocr_drawing_confidences: Dict[str, float] = field(default_factory=dict)
    frontmatter: Dict[str, Any] = field(default_factory=dict)


# ─── Rules Loader ───────────────────────────────────────────
class TriageRules:
    """트리아지 규칙 로더"""

    def __init__(self, rules_path: Path = TRIAGE_RULES_PATH):
        self.rules_path = rules_path
        self.rules = self._load_rules()

    def _load_rules(self) -> dict:
        if not self.rules_path.exists():
            log.warning(f"규칙 파일 없음: {self.rules_path}")
            return {}
        try:
            with open(self.rules_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            log.error(f"규칙 로드 실패: {e}")
            return {}

    @property
    def automation_level(self) -> str:
        return self.rules.get("automation_level", "L2")

    @property
    def sender_rules(self) -> dict:
        return self.rules.get("sender_rules", {})

    @property
    def keyword_rules(self) -> dict:
        return self.rules.get("keyword_rules", {})

    @property
    def scoring(self) -> dict:
        return self.rules.get("scoring", {})

    @property
    def issue_matching(self) -> dict:
        return self.rules.get("issue_matching", {})

    @property
    def status_control(self) -> dict:
        return self.rules.get("status_control", {})

    @property
    def sanitization(self) -> dict:
        return self.rules.get("sanitization", {})

    @property
    def noise_filter(self) -> dict:
        return self.rules.get("noise_filter", {})


# ─── Ingest Policy ─────────────────────────────────────────
INGEST_POLICY_PATH = VAULT_PATH / "_config" / "ingest-policy.yaml"

_INGEST_DEFAULTS = {
    "classification": {
        "trash": {"score_threshold": 2, "actionability_threshold": 1},
        "action": {"actionability_threshold": 3},
        "decision": {"requires_action_plan": True, "requires_empty_decision": True},
    },
    "wip": {
        "max_active_issues": 15,
        "overflow_action": "wip_overflow",
        "count_statuses": ["open", "in_progress"],
        "count_priorities": ["high", "critical"],
    },
    "ttl": {"reference_days": 90, "quarantine_days": 7},
    "paths": {
        "quarantine_dir": "ResearchVault/00-Inbox/Quarantine",
        "archive_dir": "ResearchVault/04-Archive",
    },
    "vip_sender_weight_threshold": 3,
    "actionability": {
        "urgent_keyword_bonus": 2,
        "request_keyword_bonus": 1,
        "deadline_mention_bonus": 1,
        "vip_sender_bonus": 1,
        "fyi_keyword_penalty": -1,
        "reply_chain_penalty": -1,
    },
    "novelty": {
        "first_conversation_bonus": 2,
        "new_attachments_bonus": 1,
        "new_drawing_refs_bonus": 1,
        "high_match_confidence_penalty": -1,
        "confidence_threshold": 0.8,
    },
}


class IngestPolicy:
    """Ingest Gate 정책 로더 (ingest-policy.yaml + defaults fallback)"""

    def __init__(self, path: Path = INGEST_POLICY_PATH):
        self._data = self._load(path)

    def _load(self, path: Path) -> dict:
        if not path.exists():
            log.warning(f"Ingest 정책 파일 없음, 기본값 사용: {path}")
            return dict(_INGEST_DEFAULTS)
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # 2중 fallback: 로드 값 우선, 없으면 defaults
            merged = dict(_INGEST_DEFAULTS)
            for k, v in loaded.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            return merged
        except Exception as e:
            log.error(f"Ingest 정책 로드 실패, 기본값 사용: {e}")
            return dict(_INGEST_DEFAULTS)

    @property
    def classification(self) -> dict:
        return self._data.get("classification", _INGEST_DEFAULTS["classification"])

    @property
    def wip(self) -> dict:
        return self._data.get("wip", _INGEST_DEFAULTS["wip"])

    @property
    def ttl(self) -> dict:
        return self._data.get("ttl", _INGEST_DEFAULTS["ttl"])

    @property
    def quarantine_dir(self) -> Path:
        return PROJECT_ROOT / self._data.get("paths", {}).get("quarantine_dir", "ResearchVault/00-Inbox/Quarantine")

    @property
    def archive_dir(self) -> Path:
        return PROJECT_ROOT / self._data.get("paths", {}).get("archive_dir", "ResearchVault/04-Archive")

    @property
    def vip_threshold(self) -> int:
        return self._data.get("vip_sender_weight_threshold", 3)

    @property
    def actionability_rules(self) -> dict:
        return self._data.get("actionability", _INGEST_DEFAULTS["actionability"])

    @property
    def novelty_rules(self) -> dict:
        return self._data.get("novelty", _INGEST_DEFAULTS["novelty"])


# ─── Noise Filter ──────────────────────────────────────────
@dataclass
class NoiseFilterResult:
    """노이즈 필터 결과"""
    disposition: str = "pass"  # pass | noise_blacklist | noise_subject | noise_off_project | noise_duplicate
    reason: str = ""
    conversation_id: str = ""


class NoiseFilter:
    """트리아지 전 단계 노이즈 필터 — 스팸/비관련/중복 제거"""

    def __init__(self, rules: TriageRules):
        nf = rules.noise_filter
        self.enabled = nf.get("enabled", False)
        self._sender_bl = nf.get("sender_blacklist", {})
        self._subject_bl = nf.get("subject_blacklist", [])
        self._scope = nf.get("project_scope", {})
        self._dedup = nf.get("deduplication", {})
        # conversation_id → (file_stem, received_at)
        self._seen: Dict[str, Tuple[str, str]] = {}

    def filter(self, email: EmailData) -> NoiseFilterResult:
        """4단계 필터: sender → subject → scope → dedup"""
        if not self.enabled:
            return NoiseFilterResult(disposition="pass", conversation_id=self._normalize_subject(email.subject))

        # 1. 발신자 블랙리스트
        r = self._check_sender_blacklist(email)
        if r:
            return r

        # 2. 제목 블랙리스트
        r = self._check_subject_blacklist(email)
        if r:
            return r

        # 3. 프로젝트 스코프
        r = self._check_project_scope(email)
        if r:
            return r

        # 4. 대화 중복
        conv_id = self._normalize_subject(email.subject)
        r = self._check_deduplication(email, conv_id)
        if r:
            return r

        return NoiseFilterResult(disposition="pass", conversation_id=conv_id)

    def _check_sender_blacklist(self, email: EmailData) -> Optional[NoiseFilterResult]:
        addr = email.sender_email
        if not addr:
            return None

        # 도메인 블랙리스트
        bl_domains = self._sender_bl.get("domains", [])
        for domain in bl_domains:
            if addr.endswith(f"@{domain}") or addr.endswith(f".{domain}"):
                return NoiseFilterResult(
                    disposition="noise_blacklist",
                    reason=f"sender_domain:{domain}",
                )

        # 패턴 블랙리스트 (noreply@ 등)
        bl_patterns = self._sender_bl.get("patterns", [])
        for pat in bl_patterns:
            if addr.startswith(pat):
                return NoiseFilterResult(
                    disposition="noise_blacklist",
                    reason=f"sender_pattern:{pat}",
                )

        return None

    def _check_subject_blacklist(self, email: EmailData) -> Optional[NoiseFilterResult]:
        subj = email.subject
        for pattern in self._subject_bl:
            try:
                if re.search(pattern, subj, re.IGNORECASE):
                    return NoiseFilterResult(
                        disposition="noise_subject",
                        reason=f"subject_match:{pattern}",
                    )
            except re.error:
                if pattern.lower() in subj.lower():
                    return NoiseFilterResult(
                        disposition="noise_subject",
                        reason=f"subject_match:{pattern}",
                    )
        return None

    def _check_project_scope(self, email: EmailData) -> Optional[NoiseFilterResult]:
        positive_kw = self._scope.get("p5_positive_keywords", [])
        negative_kw = self._scope.get("non_p5_keywords", [])
        text = f"{email.subject} {email.clean_body}"

        has_positive = any(kw.lower() in text.lower() for kw in positive_kw)
        has_negative = any(kw.lower() in text.lower() for kw in negative_kw)

        # 비-P5 키워드만 있고 P5 키워드가 없으면 스킵
        if has_negative and not has_positive:
            action = self._scope.get("off_project_action", "skip")
            if action == "skip":
                return NoiseFilterResult(
                    disposition="noise_off_project",
                    reason="non_p5_keywords_only",
                )
        return None

    def _normalize_subject(self, subject: str) -> str:
        """RE:/FW: 접두사 제거하여 대화 ID 생성"""
        prefixes = self._dedup.get("strip_prefixes", [])
        result = subject.strip()
        # 긴 접두사부터 먼저 제거 (RE: RE: RE: → RE: RE: → RE:)
        for prefix in sorted(prefixes, key=len, reverse=True):
            while result.upper().startswith(prefix.upper()):
                result = result[len(prefix):].strip()
        return result.strip()

    def _check_deduplication(self, email: EmailData, conv_id: str) -> Optional[NoiseFilterResult]:
        if not self._dedup.get("enabled", False):
            return None

        if conv_id in self._seen:
            prev_stem, prev_date = self._seen[conv_id]
            # 최신 유지: 현재가 더 최신이면 이전 것을 대체
            if self._dedup.get("keep_latest_only", True):
                self._seen[conv_id] = (email.file_path.stem, email.received_at)
            return NoiseFilterResult(
                disposition="noise_duplicate",
                reason=f"dup_of:{prev_stem}",
                conversation_id=conv_id,
            )
        else:
            self._seen[conv_id] = (email.file_path.stem, email.received_at)
            return None


# ─── Email Parser ───────────────────────────────────────────
class EmailParser:
    """이메일 파싱 및 정제"""

    def __init__(self, rules: TriageRules):
        self.rules = rules

    def parse_email_file(self, file_path: Path) -> Optional[EmailData]:
        """마크다운 이메일 파일 파싱"""
        try:
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter(content)

            email = EmailData(
                file_path=file_path,
                subject=frontmatter.get("subject", ""),
                sender=frontmatter.get("sender", ""),
                sender_email=self._extract_email(frontmatter.get("sender", "")),
                received_at=frontmatter.get("timestamp", frontmatter.get("date", "")),
                body=body,
                clean_body=self._sanitize_body(body),
                has_attachments="attachments" in frontmatter,
                frontmatter=frontmatter,
            )
            # OCR 도면번호 + 확신도 로드
            ocr_refs, ocr_confs = self._load_ocr_drawings(file_path)
            email.ocr_drawing_refs = ocr_refs
            email.ocr_drawing_confidences = ocr_confs
            return email
        except Exception as e:
            log.error(f"이메일 파싱 실패 ({file_path}): {e}")
            return None

    def _split_frontmatter(self, content: str) -> Tuple[dict, str]:
        """YAML frontmatter와 본문 분리"""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return fm, body
        except Exception:
            return {}, content

    def _extract_email(self, sender_str: str) -> str:
        """발신자 문자열에서 이메일 추출"""
        match = re.search(r"<([^>]+@[^>]+)>", sender_str)
        if match:
            return match.group(1).lower()
        # 이메일 형식 직접 체크
        if "@" in sender_str:
            return sender_str.strip().lower()
        return ""

    @staticmethod
    def _load_ocr_drawings(email_path: Path) -> tuple:
        """이메일에 대응하는 OCR 사이드카 파일에서 도면번호 + 확신도 로드.

        Returns:
            (drawing_refs: List[str], confidences: Dict[str, float])
        """
        attach_dir = email_path.parent / "Attachments" / email_path.stem
        if not attach_dir.exists():
            return [], {}
        drawings = []
        confidences = {}
        for ocr_file in attach_dir.glob("*.ocr.md"):
            try:
                text = ocr_file.read_text(encoding="utf-8")
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end > 0:
                        fm = yaml.safe_load(text[3:end]) or {}
                        for d in fm.get("drawing_numbers", []):
                            if isinstance(d, dict):
                                num = str(d.get("number", ""))
                                try:
                                    conf = float(d.get("confidence", 0.5))
                                except (ValueError, TypeError):
                                    conf = 0.5
                            else:
                                num = str(d)
                                conf = 0.5  # 레거시 포맷
                            if num:
                                drawings.append(num)
                                # 동일 도면이 여러 파일에 있으면 최고값 유지
                                if num not in confidences or conf > confidences[num]:
                                    confidences[num] = conf
            except Exception:
                pass
        return drawings, confidences

    def _sanitize_body(self, body: str) -> str:
        """본문 정제 (RE/FW, 서명, 인용문 제거)"""
        sanitization = self.rules.sanitization
        lines = body.split("\n")
        result_lines = []

        # 서명 마커 이후 제거
        signature_markers = sanitization.get("signature_markers", [])

        for line in lines:
            # 서명 시작 확인
            if any(line.strip().startswith(m) for m in signature_markers):
                break

            # 제거 패턴 확인
            remove_patterns = sanitization.get("remove_patterns", [])
            should_remove = False
            for pattern in remove_patterns:
                try:
                    if re.match(pattern, line.strip(), re.IGNORECASE):
                        should_remove = True
                        break
                except re.error:
                    pass

            if not should_remove:
                result_lines.append(line)

        return "\n".join(result_lines).strip()


# ─── Triage Engine ──────────────────────────────────────────
class TriageEngine:
    """메일 트리아지 엔진"""

    def __init__(self, rules: TriageRules):
        self.rules = rules
        self._issue_cache: Dict[str, dict] = {}

    def triage(self, email: EmailData, policy: Optional['IngestPolicy'] = None) -> TriageResult:
        """이메일 트리아지 실행"""
        result = TriageResult(escalation_level=self.rules.automation_level)

        # 1. 발신자 분석
        self._analyze_sender(email, result)

        # 2. 키워드 분석
        self._analyze_keywords(email, result)

        # 3. 수정자 계산
        self._calculate_modifiers(email, result)

        # 4. 총점 및 우선순위 계산
        self._calculate_priority(result)

        # 5. 이슈 매칭
        self._match_issue(email, result)

        # 6. 권장 액션 결정
        self._determine_action(email, result)

        # ─── Phase 1 Ingest Gate (policy가 있을 때만) ───
        if policy is not None:
            # 7. 실행가능성 점수
            self._calculate_actionability(email, result, policy)
            # 8. 신규성 점수
            self._calculate_novelty(email, result, policy)
            # 9. 4분류
            self._classify(email, result, policy)

        return result

    def _analyze_sender(self, email: EmailData, result: TriageResult):
        """발신자 분석"""
        sender_rules = self.rules.sender_rules
        sender_email = email.sender_email

        # 개인 메일 확인
        individuals = sender_rules.get("individuals", {})
        if sender_email in individuals:
            info = individuals[sender_email]
            result.sender_name = info.get("name", "")
            result.sender_org = info.get("org", "")
            result.sender_weight = info.get("priority_weight", 1)
            return

        # 도메인 확인
        domains = sender_rules.get("domains", {})
        for domain, info in domains.items():
            if sender_email.endswith(f"@{domain}"):
                result.sender_org = info.get("org", "")
                result.sender_weight = info.get("priority_weight", 1)
                return

        # 기본값
        result.sender_weight = 1

    def _analyze_keywords(self, email: EmailData, result: TriageResult):
        """키워드 분석"""
        keyword_rules = self.rules.keyword_rules
        text = f"{email.subject} {email.clean_body}".lower()

        # 카테고리 키워드
        categories = keyword_rules.get("categories", {})
        for cat_name, cat_info in categories.items():
            keywords = cat_info.get("keywords", [])
            weight = cat_info.get("weight", 1)
            for kw in keywords:
                if kw.lower() in text:
                    if cat_name not in result.categories:
                        result.categories.append(cat_name)
                    result.keywords_hit.append(kw)
                    result.keyword_weight += weight

        # 행동 키워드
        actions = keyword_rules.get("actions", {})
        for action_name, action_info in actions.items():
            keywords = action_info.get("keywords", [])
            weight = action_info.get("weight", 0)
            for kw in keywords:
                if kw.lower() in text:
                    result.keywords_hit.append(f"[{action_name}]{kw}")
                    result.keyword_weight += weight

    def _calculate_modifiers(self, email: EmailData, result: TriageResult):
        """수정자 가중치 계산"""
        modifiers = self.rules.scoring.get("modifiers", {})
        text = f"{email.subject} {email.clean_body}"

        # 첨부파일
        if email.has_attachments:
            result.modifier_weight += modifiers.get("has_attachment", 1)

        # 마감일 언급
        deadline_patterns = [
            r"\d{1,2}월\s*\d{1,2}일",
            r"\d{4}[-/]\d{2}[-/]\d{2}",
            r"금주",
            r"이번주",
            r"내일",
            r"오늘",
        ]
        for pattern in deadline_patterns:
            if re.search(pattern, text):
                result.modifier_weight += modifiers.get("has_deadline_mention", 2)
                break

        # 회신 체인
        if email.subject.upper().startswith(("RE:", "FW:", "RE ", "FW ")):
            result.modifier_weight += modifiers.get("is_reply_chain", -1)

        # 도면 번호 언급 (이메일 제목 + OCR 첨부파일, 확신도 가중)
        has_subject_drawing = bool(re.search(r"[A-Z]{2,}-\d{3,}", email.subject))
        if has_subject_drawing:
            result.modifier_weight += modifiers.get("has_drawing_ref", 2)

        if email.ocr_drawing_refs and not has_subject_drawing:
            # OCR 확신도 기반 가중치: high(≥0.8)=+2, medium(0.5~0.8)=+1, low(<0.5)=+0
            max_conf = max(email.ocr_drawing_confidences.values()) if email.ocr_drawing_confidences else 0.5
            if max_conf >= 0.8:
                result.modifier_weight += modifiers.get("has_drawing_ref", 2)
            elif max_conf >= 0.5:
                result.modifier_weight += 1

    def _calculate_priority(self, result: TriageResult):
        """총점 및 우선순위 계산"""
        result.total_score = (
            result.sender_weight + result.keyword_weight + result.modifier_weight
        )

        thresholds = self.rules.scoring.get("thresholds", {})
        if result.total_score >= thresholds.get("critical", 8):
            result.priority = "critical"
        elif result.total_score >= thresholds.get("high", 5):
            result.priority = "high"
        elif result.total_score >= thresholds.get("medium", 2):
            result.priority = "medium"
        else:
            result.priority = "low"

    def _match_issue(self, email: EmailData, result: TriageResult):
        """이슈 매칭"""
        self._load_issue_cache()

        matching = self.rules.issue_matching
        priority_order = matching.get("priority", ["issue_id", "title_similarity"])

        for method in priority_order:
            if method == "issue_id":
                match = self._match_by_issue_id(email)
                if match:
                    result.matched_issue_id = match
                    result.match_method = "issue_id"
                    result.match_confidence = 1.0
                    return

            elif method == "title_similarity":
                match, confidence = self._match_by_title(email)
                threshold = matching.get("title_similarity_threshold", 0.7)
                if match and confidence >= threshold:
                    result.matched_issue_id = match
                    result.match_method = "title_similarity"
                    result.match_confidence = confidence
                    return

            elif method == "keyword_assignee":
                match = self._match_by_keyword_assignee(email, result)
                if match:
                    result.matched_issue_id = match
                    result.match_method = "keyword_assignee"
                    result.match_confidence = 0.6
                    return

    def _load_issue_cache(self):
        """이슈 캐시 로드"""
        if self._issue_cache:
            return

        for issue_file in ISSUES_DIR.glob("*.md"):
            try:
                content = issue_file.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    continue
                parts = content.split("---", 2)
                if len(parts) >= 2:
                    fm = yaml.safe_load(parts[1]) or {}
                    if fm.get("issue_id"):
                        self._issue_cache[fm["issue_id"]] = {
                            "file": issue_file,
                            "title": fm.get("title", ""),
                            "owner": fm.get("owner", ""),
                            "status": fm.get("issue_status", ""),
                            "issue_status": fm.get("issue_status", ""),
                            "priority": fm.get("priority", ""),
                            "categories": fm.get("category", ""),
                            "source_origin": fm.get("source_origin", ""),
                            "due_date": fm.get("due_date", ""),
                            "decision": fm.get("decision", ""),
                            "action_plan": fm.get("action_plan", ""),
                            "triage_score": fm.get("triage_score", 0),
                        }
            except Exception:
                pass

    def _match_by_issue_id(self, email: EmailData) -> Optional[str]:
        """이슈 ID로 매칭"""
        text = f"{email.subject} {email.clean_body}"
        for issue_id in self._issue_cache.keys():
            if issue_id in text:
                return issue_id
        return None

    def _match_by_title(self, email: EmailData) -> Tuple[Optional[str], float]:
        """제목 유사도로 매칭"""
        subject = email.subject.lower()
        best_match = None
        best_score = 0.0

        for issue_id, info in self._issue_cache.items():
            title = info.get("title", "").lower()
            score = SequenceMatcher(None, subject, title).ratio()
            if score > best_score:
                best_score = score
                best_match = issue_id

        return best_match, best_score

    def _match_by_keyword_assignee(
        self, email: EmailData, result: TriageResult
    ) -> Optional[str]:
        """키워드 + 담당자로 매칭"""
        for issue_id, info in self._issue_cache.items():
            # 키워드 매칭
            issue_cat = info.get("categories", "").lower()
            if any(cat.lower() in issue_cat for cat in result.categories):
                # 담당자 매칭
                owner = info.get("owner", "").lower()
                if result.sender_name.lower() in owner or not owner:
                    return issue_id
        return None

    def _determine_action(self, email: EmailData, result: TriageResult):
        """권장 액션 결정"""
        level = self.rules.automation_level

        if result.matched_issue_id:
            if level == "L1":
                result.suggested_action = "tag_only"
            elif level == "L2":
                result.suggested_action = "suggest_update"
            else:  # L3
                result.suggested_action = "auto_update"
        else:
            on_no_match = self.rules.issue_matching.get("on_no_match", "create_new")
            if on_no_match == "create_new" and level == "L3":
                result.suggested_action = "create_issue"
            else:
                result.suggested_action = "flag_for_review"

    # ─── Phase 1 Ingest Gate Steps ────────────────────────────

    def _calculate_actionability(self, email: EmailData, result: TriageResult, policy: 'IngestPolicy'):
        """Step 7: 실행가능성 점수 (범위 -2 ~ +5)"""
        rules = policy.actionability_rules
        score = 0

        # [urgent] 키워드 히트 → +2
        if any(kw.startswith("[urgent]") for kw in result.keywords_hit):
            score += rules.get("urgent_keyword_bonus", 2)

        # [request] 키워드 히트 → +1
        if any(kw.startswith("[request]") for kw in result.keywords_hit):
            score += rules.get("request_keyword_bonus", 1)

        # 마감일 언급 (modifier에서 deadline이 반영되었으면) → +1
        text = f"{email.subject} {email.clean_body}"
        deadline_patterns = [
            r"\d{1,2}월\s*\d{1,2}일", r"\d{4}[-/]\d{2}[-/]\d{2}",
            r"금주", r"이번주", r"내일", r"오늘",
        ]
        if any(re.search(p, text) for p in deadline_patterns):
            score += rules.get("deadline_mention_bonus", 1)

        # VIP 발신자 (sender_weight >= threshold) → +1
        if result.sender_weight >= policy.vip_threshold:
            score += rules.get("vip_sender_bonus", 1)

        # [fyi] 키워드 → -1
        if any(kw.startswith("[fyi]") for kw in result.keywords_hit):
            score += rules.get("fyi_keyword_penalty", -1)

        # RE:/FW: 체인 → -1
        if email.subject.upper().startswith(("RE:", "FW:", "RE ", "FW ")):
            score += rules.get("reply_chain_penalty", -1)

        result.actionability = score

    def _calculate_novelty(self, email: EmailData, result: TriageResult, policy: 'IngestPolicy'):
        """Step 8: 신규성 점수 (범위 -1 ~ +4)"""
        rules = policy.novelty_rules
        score = 0

        # 첫 대화 (RE:/FW: 없음) → +2
        if not email.subject.upper().startswith(("RE:", "FW:", "RE ", "FW ")):
            score += rules.get("first_conversation_bonus", 2)

        # 새 첨부파일 → +1
        if email.has_attachments:
            score += rules.get("new_attachments_bonus", 1)

        # 새 도면 번호 참조 → +1
        if email.ocr_drawing_refs:
            score += rules.get("new_drawing_refs_bonus", 1)

        # 기존 이슈 높은 매칭 (confidence > threshold) → -1
        conf_threshold = rules.get("confidence_threshold", 0.8)
        if result.match_confidence > conf_threshold:
            score += rules.get("high_match_confidence_penalty", -1)

        result.novelty = score

    def _classify(self, email: EmailData, result: TriageResult, policy: 'IngestPolicy'):
        """Step 9: 4분류 결정 (우선순위: Trash > Action > Decision > Reference)"""
        cls_rules = policy.classification

        # 1. Trash: total_score < 2 AND actionability < 1
        trash_cfg = cls_rules.get("trash", {})
        if (result.total_score < trash_cfg.get("score_threshold", 2)
                and result.actionability < trash_cfg.get("actionability_threshold", 1)):
            result.classification = "Trash"
            return

        # 2. Action: urgent/request 키워드 OR actionability >= 3
        action_cfg = cls_rules.get("action", {})
        has_urgent_or_request = any(
            kw.startswith("[urgent]") or kw.startswith("[request]")
            for kw in result.keywords_hit
        )
        if has_urgent_or_request or result.actionability >= action_cfg.get("actionability_threshold", 3):
            result.classification = "Action"
            return

        # 3. Decision: 매칭 이슈에 action_plan 있고 decision 비어있음
        dec_cfg = cls_rules.get("decision", {})
        if result.matched_issue_id and result.matched_issue_id in self._issue_cache:
            issue_info = self._issue_cache[result.matched_issue_id]
            has_action_plan = bool(str(issue_info.get("action_plan", "")).strip())
            empty_decision = not str(issue_info.get("decision", "")).strip()
            if (dec_cfg.get("requires_action_plan", True) and has_action_plan
                    and dec_cfg.get("requires_empty_decision", True) and empty_decision):
                result.classification = "Decision"
                return

        # 4. Reference: 나머지
        result.classification = "Reference"


# ─── Entity Extractor ──────────────────────────────────────
class EntityExtractor:
    """이메일 본문/발신자에서 마감일·담당자 자동 추출"""

    DEADLINE_PATTERNS = [
        (r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", "iso_date"),
        (r"(\d{1,2})월\s*(\d{1,2})일\s*(?:까지|이전|내|중)", "month_day_deadline"),
        (r"(\d{1,2})월\s*(\d{1,2})일", "month_day"),
        (r"(\d{1,2})/(\d{1,2})", "slash_date"),
        (r"금주\s*(?:중|내|까지)?", "this_week"),
        (r"이번\s*주", "this_week"),
        (r"내일", "tomorrow"),
        (r"오늘\s*(?:중)?", "today"),
    ]

    def __init__(self, rules: TriageRules):
        self.rules = rules
        self._individual_map = {}
        # sender_rules.individuals → 이메일-이름 매핑 구축
        sender_rules = rules.rules.get("sender_rules", {})
        for email_addr, info in sender_rules.get("individuals", {}).items():
            self._individual_map[email_addr.lower()] = {
                "name": info.get("name", ""),
                "org": info.get("org", ""),
                "role": info.get("role", ""),
            }

    def extract_deadline(self, text: str) -> Tuple[Optional[str], float]:
        """본문에서 마감일 추출 → (YYYY-MM-DD, 확신도)"""
        today = datetime.now()

        for pattern, ptype in self.DEADLINE_PATTERNS:
            m = re.search(pattern, text)
            if not m:
                continue

            try:
                if ptype == "iso_date":
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    dt = datetime(y, mo, d)
                    if dt >= today - timedelta(days=30):
                        return dt.strftime("%Y-%m-%d"), 0.95

                elif ptype == "month_day_deadline":
                    mo, d = int(m.group(1)), int(m.group(2))
                    y = today.year
                    dt = datetime(y, mo, d)
                    if dt < today - timedelta(days=30):
                        dt = datetime(y + 1, mo, d)
                    return dt.strftime("%Y-%m-%d"), 0.9

                elif ptype == "month_day":
                    mo, d = int(m.group(1)), int(m.group(2))
                    y = today.year
                    dt = datetime(y, mo, d)
                    if dt < today - timedelta(days=30):
                        dt = datetime(y + 1, mo, d)
                    return dt.strftime("%Y-%m-%d"), 0.7

                elif ptype == "slash_date":
                    a, b = int(m.group(1)), int(m.group(2))
                    if 1 <= a <= 12 and 1 <= b <= 31:
                        dt = datetime(today.year, a, b)
                        if dt < today - timedelta(days=30):
                            dt = datetime(today.year + 1, a, b)
                        return dt.strftime("%Y-%m-%d"), 0.6

                elif ptype == "this_week":
                    # 이번 주 금요일
                    days_until_friday = (4 - today.weekday()) % 7
                    if days_until_friday == 0:
                        days_until_friday = 7
                    friday = today + timedelta(days=days_until_friday)
                    return friday.strftime("%Y-%m-%d"), 0.6

                elif ptype == "tomorrow":
                    tmr = today + timedelta(days=1)
                    return tmr.strftime("%Y-%m-%d"), 0.85

                elif ptype == "today":
                    return today.strftime("%Y-%m-%d"), 0.85

            except (ValueError, OverflowError):
                continue

        return None, 0.0

    def extract_owner(self, sender_email: str, sender_name: str, source_origin: str) -> Tuple[Optional[str], float]:
        """발신자 + sender_rules 매핑 → (담당자명, 확신도)"""
        # 1. sender_rules.individuals 직접 매칭
        if sender_email:
            info = self._individual_map.get(sender_email.lower())
            if info and info.get("name"):
                return info["name"], 0.85

        # 2. sender_name에서 이름 파싱: "이동혁 [소장] [EPC팀]" → "이동혁"
        if sender_name:
            name_clean = re.sub(r"\[.*?\]", "", sender_name).strip()
            if name_clean and len(name_clean) >= 2:
                return name_clean, 0.7

        # 3. source_origin 기반 추론
        origin_map = {
            "ENA(시공)": ("ENA 현장담당", 0.5),
            "삼성 E&A": ("삼성E&A 담당", 0.5),
            "센구조": ("센구조 담당", 0.5),
            "이앤디몰(PC)": ("이앤디몰 담당", 0.5),
        }
        if source_origin:
            for key, (name, conf) in origin_map.items():
                if key in source_origin:
                    return name, conf

        return None, 0.0


# ─── Triage Result Application ─────────────────────────────
def apply_triage_results(
    results: List[Tuple[EmailData, TriageResult]],
    dry_run: bool = False,
    policy: Optional['IngestPolicy'] = None,
) -> Dict[str, int]:
    """트리아지 결과를 이슈 파일에 반영

    Args:
        results: (이메일, 트리아지결과) 튜플 리스트
        dry_run: True면 실제 파일 수정 없이 로그만 출력
        policy: IngestPolicy 인스턴스. None이면 분류 라우팅 스킵.

    Returns:
        {"updated": N, "flagged": N, "skipped": N, ...} 카운트
    """
    counts = {"updated": 0, "flagged": 0, "skipped": 0, "entities_extracted": 0,
              "quarantined": 0, "wip_overflow": 0}

    # EntityExtractor 초기화
    rules = TriageRules()
    extractor = EntityExtractor(rules)

    # ─── Phase 1: WIP 카운트 (policy가 있을 때만) ───
    wip_count = 0
    wip_max = 15
    if policy is not None:
        wip_cfg = policy.wip
        wip_max = wip_cfg.get("max_active_issues", 15)
        count_statuses = wip_cfg.get("count_statuses", ["open", "in_progress"])
        count_priorities = wip_cfg.get("count_priorities", ["high", "critical"])
        if ISSUES_DIR.exists():
            for issue_file in ISSUES_DIR.glob("SEN-*.md"):
                try:
                    content = issue_file.read_text(encoding="utf-8")
                    if not content.startswith("---"):
                        continue
                    parts = content.split("---", 2)
                    if len(parts) >= 2:
                        fm = yaml.safe_load(parts[1]) or {}
                        if (fm.get("issue_status", "") in count_statuses
                                and fm.get("priority", "") in count_priorities):
                            wip_count += 1
                except Exception:
                    pass
        log.info(f"  WIP 현황: {wip_count}/{wip_max} (active critical/high)")

        # quarantine_dir 준비
        policy.quarantine_dir.mkdir(parents=True, exist_ok=True)

    for email, result in results:
        # ─── Phase 1: 분류 기반 라우팅 (policy가 있을 때만) ───
        if policy is not None and result.classification:
            # Trash → 격리
            if result.classification == "Trash":
                if dry_run:
                    log.info(f"  [DRY-RUN] 격리 예정: {email.subject[:40]}... (score={result.total_score}, actionability={result.actionability})")
                else:
                    try:
                        dest = policy.quarantine_dir / email.file_path.name
                        email.file_path.rename(dest)
                        log.info(f"  🗑️ 격리: {email.file_path.name} → Quarantine/")
                    except Exception as e:
                        log.error(f"  격리 실패 ({email.file_path.name}): {e}")
                counts["quarantined"] += 1
                continue

            # Action/Decision + WIP 초과 → 리뷰큐 (wip_overflow)
            if result.classification in ("Action", "Decision") and wip_count >= wip_max:
                if dry_run:
                    log.info(f"  [DRY-RUN] WIP초과 리뷰큐: {email.subject[:40]}... (WIP {wip_count}/{wip_max})")
                else:
                    _append_to_review_queue(email, result, wip_overflow=True)
                    log.info(f"  ⚠️ WIP초과 → 리뷰큐: {email.subject[:40]}...")
                counts["wip_overflow"] += 1
                counts["flagged"] += 1
                continue

        action = result.suggested_action

        if action == "suggest_update" and result.matched_issue_id:
            # L2: 매칭된 이슈 frontmatter에 트리아지 정보 기록
            issue_file = _find_issue_file(result.matched_issue_id)
            if not issue_file:
                log.warning(f"이슈 파일 미발견: {result.matched_issue_id}")
                counts["skipped"] += 1
                continue

            # EntityExtractor: 마감일/담당자 추출
            entity_updates = {}
            text = f"{email.subject} {email.clean_body}"
            deadline, dl_conf = extractor.extract_deadline(text)
            owner, ow_conf = extractor.extract_owner(
                email.sender_email, result.sender_name, result.sender_org
            )

            if deadline:
                if dl_conf >= 0.7:
                    entity_updates["due_date"] = deadline
                elif dl_conf >= 0.5:
                    entity_updates["suggested_due_date"] = deadline
            if owner:
                if ow_conf >= 0.7:
                    entity_updates["owner"] = owner
                elif ow_conf >= 0.5:
                    entity_updates["suggested_owner"] = owner

            if dry_run:
                log.info(f"  [DRY-RUN] 업데이트 예정: {issue_file.name}")
                log.info(f"    triage_score: {result.total_score}")
                log.info(f"    source_origin: {result.sender_org}")
                if entity_updates:
                    log.info(f"    자동추출: {entity_updates}")
                counts["updated"] += 1
                if entity_updates:
                    counts["entities_extracted"] += 1
                continue

            # 기존 값 보존: 빈 필드만 채움
            fm_updates = {
                "triage_score": result.total_score,
                "triage_priority": result.priority,
                "source_origin": result.sender_org,
                "keywords_hit": result.keywords_hit,
                "last_triage_at": datetime.now().isoformat(),
            }
            # Phase 1: 분류 필드 추가
            if result.classification:
                fm_updates["classification"] = result.classification
                fm_updates["actionability"] = result.actionability
                fm_updates["novelty"] = result.novelty

            if entity_updates:
                # 기존 frontmatter 읽어서 빈 필드만 채움
                try:
                    fc = issue_file.read_text(encoding="utf-8")
                    fm_parts = fc.split("---", 2)
                    if len(fm_parts) >= 2:
                        existing_fm = yaml.safe_load(fm_parts[1]) or {}
                        for key, val in entity_updates.items():
                            existing_val = str(existing_fm.get(key, "")).strip()
                            if not existing_val:
                                fm_updates[key] = val
                                log.info(f"    자동추출 → {key}: {val}")
                except Exception:
                    pass
                counts["entities_extracted"] += 1

            _update_issue_frontmatter(issue_file, fm_updates)
            log.info(f"  ✅ 업데이트: {issue_file.name} (score={result.total_score})")
            counts["updated"] += 1

        elif action == "flag_for_review":
            # 리뷰 큐에 추가
            if dry_run:
                log.info(f"  [DRY-RUN] 리뷰 플래그 예정: {email.subject[:40]}")
                counts["flagged"] += 1
                continue

            _append_to_review_queue(email, result)
            log.info(f"  🏷️ 리뷰 플래그: {email.subject[:40]}")
            counts["flagged"] += 1

        else:
            counts["skipped"] += 1

    return counts


def _find_issue_file(issue_id: str) -> Optional[Path]:
    """이슈 ID로 파일 검색"""
    for f in ISSUES_DIR.glob(f"{issue_id}-*.md"):
        return f
    # fallback: frontmatter에서 issue_id 검색
    for f in ISSUES_DIR.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            if f"issue_id: {issue_id}" in content or f'issue_id: "{issue_id}"' in content:
                return f
        except Exception:
            pass
    return None


def _update_issue_frontmatter(file_path: Path, updates: dict):
    """이슈 파일의 YAML frontmatter 업데이트"""
    content = file_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return

    parts = content.split("---", 2)
    if len(parts) < 3:
        return

    try:
        fm = yaml.safe_load(parts[1]) or {}
        fm.update(updates)
        new_fm = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).rstrip()
        new_content = f"---\n{new_fm}\n---{parts[2]}"
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        log.error(f"frontmatter 업데이트 실패 ({file_path.name}): {e}")


def _append_to_review_queue(email: EmailData, result: TriageResult, wip_overflow: bool = False):
    """리뷰 큐 파일에 항목 추가"""
    queue_path = VAULT_PATH / "P5-Project" / "00-Overview" / "triage-review-queue.md"
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    conv_id = result.conversation_id or email.subject[:60]
    added_at = datetime.now().strftime("%Y-%m-%d")
    overflow_marker = "⚠️WIP초과 " if wip_overflow else ""
    cls_marker = f"분류: {result.classification} | " if result.classification else ""
    entry = (
        f"- [ ] {overflow_marker}**{email.subject[:60]}** | "
        f"발신: {result.sender_org} | "
        f"{cls_marker}"
        f"점수: {result.total_score} ({result.priority}) | "
        f"날짜: {email.received_at} | "
        f"추가일: {added_at} | "
        f"conversation: {conv_id} | "
        f"원본: [[{email.file_path.stem}]]\n"
    )

    if queue_path.exists():
        existing = queue_path.read_text(encoding="utf-8")
        # 중복 방지: 같은 이메일 파일명이 이미 있으면 스킵
        if email.file_path.stem in existing:
            return
        queue_path.write_text(existing + entry, encoding="utf-8")
    else:
        header = (
            "---\n"
            "title: P5 트리아지 리뷰 큐\n"
            f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
            "tags: [project/p5, type/queue]\n"
            "---\n\n"
            "# 📋 트리아지 리뷰 큐\n\n"
            "> 자동 매칭되지 않은 메일 목록. 수동 검토 후 이슈 연결/생성 필요.\n\n"
        )
        queue_path.write_text(header + entry, encoding="utf-8")


# ─── Commands ───────────────────────────────────────────────
def cmd_process(args):
    """새 메일 처리"""
    log.info("=" * 50)
    log.info("P5 메일 트리아지 시작")
    log.info("=" * 50)

    rules = TriageRules()
    parser = EmailParser(rules)
    engine = TriageEngine(rules)
    noise_filter = NoiseFilter(rules)
    policy = IngestPolicy()

    mail_dir = Path(args.mail_dir) if args.mail_dir else INBOX_DIR
    if not mail_dir.exists():
        log.error(f"메일 디렉토리 없음: {mail_dir}")
        return

    mail_files = list(mail_dir.glob("*.md"))
    total_input = len(mail_files)
    log.info(f"처리할 메일: {total_input}개")

    results = []
    noise_stats: Dict[str, int] = {}
    for mail_file in mail_files:
        email = parser.parse_email_file(mail_file)
        if not email:
            continue

        # 노이즈 필터 (트리아지 전 단계)
        nf_result = noise_filter.filter(email)
        if nf_result.disposition != "pass":
            noise_stats[nf_result.disposition] = noise_stats.get(nf_result.disposition, 0) + 1
            log.info(f"  🚫 필터: {email.subject[:40]}... → {nf_result.disposition} ({nf_result.reason})")
            continue

        result = engine.triage(email, policy=policy)
        result.conversation_id = nf_result.conversation_id
        results.append((email, result))

        log.info(f"\n📧 {email.subject[:50]}...")
        log.info(f"   발신자: {result.sender_org} ({result.sender_name})")
        log.info(f"   점수: {result.total_score} → {result.priority}")
        log.info(f"   카테고리: {', '.join(result.categories) or '미분류'}")
        if result.classification:
            log.info(f"   분류: {result.classification} (실행가능성:{result.actionability}, 신규성:{result.novelty})")
        if result.matched_issue_id:
            log.info(f"   매칭: {result.matched_issue_id} ({result.match_method})")
        log.info(f"   액션: {result.suggested_action}")

    # SNR 요약
    total_filtered = sum(noise_stats.values())
    total_passed = len(results)
    snr_pct = round(total_passed / max(total_input, 1) * 100)
    log.info("\n" + "=" * 50)
    log.info(f"📊 SNR 요약: 입력 {total_input}건 | 통과 {total_passed}건 | 필터 {total_filtered}건 | SNR {snr_pct}%")
    if noise_stats:
        for disposition, count in sorted(noise_stats.items()):
            log.info(f"   {disposition}: {count}건")

    # 우선순위별 집계
    priority_count = {}
    for _, r in results:
        priority_count[r.priority] = priority_count.get(r.priority, 0) + 1
    for p, c in sorted(priority_count.items()):
        log.info(f"  {p}: {c}개")

    # 트리아지 결과 반영
    dry_run = getattr(args, "dry_run", False)
    auto_apply_above = getattr(args, "auto_apply_above", None)

    # 분류 분포 로그
    cls_dist: Dict[str, int] = {}
    for _, r in results:
        if r.classification:
            cls_dist[r.classification] = cls_dist.get(r.classification, 0) + 1
    if cls_dist:
        dist_str = " | ".join(f"{k}:{v}" for k, v in sorted(cls_dist.items()))
        log.info(f"\n📊 분류 분포: {dist_str}")

    if dry_run:
        # --dry-run이 우선: 전체 dry-run
        log.info("\n🔍 [DRY-RUN 모드] 실제 파일 수정 없이 결과만 표시합니다.")
        counts = apply_triage_results(results, dry_run=True, policy=policy)
    elif auto_apply_above is not None:
        # --auto-apply-above N: 점수 분기 적용 (L2.5 모드)
        threshold = auto_apply_above
        high_conf = [(e, r) for e, r in results if r.total_score >= threshold]
        low_conf = [(e, r) for e, r in results if r.total_score < threshold]

        log.info(f"\n📝 [AUTO-APPLY L2.5] 점수 {threshold}+ 자동 적용: {len(high_conf)}건 | "
                 f"점수 {threshold} 미만 dry-run: {len(low_conf)}건")

        _zero = {"updated": 0, "flagged": 0, "skipped": 0, "entities_extracted": 0, "quarantined": 0, "wip_overflow": 0}
        counts_high = apply_triage_results(high_conf, dry_run=False, policy=policy) if high_conf else dict(_zero)
        counts_low = apply_triage_results(low_conf, dry_run=True, policy=policy) if low_conf else dict(_zero)

        # 카운트 합산
        counts = {
            k: counts_high.get(k, 0) + counts_low.get(k, 0)
            for k in ("updated", "flagged", "skipped", "entities_extracted", "quarantined", "wip_overflow")
        }
        log.info(f"  자동 적용 (score≥{threshold}): {counts_high.get('updated', 0)}건 업데이트, {counts_high.get('flagged', 0)}건 리뷰")
        log.info(f"  dry-run (score<{threshold}): {counts_low.get('updated', 0)}건 예정, {counts_low.get('flagged', 0)}건 예정")
    else:
        log.info("\n📝 트리아지 결과 반영 중...")
        counts = apply_triage_results(results, dry_run=False, policy=policy)

    log.info(f"\n  업데이트: {counts['updated']}건")
    log.info(f"  리뷰 플래그: {counts['flagged']}건")
    log.info(f"  스킵: {counts['skipped']}건")
    log.info(f"  엔티티 추출: {counts.get('entities_extracted', 0)}건")
    if counts.get('quarantined', 0) > 0:
        log.info(f"  격리: {counts['quarantined']}건")
    if counts.get('wip_overflow', 0) > 0:
        log.info(f"  WIP초과: {counts['wip_overflow']}건")


def cmd_score(args):
    """점수 테스트"""
    rules = TriageRules()
    engine = TriageEngine(rules)
    parser = EmailParser(rules)

    # 테스트용 이메일 생성
    email = EmailData(
        file_path=Path("test"),
        subject=args.subject,
        sender=args.sender,
        sender_email=parser._extract_email(args.sender),
        body=args.body or "",
        clean_body=parser._sanitize_body(args.body or ""),
        has_attachments=args.attachment,
    )

    policy = IngestPolicy()
    result = engine.triage(email, policy=policy)

    print("\n📊 트리아지 결과")
    print("=" * 40)
    print(f"제목: {email.subject}")
    print(f"발신자: {email.sender} → {result.sender_org}")
    print()
    print("점수 분해:")
    print(f"  발신자 가중치: {result.sender_weight}")
    print(f"  키워드 가중치: {result.keyword_weight}")
    print(f"  수정자 가중치: {result.modifier_weight}")
    print(f"  ─────────────")
    print(f"  총점: {result.total_score}")
    print()
    print(f"우선순위: {result.priority}")
    print(f"분류: {result.classification}")
    print(f"실행가능성: {result.actionability}")
    print(f"신규성: {result.novelty}")
    print(f"카테고리: {', '.join(result.categories) or '없음'}")
    print(f"키워드 히트: {', '.join(result.keywords_hit) or '없음'}")
    if result.matched_issue_id:
        print(f"매칭 이슈: {result.matched_issue_id}")


# ─── 큐 노이즈 자동 제거 패턴 ──────────────────────
QUEUE_NOISE_PATTERNS = [
    r"님을\s*추가하세요",
    r"connection\s*request",
    r"뉴스레터|newsletter",
    r"unsubscribe",
    r"리마건축|우리들교회|용인\s*단지",
    r"password\s*reset",
    r"결재.*완료.*알림",
    r"전자결재.*의견",
    r"noreply@|no-reply@|notification@",
]


def _parse_queue_entries(queue_path: Path) -> List[Dict[str, str]]:
    """큐 파일 파싱 → 엔트리 리스트"""
    if not queue_path.exists():
        return []

    content = queue_path.read_text(encoding="utf-8")
    entries = []
    for line in content.split("\n"):
        if not line.startswith("- ["):
            continue

        entry = {"raw": line, "checked": line.startswith("- [x]")}

        # 필드 파싱
        parts = line.split(" | ")
        for part in parts:
            part = part.strip()
            if part.startswith("추가일:"):
                entry["added_at"] = part.replace("추가일:", "").strip()
            elif part.startswith("conversation:"):
                entry["conversation"] = part.replace("conversation:", "").strip()
            elif part.startswith("점수:"):
                score_str = part.replace("점수:", "").strip()
                try:
                    entry["score"] = int(score_str.split("(")[0].strip())
                    entry["priority"] = score_str.split("(")[1].rstrip(")").strip() if "(" in score_str else ""
                except (ValueError, IndexError):
                    entry["score"] = 0
            elif part.startswith("날짜:"):
                entry["date"] = part.replace("날짜:", "").strip()
            elif part.startswith("발신:"):
                entry["sender"] = part.replace("발신:", "").strip()

        # 제목 추출
        title_match = re.search(r"\*\*(.+?)\*\*", line)
        if title_match:
            entry["title"] = title_match.group(1)

        # 추가일 필드가 없으면 날짜 필드에서 소급 (레거시 호환)
        if not entry.get("added_at") and entry.get("date"):
            try:
                dt_str = entry["date"][:10]  # "2026-02-06T21:23:00" → "2026-02-06"
                datetime.strptime(dt_str, "%Y-%m-%d")
                entry["added_at"] = dt_str
            except (ValueError, IndexError):
                pass

        entries.append(entry)

    return entries


def _rebuild_queue(queue_path: Path, entries: List[Dict[str, str]]):
    """엔트리 리스트 → 큐 파일 재작성 (에이징 표시 + 정렬)"""
    today = datetime.now()

    # 점수(내림)+연령(내림) 정렬
    def _sort_key(e):
        score = e.get("score", 0)
        added = e.get("added_at", "")
        age = 0
        if added:
            try:
                age = (today - datetime.strptime(added, "%Y-%m-%d")).days
            except ValueError:
                pass
        return (-score, -age)

    entries.sort(key=_sort_key)

    # 에이징 경고 카운트
    stale_count = 0
    for e in entries:
        added = e.get("added_at", "")
        if added:
            try:
                age = (today - datetime.strptime(added, "%Y-%m-%d")).days
                if age >= 7 and not e.get("checked"):
                    stale_count += 1
            except ValueError:
                pass

    # 에이징 마커 적용한 라인 생성
    rebuilt_lines = []
    for e in entries:
        raw = e["raw"]
        added = e.get("added_at", "")
        age = 0
        if added:
            try:
                age = (today - datetime.strptime(added, "%Y-%m-%d")).days
            except ValueError:
                pass
        # 7일 이상 미처리 항목 앞에 🔴 표시
        if age >= 7 and not e.get("checked"):
            # raw 라인에서 기존 🔴 제거 후 재삽입
            clean_raw = raw.replace("🔴 ", "")
            if clean_raw.startswith("- [ ] "):
                raw = "- [ ] 🔴 " + clean_raw[6:]
        else:
            # 7일 미만이면 🔴 제거
            raw = raw.replace("🔴 ", "")
        rebuilt_lines.append(raw)

    warning_line = ""
    if stale_count > 0:
        warning_line = f"> ⚠️ {stale_count}건 7일 이상 미처리\n\n"

    header = (
        "---\n"
        "title: P5 트리아지 리뷰 큐\n"
        f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
        "tags: [project/p5, type/queue]\n"
        "---\n\n"
        "# 📋 트리아지 리뷰 큐\n\n"
        "> 자동 매칭되지 않은 메일 목록. 수동 검토 후 이슈 연결/생성 필요.\n\n"
        f"{warning_line}"
    )
    queue_path.write_text(header + "\n".join(rebuilt_lines) + "\n", encoding="utf-8")


def cmd_queue(args):
    """리뷰 큐 관리"""
    queue_path = VAULT_PATH / "P5-Project" / "00-Overview" / "triage-review-queue.md"
    action = args.action

    if action == "stats":
        entries = _parse_queue_entries(queue_path)
        total = len(entries)
        checked = sum(1 for e in entries if e.get("checked"))
        unchecked = total - checked

        # 연령 분포
        today = datetime.now()
        age_buckets = {"<7일": 0, "7-14일": 0, "14-30일": 0, ">30일": 0, "미상": 0}
        for e in entries:
            added = e.get("added_at", "")
            if added:
                try:
                    d = datetime.strptime(added, "%Y-%m-%d")
                    age = (today - d).days
                    if age < 7:
                        age_buckets["<7일"] += 1
                    elif age < 14:
                        age_buckets["7-14일"] += 1
                    elif age < 30:
                        age_buckets["14-30일"] += 1
                    else:
                        age_buckets[">30일"] += 1
                except ValueError:
                    age_buckets["미상"] += 1
            else:
                age_buckets["미상"] += 1

        # 우선순위 분포
        prio_dist = {}
        for e in entries:
            p = e.get("priority", "unknown")
            prio_dist[p] = prio_dist.get(p, 0) + 1

        log.info("📊 큐 통계")
        log.info(f"  총 항목: {total}건 (체크: {checked}, 미체크: {unchecked})")
        log.info("  연령 분포:")
        for k, v in age_buckets.items():
            if v > 0:
                log.info(f"    {k}: {v}건")
        log.info("  우선순위 분포:")
        for k, v in sorted(prio_dist.items()):
            log.info(f"    {k}: {v}건")

    elif action == "dedup":
        entries = _parse_queue_entries(queue_path)
        seen_convs: Dict[str, int] = {}
        deduped = []
        removed = 0

        for e in entries:
            conv = e.get("conversation", e.get("title", ""))
            if conv in seen_convs:
                removed += 1
                log.info(f"  중복 제거: {e.get('title', '')[:40]}...")
            else:
                seen_convs[conv] = len(deduped)
                deduped.append(e)

        if removed > 0:
            _rebuild_queue(queue_path, deduped)
            log.info(f"✅ 큐 중복 제거: {len(entries)}건 → {len(deduped)}건 ({removed}건 제거)")
        else:
            log.info("✅ 중복 없음")

    elif action == "clean":
        entries = _parse_queue_entries(queue_path)
        max_age = getattr(args, "max_age", 14)
        today = datetime.now()
        kept = []
        archived = 0
        noise_removed = 0

        for e in entries:
            # 체크된 항목 제거
            if e.get("checked"):
                archived += 1
                log.info(f"  정리 (체크됨): {e.get('title', '')[:40]}...")
                continue

            # 저점수 항목 제거 (score < 2)
            if e.get("score", 99) < 2:
                archived += 1
                log.info(f"  정리 (저점수): {e.get('title', '')[:40]}...")
                continue

            # 노이즈 패턴 매칭 제거
            raw_text = e.get("raw", "") + " " + e.get("title", "")
            is_noise = False
            for pattern in QUEUE_NOISE_PATTERNS:
                if re.search(pattern, raw_text, re.IGNORECASE):
                    noise_removed += 1
                    archived += 1
                    log.info(f"  정리 (노이즈:{pattern[:20]}): {e.get('title', '')[:40]}...")
                    is_noise = True
                    break
            if is_noise:
                continue

            # 오래된 항목 제거
            added = e.get("added_at", "")
            if added:
                try:
                    d = datetime.strptime(added, "%Y-%m-%d")
                    age = (today - d).days
                    if age > max_age:
                        archived += 1
                        log.info(f"  정리 ({age}일): {e.get('title', '')[:40]}...")
                        continue
                except ValueError:
                    pass

            kept.append(e)

        if archived > 0:
            _rebuild_queue(queue_path, kept)
            log.info(f"✅ 큐 정리: {len(entries)}건 → {len(kept)}건 ({archived}건 아카이브, 노이즈:{noise_removed}건)")
        else:
            log.info("✅ 정리 대상 없음")


def cmd_decide(args):
    """의사결정 기록 생성"""
    decisions_dir = VAULT_PATH / "P5-Project" / "04-Decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    # DEC-YYYYMMDD-NNN 시퀀스 ID 생성
    today = datetime.now().strftime("%Y%m%d")
    existing = list(decisions_dir.glob(f"DEC-{today}-*.md"))
    seq = len(existing) + 1
    dec_id = f"DEC-{today}-{seq:03d}"

    title = args.title.strip('"').strip("'")
    decision_text = args.decision.strip('"').strip("'")
    decided_by = (getattr(args, "decided_by", "") or "").strip('"').strip("'")
    issue_id = getattr(args, "issue", None)

    # 파일명 생성 (한글 안전)
    safe_title = re.sub(r"[^\w가-힣-]", "-", title)[:30].strip("-")
    dec_filename = f"{dec_id}-{safe_title}.md"
    dec_path = decisions_dir / dec_filename

    # 결정 노트 생성
    related_issues = [issue_id] if issue_id else []
    content = (
        "---\n"
        f"decision_id: \"{dec_id}\"\n"
        f"title: \"{title}\"\n"
        f"related_issues: {related_issues}\n"
        "related_emails: []\n"
        f"decided_by: \"{decided_by}\"\n"
        f"decided_at: \"{datetime.now().strftime('%Y-%m-%d')}\"\n"
        "status: draft\n"
        "impact_scope: \"\"\n"
        "tags: [project/p5, type/decision]\n"
        "---\n"
        f"# {title}\n\n"
        "## 결정 사항\n"
        f"{decision_text}\n\n"
        "## 근거\n\n\n"
        "## 영향 범위\n\n\n"
        "## 후속 조치\n"
        "- [ ] \n"
    )
    dec_path.write_text(content, encoding="utf-8")
    log.info(f"✅ 결정 기록 생성: {dec_path.name}")

    # 관련 SEN 이슈 파일에 양방향 링크 추가
    if issue_id:
        issue_file = _find_issue_file(issue_id)
        if issue_file:
            _update_issue_frontmatter(issue_file, {
                "decision": decision_text[:80],
                "decision_ref": f"[[{dec_id}]]",
                "decision_at": datetime.now().strftime("%Y-%m-%d"),
            })
            log.info(f"  ↔ 이슈 업데이트: {issue_file.name} ← decision_ref: [[{dec_id}]]")
        else:
            log.warning(f"  이슈 파일 미발견: {issue_id}")

    log.info(f"  📎 결정 ID: {dec_id}")
    log.info(f"  📂 경로: {dec_path}")


def _get_queue_count() -> int:
    """리뷰 큐 미처리 항목 수 반환"""
    queue_path = VAULT_PATH / "P5-Project" / "00-Overview" / "triage-review-queue.md"
    if not queue_path.exists():
        return 0
    count = 0
    for line in queue_path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("- [ ]"):
            count += 1
    return count


def _generate_weekly_action_plan(engine: TriageEngine) -> List[str]:
    """주간 액션 플랜 Top 5 생성"""
    candidates = []

    for issue_id, info in engine._issue_cache.items():
        priority = info.get("priority", "")
        status = info.get("issue_status", "open")
        if status in ("closed", "resolved"):
            continue

        prio_w = {"critical": 4, "high": 3, "medium": 2}.get(priority, 1)
        owner = str(info.get("owner", "")).strip()
        due_date = str(info.get("due_date", "")).strip()
        decision = str(info.get("decision", "")).strip()
        action_plan = str(info.get("action_plan", "") or "").strip()
        title = info.get("title", "")[:40]
        source = info.get("source_origin", "")

        # 완전성 갭
        gap = 0
        action_type = ""
        action_desc = ""
        if not owner:
            gap += 1
            action_type = "담당자 지정"
            action_desc = f"담당자 지정 필요 (발생원: {source or '미상'})"
        if not due_date:
            gap += 1
            if not action_type:
                action_type = "마감일 설정"
                action_desc = f"마감일 설정 필요 (High/Critical)"
        if action_plan and not decision:
            gap += 1
            action_type = "결정 기록"
            action_desc = f"결정 기록 필요 (action_plan 존재)"

        if gap == 0 and priority not in ("critical", "high"):
            continue

        # 점수 계산
        score = (
            prio_w * 3
            + gap * 2
            + (3 if action_plan and not decision else 0)
        )

        if score > 0:
            candidates.append((score, issue_id, title, action_type, action_desc, source))

    candidates.sort(key=lambda x: -x[0])
    lines = []
    for idx, (score, iid, title, atype, adesc, src) in enumerate(candidates[:5], 1):
        lines.append(f"{idx}. [ ] **{iid}** {atype}: {title}")
        lines.append(f"   - {adesc}")

    return lines


def cmd_report(args):
    """주간 예외 보고서 생성 (핵심 요약형)"""
    log.info("주간 예외 보고서 생성 중...")

    rules = TriageRules()
    engine = TriageEngine(rules)
    engine._load_issue_cache()

    today = datetime.now()
    report_lines = [
        "---",
        "title: P5 주간 예외 보고서",
        f"date: {today.strftime('%Y-%m-%d')}",
        "tags: [project/p5, type/report]",
        "---",
        "",
        "# P5 주간 예외 보고서",
        f"> 생성일: {today.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # ── 0. 이번 주 액션 플랜 ──
    report_lines.append("## 이번 주 액션 플랜")
    action_plan_lines = _generate_weekly_action_plan(engine)
    if action_plan_lines:
        report_lines.extend(action_plan_lines)
    else:
        report_lines.append("_액션 플랜 없음_")
    report_lines.append("")

    # ── 1. 이번 주 결정사항 ──
    decisions_dir = VAULT_PATH / "P5-Project" / "04-Decisions"
    report_lines.append("## 이번 주 결정사항")
    recent_decs = []
    if decisions_dir.exists():
        for f in sorted(decisions_dir.glob("DEC-*.md"), reverse=True):
            fm = {}
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                pass
            dec_title = fm.get("title", f.stem)
            dec_by = fm.get("decided_by", "")
            dec_at = fm.get("decided_at", "")
            related = fm.get("related_issues", [])
            ref = f" → {', '.join(str(r) for r in related)}" if related else ""
            recent_decs.append(f"- **{dec_title}** ({dec_by}, {dec_at}){ref}")
            if len(recent_decs) >= 5:
                break

    if recent_decs:
        report_lines.extend(recent_decs)
    else:
        report_lines.append("_없음_")
    report_lines.append("")

    # ── 2. 주목할 미결 이슈 Top 10 (Tier1만) ──
    report_lines.append("## 주목할 미결 이슈 (Tier1 Active)")
    tier1_issues = []
    for issue_id, info in engine._issue_cache.items():
        priority = info.get("priority", "")
        status = info.get("issue_status", "open")
        if priority in ("critical", "high") and status in ("open", "in_progress"):
            score = info.get("triage_score", 0) or 0
            title = info.get("title", "")[:50]
            origin = info.get("source_origin", "")
            tier1_issues.append((score, issue_id, title, priority, origin))

    tier1_issues.sort(key=lambda x: -x[0])
    if tier1_issues:
        for score, iid, title, pri, origin in tier1_issues[:10]:
            score_str = f" (score:{score})" if score else ""
            report_lines.append(f"- [[{iid}]] {title} `{pri}`{score_str} - {origin}")
    else:
        report_lines.append("_없음_")
    report_lines.append("")

    # ── 3. 트렌드 요약 ──
    total_issues = len(engine._issue_cache)
    no_owner = sum(1 for info in engine._issue_cache.values() if not str(info.get("owner", "")).strip())
    no_due_hc = sum(
        1 for info in engine._issue_cache.values()
        if info.get("priority") in ("high", "critical") and not str(info.get("due_date", "")).strip()
    )
    has_decision = sum(1 for info in engine._issue_cache.values() if str(info.get("decision", "")).strip())

    report_lines.extend([
        "## 전체 현황 요약",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 전체 이슈 | {total_issues}건 |",
        f"| 담당자 미지정 | {no_owner}건 ({round(no_owner/max(total_issues,1)*100)}%) |",
        f"| 마감일 없는 H/C | {no_due_hc}건 |",
        f"| 결정 기록 보유 | {has_decision}건 ({round(has_decision/max(total_issues,1)*100)}%) |",
        f"| 리뷰 큐 | {_get_queue_count()}건 미처리 |",
        "",
    ])

    # ── 4. 데이터 품질 경고 (상위 5건만) ──
    report_lines.append("## 데이터 품질 경고")
    warnings = []
    if no_owner > 0:
        warnings.append(f"🔴 담당자 미지정: {no_owner}건")
    if no_due_hc > 0:
        warnings.append(f"🔴 마감일 없는 High/Critical: {no_due_hc}건")

    overdue = 0
    for info in engine._issue_cache.values():
        due_str = str(info.get("due_date", "")).strip()
        status = info.get("issue_status", "")
        if due_str and status not in ("closed", "resolved"):
            try:
                if datetime.strptime(due_str[:10], "%Y-%m-%d") < today:
                    overdue += 1
            except (ValueError, TypeError):
                pass
    if overdue > 0:
        warnings.append(f"🟡 마감 초과: {overdue}건")

    if warnings:
        for w in warnings:
            report_lines.append(f"- {w}")
    else:
        report_lines.append("_경고 없음_")

    report_path = VAULT_PATH / "P5-Project" / "00-Overview" / "주간예외보고서.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(report_lines)
    report_text = report_text.encode("utf-8", errors="replace").decode("utf-8")
    report_path.write_text(report_text, encoding="utf-8")

    log.info(f"보고서 생성: {report_path}")
    log.info(f"  보고서 길이: {len(report_lines)}줄 (이전 669줄 → 핵심 요약)")


# ─── Main ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="P5 메일 트리아지 엔진",
    )

    sub = parser.add_subparsers(dest="command", help="명령어")

    # process
    p_process = sub.add_parser("process", help="새 메일 처리")
    p_process.add_argument("--mail-dir", help="메일 디렉토리 경로")
    p_process.add_argument("--dry-run", action="store_true", help="파일 수정 없이 결과만 표시")
    p_process.add_argument(
        "--auto-apply-above", type=int, default=None, metavar="N",
        help="점수 N 이상은 자동 적용, 미만은 dry-run (예: --auto-apply-above 8). --dry-run 우선."
    )
    p_process.add_argument("--debug", action="store_true")
    p_process.set_defaults(func=cmd_process)

    # score
    p_score = sub.add_parser("score", help="점수 테스트")
    p_score.add_argument("--subject", required=True, help="메일 제목")
    p_score.add_argument("--sender", required=True, help="발신자")
    p_score.add_argument("--body", default="", help="본문")
    p_score.add_argument("--attachment", action="store_true", help="첨부파일 있음")
    p_score.set_defaults(func=cmd_score)

    # report
    p_report = sub.add_parser("report", help="주간 예외 보고서")
    p_report.set_defaults(func=cmd_report)

    # queue
    p_queue = sub.add_parser("queue", help="리뷰 큐 관리")
    p_queue.add_argument("action", choices=["clean", "dedup", "stats"])
    p_queue.add_argument("--max-age", type=int, default=14, help="정리 기준 일수 (기본 14일)")
    p_queue.set_defaults(func=cmd_queue)

    # decide
    p_decide = sub.add_parser("decide", help="결정 기록 생성")
    p_decide.add_argument("--issue", help="관련 이슈 ID (예: SEN-070)")
    p_decide.add_argument("--title", required=True, help="결정 제목")
    p_decide.add_argument("--decision", required=True, help="결정 내용")
    p_decide.add_argument("--decided-by", default="", help="결정자")
    p_decide.set_defaults(func=cmd_decide)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if getattr(args, "debug", False):
        global log
        log = setup_logging(debug=True)

    args.func(args)


if __name__ == "__main__":
    main()

"""
hook_utils.py - 훅 시스템 공통 유틸리티
JSON I/O, 트리거 매칭, 세션 상태 관리, 품질 검사 실행
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ──────────────────────────────────────────────
# 경로 상수
# ──────────────────────────────────────────────
PROJECT_DIR = Path(os.environ.get(
    "CLAUDE_PROJECT_DIR",
    str(Path(__file__).resolve().parent.parent.parent)
))
HOOKS_DIR = PROJECT_DIR / ".claude" / "hooks"
SESSION_STATE_FILE = HOOKS_DIR / "session_state.json"
TRIGGERS_FILE = PROJECT_DIR / "guides" / "manual_triggers.yaml"
GUIDES_DIR = PROJECT_DIR / "guides"

# Python / ruff 경로
VENV_PYTHON = PROJECT_DIR / ".agent_venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


# ──────────────────────────────────────────────
# JSON I/O (stdin/stdout)
# ──────────────────────────────────────────────
def read_stdin_json() -> dict:
    """stdin에서 JSON 파싱. 빈 입력이면 빈 dict 반환."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def write_stdout_json(data: dict):
    """stdout으로 JSON 출력 (훅 응답)."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False))
    sys.stdout.flush()


def write_stderr(msg: str):
    """stderr로 메시지 출력 (차단 사유 등)."""
    sys.stderr.write(msg)
    sys.stderr.flush()


# ──────────────────────────────────────────────
# 트리거 로드 (manual_triggers.yaml)
# ──────────────────────────────────────────────
_triggers_cache = None


def load_triggers() -> dict:
    """manual_triggers.yaml 로드. 캐시 사용."""
    global _triggers_cache
    if _triggers_cache is not None:
        return _triggers_cache
    if not TRIGGERS_FILE.exists():
        _triggers_cache = {"global": {}, "rules": []}
        return _triggers_cache
    try:
        import yaml
        with open(TRIGGERS_FILE, "r", encoding="utf-8") as f:
            _triggers_cache = yaml.safe_load(f) or {"global": {}, "rules": []}
    except ImportError:
        # PyYAML 미설치 시 간단 파싱
        _triggers_cache = _parse_yaml_fallback()
    except Exception:
        _triggers_cache = {"global": {}, "rules": []}
    return _triggers_cache


def _parse_yaml_fallback() -> dict:
    """PyYAML 없을 때 최소 파싱 (global.always_load만 추출)."""
    result = {"global": {"always_load": []}, "rules": []}
    try:
        with open(TRIGGERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("- guides/") or stripped.startswith("- .agent/"):
                    result["global"]["always_load"].append(stripped[2:])
    except Exception:
        pass
    return result


# ──────────────────────────────────────────────
# 트리거 매칭
# ──────────────────────────────────────────────
def match_path_triggers(file_path: str) -> list[str]:
    """경로 기반 트리거 매칭. 매칭된 가이드라인 경로 목록 반환."""
    triggers = load_triggers()
    matched = set()
    # 상대 경로로 변환
    try:
        rel_path = str(Path(file_path).resolve().relative_to(PROJECT_DIR)).replace("\\", "/")
    except ValueError:
        rel_path = file_path.replace("\\", "/")

    for rule in triggers.get("rules", []):
        if rule.get("type") != "path":
            continue
        # any_prefix 매칭
        for prefix in rule.get("any_prefix", []):
            if rel_path.startswith(prefix):
                matched.update(rule.get("activate", []))
        # any_suffix 매칭
        for suffix in rule.get("any_suffix", []):
            if rel_path.endswith(suffix):
                matched.update(rule.get("activate", []))
    return list(matched)


def match_keyword_triggers(text: str) -> list[str]:
    """키워드/의도 기반 트리거 매칭."""
    if not text:
        return []
    triggers = load_triggers()
    matched = set()
    text_lower = text.lower()

    for rule in triggers.get("rules", []):
        rule_type = rule.get("type", "")
        if rule_type not in ("keyword", "intent"):
            continue
        keywords = rule.get("any", [])
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.update(rule.get("activate", []))
                break  # 하나만 매칭되면 해당 규칙의 모든 activate 추가
    return list(matched)


def get_always_load_guides() -> list[str]:
    """항상 로드할 가이드라인 목록."""
    triggers = load_triggers()
    return triggers.get("global", {}).get("always_load", [])


# ──────────────────────────────────────────────
# 가이드라인 요약 추출
# ──────────────────────────────────────────────
def load_guide_summary(guide_rel_path: str) -> str:
    """가이드라인 파일에서 핵심 규칙 섹션만 추출.
    ## 필수 규칙, ## 구현 규칙, ## 금지 항목 등 핵심 섹션만 반환.
    없으면 처음 500자 반환.
    """
    guide_path = PROJECT_DIR / guide_rel_path
    if not guide_path.exists():
        return ""

    try:
        content = guide_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    # 핵심 섹션 추출
    key_sections = []
    current_section = None
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## "):
            # 이전 섹션 저장
            if current_section and _is_key_section(current_section):
                key_sections.append(f"{current_section}\n" + "\n".join(current_lines))
            current_section = line
            current_lines = []
        elif current_section:
            current_lines.append(line)

    # 마지막 섹션
    if current_section and _is_key_section(current_section):
        key_sections.append(f"{current_section}\n" + "\n".join(current_lines))

    if key_sections:
        result = "\n".join(key_sections).strip()
        # 토큰 절약: 최대 800자
        return result[:800] if len(result) > 800 else result

    # 핵심 섹션 없으면 처음 500자
    return content[:500].strip()


def _is_key_section(header: str) -> bool:
    """핵심 섹션인지 판별."""
    key_words = ["규칙", "필수", "금지", "완료", "체크", "에러", "보안",
                 "rule", "required", "must", "check", "error"]
    header_lower = header.lower()
    return any(kw in header_lower for kw in key_words)


# ──────────────────────────────────────────────
# 세션 상태 관리
# ──────────────────────────────────────────────
def load_session_state() -> dict:
    """session_state.json 로드. 없으면 초기 상태 반환."""
    if SESSION_STATE_FILE.exists():
        try:
            with open(SESSION_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_session_state()


def save_session_state(state: dict):
    """session_state.json 원자적 저장."""
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(HOOKS_DIR), suffix=".tmp", prefix="session_state_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(SESSION_STATE_FILE))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _empty_session_state() -> dict:
    return {
        "session_start": datetime.now(timezone.utc).isoformat(),
        "modified_files": {},
        "total_modifications": 0,
        "qa_pass_count": 0,
        "qa_fail_count": 0,
        "walkthrough_detected": False,
        "stop_hook_active": False,
    }


def init_session_state() -> dict:
    """세션 상태 초기화 (새 세션용)."""
    state = _empty_session_state()
    save_session_state(state)
    return state


# ──────────────────────────────────────────────
# 품질 검사 실행
# ──────────────────────────────────────────────
def run_quality_check(file_path: str) -> dict:
    """파일 타입별 품질 검사 실행.
    Returns: {"qa_result": "PASS"|"FAIL", "checks": [...], "errors": [...]}
    """
    ext = Path(file_path).suffix.lower()
    checks = []
    errors = []

    if ext == ".py":
        checks, errors = _check_python(file_path)
    elif ext == ".json":
        checks, errors = _check_json(file_path)
    elif ext == ".md":
        checks, errors = _check_markdown(file_path)
    else:
        checks.append(f"skip:{ext} (no checker)")

    qa_result = "FAIL" if errors else "PASS"
    return {"qa_result": qa_result, "checks": checks, "errors": errors}


def _check_python(file_path: str) -> tuple[list, list]:
    """Python 파일 검사: py_compile + ruff."""
    checks = []
    errors = []

    # 1. py_compile
    try:
        result = subprocess.run(
            [PYTHON, "-m", "py_compile", file_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            checks.append("py_compile:OK")
        else:
            err_msg = (result.stderr or result.stdout).strip()
            checks.append("py_compile:FAIL")
            errors.append(f"py_compile: {err_msg[:300]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        checks.append(f"py_compile:ERROR({type(e).__name__})")

    # 2. ruff check
    try:
        result = subprocess.run(
            ["ruff", "check", file_path, "--no-fix"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            checks.append("ruff:OK")
        else:
            err_msg = (result.stdout or result.stderr).strip()
            # ruff 경고만이면 PASS 처리 (에러만 FAIL)
            if "error" in err_msg.lower():
                checks.append("ruff:FAIL")
                errors.append(f"ruff: {err_msg[:300]}")
            else:
                checks.append(f"ruff:WARN")
                # 경고는 errors에 넣지 않음
    except FileNotFoundError:
        checks.append("ruff:NOT_FOUND")
    except subprocess.TimeoutExpired:
        checks.append("ruff:TIMEOUT")

    return checks, errors


def _check_json(file_path: str) -> tuple[list, list]:
    """JSON 파일 유효성 검사."""
    checks = []
    errors = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            json.load(f)
        checks.append("json_valid:OK")
    except json.JSONDecodeError as e:
        checks.append("json_valid:FAIL")
        errors.append(f"JSON parse error: {str(e)[:200]}")
    except Exception as e:
        checks.append(f"json_valid:ERROR({type(e).__name__})")
    return checks, errors


def _check_markdown(file_path: str) -> tuple[list, list]:
    """Markdown 파일 검사: YAML 프론트매터 유효성."""
    checks = []
    errors = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        checks.append("read:ERROR")
        return checks, errors

    # YAML 프론트매터 검사 (--- ... --- 패턴)
    if content.startswith("---"):
        end_idx = content.find("---", 3)
        if end_idx > 0:
            frontmatter = content[3:end_idx].strip()
            try:
                import yaml
                yaml.safe_load(frontmatter)
                checks.append("frontmatter:OK")
            except ImportError:
                checks.append("frontmatter:SKIP(no yaml)")
            except Exception as e:
                checks.append("frontmatter:FAIL")
                errors.append(f"YAML frontmatter invalid: {str(e)[:200]}")
        else:
            checks.append("frontmatter:UNCLOSED")
            errors.append("YAML frontmatter block not properly closed")
    else:
        checks.append("frontmatter:NONE")

    return checks, errors


# ──────────────────────────────────────────────
# walkthrough 감지
# ──────────────────────────────────────────────
WALKTHROUGH_PATTERNS = [
    "변경 내역", "수정된 파일", "셀프 리뷰", "검증 결과",
    "walkthrough", "작업 보고서", "보고서",
    "Gate 1", "Gate 2", "Gate 3",
    "quality gate", "품질 검사",
]


def detect_walkthrough(text: str) -> bool:
    """텍스트에서 walkthrough/리뷰 패턴 감지."""
    if not text:
        return False
    text_lower = text.lower()
    match_count = sum(1 for p in WALKTHROUGH_PATTERNS if p.lower() in text_lower)
    return match_count >= 2  # 2개 이상 패턴 매칭 시 walkthrough로 간주

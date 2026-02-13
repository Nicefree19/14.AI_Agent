"""
P5 OCR Pipeline — 이메일 첨부파일 자동 인식 CLI

GLM-OCR (Ollama) 기반 첨부파일 OCR + 도면번호/테이블 추출 + 이슈 연계

Usage:
    python p5_ocr_pipeline.py health              # Ollama + glm-ocr 상태 확인
    python p5_ocr_pipeline.py process             # 미처리 첨부파일 전체 OCR
    python p5_ocr_pipeline.py process --limit 5   # 최근 5건만
    python p5_ocr_pipeline.py link                # 도면번호 → SEN 이슈 매칭
    python p5_ocr_pipeline.py link --min-confidence 0.8  # 고확신도만 링킹
    python p5_ocr_pipeline.py correct             # 저확신도 도면번호 목록
    python p5_ocr_pipeline.py correct --interactive  # 대화형 교정
    python p5_ocr_pipeline.py status              # OCR 처리 통계
"""

import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Set

import yaml

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── 경로 설정 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
INBOX_DIR = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"
CONFIG_PATH = VAULT_PATH / "_config" / "p5-sync-config.yaml"
LOG_FILE = SCRIPT_DIR / "p5_ocr_pipeline.log"

# ─── 로깅 설정 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("p5_ocr")


def load_config() -> dict:
    """p5-sync-config.yaml에서 OCR 설정 로드."""
    if not CONFIG_PATH.exists():
        log.warning("설정 파일 없음: %s", CONFIG_PATH)
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("ocr", {})


def create_ocr_client(cfg: dict):
    """설정에서 GlmOcrClient 생성."""
    from ocr.glm_ocr_client import GlmOcrClient
    from ocr.image_preprocessor import ImagePreprocessor, PreprocessConfig

    cache_dir = VAULT_PATH / ".cache" / "ocr"

    # 전처리기 설정
    preprocess_cfg = PreprocessConfig.from_yaml(cfg.get("preprocessing", {}))
    preprocessor = ImagePreprocessor(preprocess_cfg) if preprocess_cfg.enabled else None
    if preprocessor:
        log.info("이미지 전처리 활성화")

    return GlmOcrClient(
        base_url=cfg.get("ollama_url", "http://localhost:11434"),
        model=cfg.get("model", "glm-ocr"),
        timeout_image=cfg.get("timeout_per_image_sec", 60),
        timeout_pdf_page=cfg.get("timeout_per_image_sec", 60) * 2,
        max_retries=cfg.get("retry_count", 3),
        cache_dir=cache_dir if cfg.get("cache_enabled", True) else None,
        preprocessor=preprocessor,
    )


def load_correction_manager(cfg: dict):
    """설정에서 CorrectionManager 로드. 비활성이면 None."""
    corr_cfg = cfg.get("corrections", {})
    if not corr_cfg.get("enabled", False):
        return None
    from ocr.correction_manager import CorrectionManager
    corr_path = PROJECT_ROOT / corr_cfg.get(
        "corrections_file",
        "ResearchVault/_config/ocr-corrections.yaml",
    )
    return CorrectionManager(corr_path)


def create_processor(cfg: dict, ocr_client):
    """설정에서 AttachmentProcessor 생성."""
    from ocr.attachment_processor import AttachmentProcessor

    attach_dir_rel = cfg.get("attachment_dir", "ResearchVault/00-Inbox/Messages/Emails/Attachments")
    attach_dir = PROJECT_ROOT / attach_dir_rel

    correction_manager = load_correction_manager(cfg)
    if correction_manager:
        log.info("OCR 교정 활성화 (별칭 %d건)", len(correction_manager.aliases))

    return AttachmentProcessor(
        ocr_client=ocr_client,
        attachment_base_dir=attach_dir,
        max_pages_per_pdf=cfg.get("max_pages_per_pdf", 10),
        max_file_size_mb=cfg.get("max_file_size_mb", 50),
        ocr_extensions=set(cfg.get("eligible_extensions", [".pdf", ".png", ".jpg", ".jpeg"])),
        skip_extensions=set(cfg.get("skip_extensions", [".dwg", ".dxf", ".zip", ".rar", ".exe"])),
        correction_manager=correction_manager,
    )


# ═════════════════════════════════════════════════════════════════
# 명령어: health
# ═════════════════════════════════════════════════════════════════

def cmd_health(args):
    """Ollama + GLM-OCR 환경 확인."""
    cfg = load_config()
    log.info("=" * 50)
    log.info("GLM-OCR 환경 확인")
    log.info("=" * 50)

    # 1. 설정 확인
    ollama_url = cfg.get("ollama_url", "http://localhost:11434")
    model = cfg.get("model", "glm-ocr")
    log.info("Ollama URL: %s", ollama_url)
    log.info("모델: %s", model)
    log.info("OCR 활성화: %s", cfg.get("enabled", True))

    # 2. Ollama 연결
    client = create_ocr_client(cfg)

    try:
        import requests
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            log.info("Ollama 연결: OK")
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            log.info("설치된 모델: %s", models)
        else:
            log.error("Ollama 연결 실패: HTTP %d", resp.status_code)
            return False
    except requests.ConnectionError:
        log.error("Ollama 미실행: %s 에 연결할 수 없습니다", ollama_url)
        log.info("해결: ollama serve 또는 Ollama 앱 실행")
        return False
    except Exception as e:
        log.error("Ollama 확인 오류: %s", e)
        return False

    # 3. 모델 확인
    if client.is_available():
        log.info("GLM-OCR 모델: OK (사용 가능)")
        info = client.get_model_info()
        if info:
            details = info.get("details", {})
            log.info("  파라미터: %s", details.get("parameter_size", "N/A"))
            log.info("  양자화: %s", details.get("quantization_level", "N/A"))
    else:
        log.warning("GLM-OCR 모델 미설치")
        log.info("해결: ollama pull glm-ocr")
        return False

    # 4. 경로 확인
    log.info("─" * 50)
    log.info("이메일 디렉토리: %s (%s)", INBOX_DIR, "존재" if INBOX_DIR.exists() else "없음")
    log.info("이슈 디렉토리: %s (%s)", ISSUES_DIR, "존재" if ISSUES_DIR.exists() else "없음")

    attach_dir_rel = cfg.get("attachment_dir", "ResearchVault/00-Inbox/Messages/Emails/Attachments")
    attach_dir = PROJECT_ROOT / attach_dir_rel
    log.info("첨부파일 디렉토리: %s", attach_dir)

    # 5. PyMuPDF 확인
    try:
        import fitz
        log.info("PyMuPDF: OK (v%s)", fitz.version[0])
    except ImportError:
        log.warning("PyMuPDF 미설치: pip install PyMuPDF")

    log.info("=" * 50)
    log.info("환경 확인 완료")
    return True


# ═════════════════════════════════════════════════════════════════
# 명령어: process
# ═════════════════════════════════════════════════════════════════

def cmd_process(args):
    """미처리 이메일 첨부파일 OCR 실행."""
    cfg = load_config()

    if not cfg.get("enabled", True):
        log.info("OCR 비활성화 (config: ocr.enabled=false)")
        return

    # Ollama 연결 확인
    client = create_ocr_client(cfg)
    if not client.is_available():
        log.warning("Ollama/GLM-OCR 사용 불가 — OCR 스킵")
        return

    processor = create_processor(cfg, client)

    # Outlook 어댑터 (선택적) — context manager로 COM 라이프사이클 관리
    outlook = None
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from adapters.outlook_adapter import OutlookAdapter
        outlook = OutlookAdapter()
        if outlook.initialize():
            log.info("Outlook 연결됨")
        else:
            log.warning("Outlook 연결 실패 — 기존 파일만 처리")
            outlook = None
    except Exception as e:
        log.warning("Outlook 어댑터 로드 실패: %s", e)
        outlook = None

    # 처리 대상 이메일 수집
    if not INBOX_DIR.exists():
        log.error("이메일 디렉토리 없음: %s", INBOX_DIR)
        return

    email_files = sorted(INBOX_DIR.glob("*.md"), reverse=True)  # 최신 순
    processed_stems = processor.get_processed_emails()

    candidates = []
    for ef in email_files:
        if not args.force and ef.stem in processed_stems:
            continue
        if processor.is_email_processable(ef):
            candidates.append(ef)

    if args.limit and args.limit > 0:
        candidates = candidates[:args.limit]

    log.info("─" * 50)
    log.info(
        "OCR 처리 대상: %d건 (전체 %d건, 처리완료 %d건)",
        len(candidates), len(email_files), len(processed_stems),
    )

    if not candidates:
        log.info("처리할 이메일 없음")
        return

    # OCR 실행
    total_drawings = set()
    total_tables = 0
    processed = 0
    errors = 0

    for idx, email_file in enumerate(candidates, 1):
        log.info(
            "[%d/%d] %s",
            idx, len(candidates), email_file.stem[:60],
        )
        result = processor.process_email(
            email_file, outlook_adapter=outlook, force=args.force,
        )

        if result.errors:
            errors += 1
            for err in result.errors:
                log.warning("  오류: %s", err)
        else:
            processed += 1

        total_drawings.update(result.drawing_numbers)
        total_tables += result.tables_found

        log.info(
            "  첨부: %d, OCR: %d, 도면번호: %d, 테이블: %d",
            result.attachment_count, result.ocr_processed,
            len(result.drawing_numbers), result.tables_found,
        )

    # Outlook 어댑터 정리
    if outlook is not None:
        try:
            outlook.close()
        except Exception:
            pass

    # 요약
    log.info("─" * 50)
    log.info(
        "OCR 완료: 처리 %d건, 오류 %d건, 도면번호 %d종, 테이블 %d개",
        processed, errors, len(total_drawings), total_tables,
    )
    if total_drawings:
        log.info("추출된 도면번호: %s", ", ".join(sorted(total_drawings)[:20]))
        if len(total_drawings) > 20:
            log.info("  ... 외 %d종", len(total_drawings) - 20)


# ═════════════════════════════════════════════════════════════════
# 명령어: link
# ═════════════════════════════════════════════════════════════════

def cmd_link(args):
    """도면번호 → SEN 이슈 매칭 + frontmatter 보강."""
    cfg = load_config()

    attach_dir_rel = cfg.get("attachment_dir", "ResearchVault/00-Inbox/Messages/Emails/Attachments")
    attach_dir = PROJECT_ROOT / attach_dir_rel

    if not attach_dir.exists():
        log.info("첨부파일 디렉토리 없음: %s", attach_dir)
        return

    # 확신도 필터 (CLI 인자 우선 → config fallback)
    min_conf = getattr(args, "min_confidence", None)
    if min_conf is None:
        conf_cfg = cfg.get("confidence", {})
        min_conf = conf_cfg.get("link_threshold", 0.0)

    # 1. 모든 .ocr.md 파일에서 도면번호 수집 (확신도 필터링)
    drawing_to_emails: Dict[str, List[str]] = {}  # drawing_number → [email_stems]
    ocr_files = list(attach_dir.rglob("*.ocr.md"))
    skipped_low_conf = 0

    for ocr_file in ocr_files:
        try:
            text = ocr_file.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            end = text.find("---", 3)
            if end == -1:
                continue
            fm = yaml.safe_load(text[3:end]) or {}
            nums = fm.get("drawing_numbers", [])
            email_stem = ocr_file.parent.name  # Attachments/{email_stem}/
            for n in nums:
                # 양 포맷 호환: dict (신규) / str (레거시)
                if isinstance(n, dict):
                    num = str(n.get("number", "")).upper()
                    conf = float(n.get("confidence", 0.5))
                else:
                    num = str(n).upper()
                    conf = 0.5  # 레거시 포맷
                if not num:
                    continue
                if conf < min_conf:
                    skipped_low_conf += 1
                    continue
                drawing_to_emails.setdefault(num, []).append(email_stem)
        except Exception:
            pass

    log.info("OCR 도면번호: %d종 (파일 %d개)", len(drawing_to_emails), len(ocr_files))
    if min_conf > 0:
        log.info("  확신도 필터: ≥%.2f (제외 %d건)", min_conf, skipped_low_conf)
    if not drawing_to_emails:
        log.info("연계할 도면번호 없음")
        return

    # 2. SEN 이슈 파일 스캔 → related_docs 필드 매칭
    if not ISSUES_DIR.exists():
        log.error("이슈 디렉토리 없음: %s", ISSUES_DIR)
        return

    issue_files = list(ISSUES_DIR.glob("*.md"))
    matched = 0
    updated_issues = 0

    for issue_file in issue_files:
        try:
            text = issue_file.read_text(encoding="utf-8")
        except Exception:
            continue

        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end == -1:
            continue

        try:
            fm = yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError:
            continue

        issue_id = fm.get("issue_id", "")
        related_docs = str(fm.get("related_docs", ""))
        title = str(fm.get("title", ""))
        description = str(fm.get("description", ""))

        # 이미 OCR 연계된 경우 스킵
        existing_refs = fm.get("ocr_drawing_refs", [])

        # 이슈 텍스트에서 도면번호 매칭
        issue_text = f"{issue_id} {related_docs} {title} {description}".upper()
        matched_drawings = []
        matched_emails = set()

        for dnum, email_stems in drawing_to_emails.items():
            if dnum in issue_text:
                matched_drawings.append(dnum)
                matched_emails.update(email_stems)
                matched += 1

        # 새로운 도면번호가 있으면 frontmatter 갱신
        new_refs = sorted(set(matched_drawings) - set(existing_refs))
        if new_refs and not args.dry_run:
            # frontmatter에 ocr_drawing_refs 추가
            all_refs = sorted(set(existing_refs) | set(matched_drawings))
            if "ocr_drawing_refs" in text[3:end]:
                # 기존 필드 교체
                import re
                new_fm_text = re.sub(
                    r"ocr_drawing_refs:.*?(?=\n\w|\n---)",
                    f"ocr_drawing_refs: {all_refs}\n",
                    text[3:end],
                    flags=re.DOTALL,
                )
                new_text = f"---{new_fm_text}---{text[end+3:]}"
            else:
                # 새 필드 추가 (--- 바로 앞에)
                insert_line = f"ocr_drawing_refs: {all_refs}\n"
                new_text = f"---\n{text[4:end]}{insert_line}---{text[end+3:]}"

            issue_file.write_text(new_text, encoding="utf-8")
            updated_issues += 1
            log.info(
                "  이슈 갱신: %s ← %s",
                issue_id, new_refs,
            )
        elif new_refs and args.dry_run:
            log.info(
                "  [DRY-RUN] %s ← %s",
                issue_id, new_refs,
            )

    log.info("─" * 50)
    log.info(
        "이슈 연계: %d건 매칭, %d건 갱신",
        matched, updated_issues,
    )


# ═════════════════════════════════════════════════════════════════
# 명령어: correct
# ═════════════════════════════════════════════════════════════════

def cmd_correct(args):
    """저확신도 도면번호 조회 + 대화형 교정."""
    cfg = load_config()
    corr_mgr = load_correction_manager(cfg)
    if corr_mgr is None:
        # 교정 비활성이어도 조회는 가능하게
        from ocr.correction_manager import CorrectionManager
        corr_cfg = cfg.get("corrections", {})
        corr_path = PROJECT_ROOT / corr_cfg.get(
            "corrections_file",
            "ResearchVault/_config/ocr-corrections.yaml",
        )
        corr_mgr = CorrectionManager(corr_path)

    attach_dir_rel = cfg.get("attachment_dir", "ResearchVault/00-Inbox/Messages/Emails/Attachments")
    attach_dir = PROJECT_ROOT / attach_dir_rel

    threshold = args.threshold
    low_items = corr_mgr.get_low_confidence_items(attach_dir, threshold)

    log.info("=" * 50)
    log.info("OCR 도면번호 교정")
    log.info("=" * 50)
    log.info("기존 별칭: %d건", len(corr_mgr.aliases))
    log.info("확신도 임계값: %.2f", threshold)
    log.info("저확신도 도면번호: %d건", len(low_items))

    if not low_items:
        log.info("교정 대상 없음")
        return

    # 목록 출력
    for i, item in enumerate(low_items, 1):
        log.info(
            "  %3d. %-15s (확신도: %.2f, 출처: %s)",
            i, item["number"], item["confidence"], item["source"],
        )

    if not args.interactive:
        log.info("대화형 교정: --interactive 플래그 사용")
        return

    # 대화형 교정
    log.info("")
    log.info("대화형 교정 모드 (Enter=스킵, 'q'=종료)")
    corrections_made = 0

    for item in low_items:
        try:
            answer = input(f"  {item['number']} (conf={item['confidence']:.2f}) → 올바른 도면번호? ")
        except (EOFError, KeyboardInterrupt):
            break

        answer = answer.strip()
        if answer.lower() == "q":
            break
        if not answer:
            continue

        corr_mgr.add_correction(item["number"], answer)
        corrections_made += 1

    if corrections_made > 0:
        corr_mgr.save()
        log.info("교정 %d건 저장 완료", corrections_made)
    else:
        log.info("교정 없음")


# ═════════════════════════════════════════════════════════════════
# 명령어: status
# ═════════════════════════════════════════════════════════════════

def cmd_status(args):
    """OCR 처리 통계 표시."""
    cfg = load_config()

    attach_dir_rel = cfg.get("attachment_dir", "ResearchVault/00-Inbox/Messages/Emails/Attachments")
    attach_dir = PROJECT_ROOT / attach_dir_rel

    log.info("=" * 50)
    log.info("P5 OCR 파이프라인 현황")
    log.info("=" * 50)

    # 이메일 통계
    email_count = 0
    if INBOX_DIR.exists():
        email_count = len(list(INBOX_DIR.glob("*.md")))
    log.info("전체 이메일: %d건", email_count)

    # 첨부파일 통계
    processed_emails = 0
    total_attachments = 0
    total_ocr_files = 0
    all_drawings = set()
    total_tables = 0

    if attach_dir.exists():
        for email_dir in attach_dir.iterdir():
            if not email_dir.is_dir():
                continue
            processed_emails += 1

            for f in email_dir.iterdir():
                if f.suffix.lower() == ".md" and f.name.endswith(".ocr.md"):
                    total_ocr_files += 1
                    # 도면번호 수집
                    try:
                        text = f.read_text(encoding="utf-8")
                        if text.startswith("---"):
                            end = text.find("---", 3)
                            if end > 0:
                                fm = yaml.safe_load(text[3:end]) or {}
                                for d in fm.get("drawing_numbers", []):
                                    all_drawings.add(str(d))
                                total_tables += fm.get("tables_found", 0)
                    except Exception:
                        pass
                elif not f.name.endswith(".ocr.md"):
                    total_attachments += 1

    log.info("처리된 이메일: %d건", processed_emails)
    log.info("첨부파일: %d개", total_attachments)
    log.info("OCR 결과: %d개", total_ocr_files)
    log.info("추출된 도면번호: %d종", len(all_drawings))
    log.info("추출된 테이블: %d개", total_tables)

    # 이슈 연계 통계
    linked_issues = 0
    if ISSUES_DIR.exists():
        for issue_file in ISSUES_DIR.glob("*.md"):
            try:
                text = issue_file.read_text(encoding="utf-8")
                if "ocr_drawing_refs:" in text[:500]:
                    linked_issues += 1
            except Exception:
                pass
    log.info("OCR 연계 이슈: %d건", linked_issues)

    # Ollama 상태
    log.info("─" * 50)
    try:
        client = create_ocr_client(cfg)
        if client.is_available():
            log.info("Ollama/GLM-OCR: 사용 가능")
        else:
            log.info("Ollama/GLM-OCR: 사용 불가")
    except Exception:
        log.info("Ollama/GLM-OCR: 확인 불가")

    if all_drawings:
        log.info("─" * 50)
        log.info("도면번호 목록 (상위 20):")
        for d in sorted(all_drawings)[:20]:
            log.info("  - %s", d)

    log.info("=" * 50)


# ═════════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="P5 OCR Pipeline — 이메일 첨부파일 자동 인식",
    )
    sub = parser.add_subparsers(dest="command", help="명령어")

    # health
    p_health = sub.add_parser("health", help="Ollama + GLM-OCR 환경 확인")

    # process
    p_process = sub.add_parser("process", help="첨부파일 OCR 처리")
    p_process.add_argument("--limit", type=int, default=0, help="최대 처리 건수")
    p_process.add_argument("--force", action="store_true", help="이미 처리된 파일도 재처리")

    # link
    p_link = sub.add_parser("link", help="도면번호 → 이슈 매칭")
    p_link.add_argument("--dry-run", action="store_true", help="변경 없이 미리보기")
    p_link.add_argument("--min-confidence", type=float, default=None, help="최소 확신도 필터 (미지정 시 config 사용)")

    # correct
    p_correct = sub.add_parser("correct", help="저확신도 도면번호 교정")
    p_correct.add_argument("--interactive", action="store_true", help="대화형 교정 모드")
    p_correct.add_argument("--threshold", type=float, default=0.6, help="확신도 임계값 (기본: 0.6)")

    # status
    p_status = sub.add_parser("status", help="OCR 처리 통계")

    args = parser.parse_args()

    if args.command == "health":
        if not cmd_health(args):
            sys.exit(1)
    elif args.command == "process":
        cmd_process(args)
    elif args.command == "link":
        cmd_link(args)
    elif args.command == "correct":
        cmd_correct(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

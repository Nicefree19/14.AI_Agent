"""
Attachment Processor — 이메일 첨부파일 다운로드 + OCR 오케스트레이션

이메일 → 첨부파일 저장 → GLM-OCR 실행 → 사이드카 .ocr.md 생성 → 도면번호/테이블 추출
"""

import logging
import re
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Dict, Any, TYPE_CHECKING

from .glm_ocr_client import GlmOcrClient, OcrResult
from .drawing_extractor import DrawingExtractor, DrawingInfo
from .table_extractor import TableExtractor, ExtractedTable

if TYPE_CHECKING:
    from .correction_manager import CorrectionManager

log = logging.getLogger(__name__)

# ─── 파일 확장자 필터 ────────────────────────────────────────────
OCR_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SKIP_EXTENSIONS = {".dwg", ".dxf", ".zip", ".rar", ".7z", ".exe", ".dll"}
MAX_FILE_SIZE_MB = 50


@dataclass
class AttachmentResult:
    """이메일 첨부파일 처리 결과."""
    email_file: str
    email_id: str
    attachment_count: int = 0
    ocr_processed: int = 0
    ocr_skipped: int = 0
    drawing_numbers: List[str] = field(default_factory=list)
    tables_found: int = 0
    sidecar_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AttachmentProcessor:
    """이메일 첨부파일 OCR 오케스트레이션.

    1. 이메일 frontmatter에서 EntryID 파싱
    2. Attachments/{email_stem}/ 디렉토리 생성
    3. OutlookAdapter.get_attachments() 호출
    4. OCR 대상 파일 필터링
    5. GLM-OCR 실행 (PDF→페이지별, 이미지→직접)
    6. 사이드카 .ocr.md 파일 생성
    7. 도면번호 + 테이블 추출
    """

    def __init__(
        self,
        ocr_client: GlmOcrClient,
        attachment_base_dir: Path,
        max_pages_per_pdf: int = 10,
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        ocr_extensions: Optional[Set[str]] = None,
        skip_extensions: Optional[Set[str]] = None,
        correction_manager: Optional["CorrectionManager"] = None,
    ):
        self.ocr_client = ocr_client
        self.attachment_base_dir = Path(attachment_base_dir)
        self.max_pages = max_pages_per_pdf
        self.max_file_size = max_file_size_mb * 1024 * 1024  # bytes
        self.ocr_extensions = ocr_extensions or OCR_EXTENSIONS
        self.skip_extensions = skip_extensions or SKIP_EXTENSIONS
        self.drawing_extractor = DrawingExtractor(
            ocr_client, correction_manager=correction_manager,
        )
        self.table_extractor = TableExtractor(ocr_client)

    def process_email(
        self,
        email_file: Path,
        outlook_adapter=None,
        force: bool = False,
    ) -> AttachmentResult:
        """이메일 파일의 첨부파일 OCR 처리.

        Args:
            email_file: 이메일 마크다운 파일 경로
            outlook_adapter: OutlookAdapter 인스턴스 (첨부파일 다운로드용)
            force: True면 이미 처리된 이메일도 재처리

        Returns:
            AttachmentResult 처리 결과
        """
        email_file = Path(email_file)
        result = AttachmentResult(
            email_file=str(email_file),
            email_id="",
        )

        # 1. Frontmatter 파싱
        frontmatter = self._parse_frontmatter(email_file)
        if not frontmatter:
            result.errors.append("frontmatter 파싱 실패")
            return result

        email_id = frontmatter.get("id", "")
        result.email_id = email_id

        if not email_id:
            result.errors.append("이메일 ID 없음")
            return result

        # 2. 출력 디렉토리
        email_stem = email_file.stem
        attach_dir = self.attachment_base_dir / email_stem

        # 이미 처리된 경우 스킵
        if not force and attach_dir.exists() and self._has_ocr_results(attach_dir):
            log.debug("이미 처리됨, 스킵: %s", email_stem)
            # 기존 결과에서 도면번호 로드
            result.drawing_numbers = self._load_existing_drawings(attach_dir)
            result.tables_found = self._count_existing_tables(attach_dir)
            return result

        # 3. 첨부파일 다운로드
        if outlook_adapter:
            try:
                saved_files = outlook_adapter.get_attachments(email_id, attach_dir)
                result.attachment_count = len(saved_files)
                log.info(
                    "첨부파일 %d개 저장: %s",
                    len(saved_files), email_stem,
                )
            except Exception as e:
                result.errors.append(f"첨부파일 다운로드 실패: {e}")
                log.warning("첨부파일 다운로드 실패 (%s): %s", email_stem, e)
                return result
        else:
            # Outlook 없이 기존 다운로드된 파일로 처리
            if attach_dir.exists():
                saved_files = list(attach_dir.iterdir())
                result.attachment_count = len(saved_files)
            else:
                result.errors.append("첨부파일 디렉토리 없음, Outlook 미연결")
                return result

        # 4. OCR 처리
        all_drawing_numbers = set()

        for fpath in sorted(attach_dir.iterdir()):
            if fpath.suffix.lower() == ".md":
                continue  # 사이드카 파일 스킵
            if fpath.suffix.lower() in self.skip_extensions:
                result.ocr_skipped += 1
                continue
            if fpath.suffix.lower() not in self.ocr_extensions:
                result.ocr_skipped += 1
                continue
            if fpath.stat().st_size > self.max_file_size:
                result.ocr_skipped += 1
                log.warning(
                    "파일 크기 초과, 스킵: %s (%.1fMB)",
                    fpath.name, fpath.stat().st_size / 1024 / 1024,
                )
                continue

            try:
                sidecar = self._process_single_file(fpath, all_drawing_numbers, result)
                if sidecar:
                    result.sidecar_files.append(str(sidecar))
                    result.ocr_processed += 1
            except Exception as e:
                result.errors.append(f"OCR 실패 ({fpath.name}): {e}")
                log.warning("OCR 실패 (%s): %s", fpath.name, e)

        result.drawing_numbers = sorted(all_drawing_numbers)
        return result

    def is_email_processable(self, email_file: Path) -> bool:
        """이메일이 OCR 처리 대상인지 확인."""
        fm = self._parse_frontmatter(email_file)
        if not fm:
            return False
        # has_attachments가 frontmatter에 있으면 활용
        has_attach = fm.get("has_attachments", None)
        if has_attach is not None:
            return bool(has_attach)
        # 없으면 ID 존재 여부로 판단 (실제 다운로드 시도 필요)
        return bool(fm.get("id"))

    def get_processed_emails(self) -> Set[str]:
        """이미 OCR 처리된 이메일 stem 목록."""
        processed = set()
        if self.attachment_base_dir.exists():
            for d in self.attachment_base_dir.iterdir():
                if d.is_dir() and self._has_ocr_results(d):
                    processed.add(d.name)
        return processed

    # ─── 단일 파일 처리 ──────────────────────────────────────────

    def _process_single_file(
        self,
        file_path: Path,
        all_drawings: Set[str],
        result: AttachmentResult,
    ) -> Optional[Path]:
        """단일 첨부파일 OCR + 사이드카 생성."""
        log.info("  OCR 처리: %s", file_path.name)

        drawing_infos: List[DrawingInfo] = []
        tables: List[ExtractedTable] = []
        ocr_results: List[OcrResult] = []

        if file_path.suffix.lower() == ".pdf":
            # PDF: 도면번호 + 테이블 각각 추출
            drawing_infos = self.drawing_extractor.extract_from_pdf(
                file_path, self.max_pages,
            )
            tables = self.table_extractor.extract_tables_from_pdf(
                file_path, self.max_pages,
            )
            # 일반 OCR 텍스트도 수집
            ocr_results = self.ocr_client.ocr_pdf(file_path, self.max_pages)
        else:
            # 이미지
            di = self.drawing_extractor.extract_from_image(file_path)
            drawing_infos = [di]
            tables = self.table_extractor.extract_tables_from_image(file_path)
            ocr_results = [self.ocr_client.ocr_image(file_path)]

        # 도면번호 수집
        drawings = self.drawing_extractor.extract_all_numbers(drawing_infos)
        all_drawings.update(drawings)
        result.tables_found += len(tables)

        # 사이드카 파일 생성
        sidecar_path = file_path.parent / f"{file_path.name}.ocr.md"
        self._write_sidecar(
            sidecar_path=sidecar_path,
            source_file=file_path,
            ocr_results=ocr_results,
            drawing_infos=drawing_infos,
            tables=tables,
            drawings=drawings,
        )

        return sidecar_path

    # ─── 사이드카 파일 생성 ──────────────────────────────────────

    def _write_sidecar(
        self,
        sidecar_path: Path,
        source_file: Path,
        ocr_results: List[OcrResult],
        drawing_infos: List[DrawingInfo],
        tables: List[ExtractedTable],
        drawings: Set[str],
    ):
        """OCR 결과를 사이드카 .ocr.md 파일로 저장."""
        # YAML frontmatter — 구조화 도면번호 (확신도 포함)
        fm = {
            "source": source_file.name,
            "ocr_model": "glm-ocr",
            "processed_at": datetime.now().isoformat(),
            "pages_processed": len(ocr_results),
            "drawing_numbers": self._format_drawings_with_confidence(
                drawing_infos, drawings,
            ),
            "tables_found": len(tables),
            "table_types": sorted(set(t.table_type for t in tables if t.table_type != "unknown")),
        }

        lines = ["---"]
        lines.append(yaml.dump(fm, allow_unicode=True, default_flow_style=False).strip())
        lines.append("---")
        lines.append(f"\n# OCR 결과: {source_file.name}\n")

        # 도면번호 섹션
        if drawings:
            lines.append("## 추출된 도면번호")
            for d in sorted(drawings):
                lines.append(f"- {d}")
            lines.append("")

        # 테이블 섹션
        for idx, table in enumerate(tables, 1):
            ttype_label = {
                "spec_sheet": "시방서",
                "load_table": "하중표",
                "material_list": "자재목록",
                "schedule": "공정표",
                "rebar_schedule": "배근표",
            }.get(table.table_type, table.table_type)

            lines.append(f"## 테이블 {idx}: {ttype_label} ({table.table_type})")
            if table.page_number > 0:
                lines.append(f"> Page {table.page_number}")
            lines.append("")
            lines.append(table.markdown_table)
            lines.append("")

        # OCR 텍스트 섹션
        for r in ocr_results:
            if r.raw_text.strip():
                page_label = f"Page {r.page_number}" if r.page_number > 0 else "전체"
                lines.append(f"## OCR 텍스트 ({page_label})")
                # 텍스트 길이 제한 (사이드카 파일이 너무 커지지 않도록)
                text = r.raw_text.strip()
                if len(text) > 3000:
                    text = text[:3000] + "\n\n... (텍스트 잘림, 원본 참조)"
                lines.append(text)
                lines.append("")

        sidecar_path.write_text("\n".join(lines), encoding="utf-8")
        log.debug("사이드카 생성: %s", sidecar_path.name)

    # ─── 확신도 포맷팅 ──────────────────────────────────────────

    @staticmethod
    def _format_drawings_with_confidence(
        drawing_infos: List[DrawingInfo],
        all_drawings: Set[str],
    ) -> list:
        """DrawingInfo 리스트에서 구조화 도면번호 리스트 생성.

        Returns:
            [{"number": "EP-105", "confidence": 0.9, "source": "structured"}, ...]
        """
        seen: Dict[str, dict] = {}
        for info in drawing_infos:
            for num in info.drawing_numbers:
                num_upper = num.upper()
                conf = info.per_drawing_confidence.get(num, info.confidence)
                if num_upper not in seen or conf > seen[num_upper]["confidence"]:
                    seen[num_upper] = {
                        "number": num_upper,
                        "confidence": round(conf, 2),
                        "source": info.source or "unknown",
                    }
            for num in info.referenced_drawings:
                num_upper = num.upper()
                if num_upper not in seen:
                    seen[num_upper] = {
                        "number": num_upper,
                        "confidence": round(info.confidence * 0.8, 2),
                        "source": info.source or "unknown",
                    }
        # all_drawings에 있지만 info에 없는 경우 (방어)
        for num in all_drawings:
            if num not in seen:
                seen[num] = {"number": num, "confidence": 0.5, "source": "unknown"}
        return sorted(seen.values(), key=lambda x: x["number"])

    # ─── 유틸리티 ────────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(file_path: Path) -> Optional[Dict[str, Any]]:
        """마크다운 파일의 YAML frontmatter 파싱."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        if not text.startswith("---"):
            return None

        end = text.find("---", 3)
        if end == -1:
            return None

        try:
            return yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError:
            return None

    @staticmethod
    def _has_ocr_results(attach_dir: Path) -> bool:
        """디렉토리에 .ocr.md 파일이 있는지 확인."""
        return any(attach_dir.glob("*.ocr.md"))

    @staticmethod
    def _load_existing_drawings(attach_dir: Path) -> List[str]:
        """기존 사이드카 파일에서 도면번호 로드 (신/구 포맷 호환)."""
        drawings = set()
        for ocr_file in attach_dir.glob("*.ocr.md"):
            try:
                text = ocr_file.read_text(encoding="utf-8")
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end > 0:
                        fm = yaml.safe_load(text[3:end]) or {}
                        for d in fm.get("drawing_numbers", []):
                            if isinstance(d, dict):
                                drawings.add(str(d.get("number", "")))
                            else:
                                drawings.add(str(d))
            except Exception:
                pass
        return sorted(d for d in drawings if d)

    @staticmethod
    def _count_existing_tables(attach_dir: Path) -> int:
        """기존 사이드카 파일에서 테이블 수 합산."""
        total = 0
        for ocr_file in attach_dir.glob("*.ocr.md"):
            try:
                text = ocr_file.read_text(encoding="utf-8")
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end > 0:
                        fm = yaml.safe_load(text[3:end]) or {}
                        total += fm.get("tables_found", 0)
            except Exception:
                pass
        return total

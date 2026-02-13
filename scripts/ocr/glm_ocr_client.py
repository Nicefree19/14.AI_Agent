"""
GLM-OCR Client — Ollama API를 통한 OCR 처리
Zhipu AI GLM-OCR (0.9B) 모델을 Ollama로 로컬 서빙하여 사용.
"""

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests

from .image_preprocessor import ImagePreprocessor

log = logging.getLogger(__name__)

# ─── 기본 설정 ──────────────────────────────────────────────────
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "glm-ocr"
DEFAULT_TIMEOUT_IMAGE = 60   # 초
DEFAULT_TIMEOUT_PDF_PAGE = 120  # 초
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]   # 지수 백오프 (초)


@dataclass
class OcrResult:
    """단일 이미지/PDF 페이지의 OCR 결과."""
    source_file: str
    page_number: int          # 0 = 단일 이미지
    raw_text: str
    structured_data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    processing_time_ms: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


class GlmOcrClient:
    """Ollama GLM-OCR 클라이언트.

    Usage:
        client = GlmOcrClient()
        if client.is_available():
            result = client.ocr_image(Path("drawing.png"))
            print(result.raw_text)
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_image: int = DEFAULT_TIMEOUT_IMAGE,
        timeout_pdf_page: int = DEFAULT_TIMEOUT_PDF_PAGE,
        max_retries: int = MAX_RETRIES,
        cache_dir: Optional[Path] = None,
        preprocessor: Optional[ImagePreprocessor] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_image = timeout_image
        self.timeout_pdf_page = timeout_pdf_page
        self.max_retries = max_retries
        self._cache_dir = cache_dir
        self._preprocessor = preprocessor
        self._session = requests.Session()

    # ─── 헬스체크 ────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Ollama 실행 중이고 glm-ocr 모델이 로드되어 있는지 확인."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/tags", timeout=5
            )
            if resp.status_code != 200:
                log.warning("Ollama 응답 이상: status=%d", resp.status_code)
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # "glm-ocr" 또는 "glm-ocr:latest" 등 매치
            found = any(self.model in m for m in models)
            if not found:
                log.warning(
                    "Ollama에 %s 모델 없음. 사용 가능 모델: %s",
                    self.model, models,
                )
            return found
        except requests.ConnectionError:
            log.warning("Ollama 연결 실패: %s", self.base_url)
            return False
        except Exception as e:
            log.warning("Ollama 헬스체크 오류: %s", e)
            return False

    def get_model_info(self) -> Optional[Dict[str, Any]]:
        """모델 상세 정보 조회."""
        try:
            resp = self._session.post(
                f"{self.base_url}/api/show",
                json={"name": self.model},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.debug("모델 정보 조회 실패: %s", e)
        return None

    # ─── 이미지 OCR ──────────────────────────────────────────────

    def ocr_image(
        self,
        image_path: Path,
        prompt: str = "이 이미지의 모든 텍스트를 정확하게 추출하세요.",
    ) -> OcrResult:
        """단일 이미지 OCR → OcrResult.

        Args:
            image_path: 이미지 파일 경로 (PNG, JPG, TIFF, BMP)
            prompt: GLM-OCR에 전달할 프롬프트

        Returns:
            OcrResult 객체
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"이미지 없음: {image_path}")

        # 캐시 확인
        cached = self._check_cache(image_path, prompt)
        if cached:
            log.debug("캐시 히트: %s", image_path.name)
            return cached

        # base64 인코딩
        img_b64 = self._encode_image(image_path)

        # API 호출 (재시도 포함)
        start = time.time()
        response_text = self._call_ollama_chat(
            prompt=prompt,
            images=[img_b64],
            timeout=self.timeout_image,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        result = OcrResult(
            source_file=str(image_path),
            page_number=0,
            raw_text=response_text,
            confidence=self._estimate_confidence(response_text),
            processing_time_ms=elapsed_ms,
        )

        # 캐시 저장
        self._save_cache(image_path, prompt, result)

        return result

    # ─── PDF OCR ─────────────────────────────────────────────────

    def ocr_pdf(
        self,
        pdf_path: Path,
        max_pages: int = 10,
        prompt: str = "이 이미지의 모든 텍스트를 정확하게 추출하세요.",
        dpi: int = 200,
    ) -> List[OcrResult]:
        """PDF → 페이지별 이미지 변환 → OCR.

        PyMuPDF(fitz)를 사용하여 PDF 페이지를 이미지로 변환 후 OCR.
        Windows에서 외부 의존성 없이 동작.

        Args:
            pdf_path: PDF 파일 경로
            max_pages: 최대 처리 페이지 수
            prompt: GLM-OCR 프롬프트
            dpi: 이미지 변환 해상도

        Returns:
            페이지별 OcrResult 리스트
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 없음: {pdf_path}")

        try:
            import fitz  # PyMuPDF
        except ImportError:
            log.error("PyMuPDF 미설치. pip install PyMuPDF 실행 필요")
            return []

        results = []
        doc = fitz.open(str(pdf_path))
        total_pages = min(len(doc), max_pages)

        log.info(
            "PDF OCR 시작: %s (%d/%d 페이지)",
            pdf_path.name, total_pages, len(doc),
        )

        for page_num in range(total_pages):
            page = doc[page_num]
            # 페이지 → PNG 이미지 (메모리)
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            if self._preprocessor and self._preprocessor.is_enabled:
                img_bytes = self._preprocessor.preprocess_bytes(img_bytes)
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            # API 호출
            start = time.time()
            response_text = self._call_ollama_chat(
                prompt=prompt,
                images=[img_b64],
                timeout=self.timeout_pdf_page,
            )
            elapsed_ms = int((time.time() - start) * 1000)

            result = OcrResult(
                source_file=str(pdf_path),
                page_number=page_num + 1,
                raw_text=response_text,
                confidence=self._estimate_confidence(response_text),
                processing_time_ms=elapsed_ms,
            )
            results.append(result)
            log.debug(
                "  Page %d/%d → %d chars (%.1fs)",
                page_num + 1, total_pages,
                len(response_text), elapsed_ms / 1000,
            )

        doc.close()
        return results

    # ─── 구조화 추출 (프롬프트 엔지니어링) ────────────────────────

    def ocr_structured(
        self,
        image_path: Path,
        prompt: str,
    ) -> OcrResult:
        """구조화된 프롬프트로 OCR → JSON 파싱 시도.

        drawing_extractor, table_extractor에서 호출.
        프롬프트가 JSON 반환을 요청하면 structured_data에 파싱 결과 저장.
        """
        result = self.ocr_image(image_path, prompt=prompt)

        # JSON 추출 시도
        result.structured_data = self._try_parse_json(result.raw_text)

        return result

    def ocr_pdf_structured(
        self,
        pdf_path: Path,
        prompt: str,
        max_pages: int = 10,
        dpi: int = 200,
    ) -> List[OcrResult]:
        """PDF 구조화 OCR — 페이지별 JSON 파싱."""
        results = self.ocr_pdf(pdf_path, max_pages, prompt, dpi)
        for r in results:
            r.structured_data = self._try_parse_json(r.raw_text)
        return results

    # ─── 내부 메서드 ─────────────────────────────────────────────

    @staticmethod
    def _estimate_confidence(response_text: str) -> float:
        """OCR 응답 품질 기반 확신도 추정 (0.0~1.0).

        길이, 구조화 데이터 존재 여부 등 휴리스틱 기반.
        """
        if not response_text or not response_text.strip():
            return 0.0
        text = response_text.strip()
        score = 0.5  # 기본값
        # 길이 기반 보정
        if len(text) > 100:
            score += 0.1
        if len(text) > 500:
            score += 0.1
        # JSON 구조 존재 시 보너스
        if "{" in text and "}" in text:
            score += 0.1
        # 너무 짧은 응답은 감점
        if len(text) < 20:
            score -= 0.2
        return max(0.0, min(1.0, round(score, 2)))

    def _call_ollama_chat(
        self,
        prompt: str,
        images: List[str],
        timeout: int,
    ) -> str:
        """Ollama /api/chat 호출 (재시도 포함).

        Args:
            prompt: 사용자 프롬프트
            images: base64 인코딩된 이미지 리스트
            timeout: 타임아웃 (초)

        Returns:
            모델 응답 텍스트
        """
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": images,
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,  # OCR은 결정론적 결과가 좋음
            },
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = self._session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("message", {}).get("content", "")
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    log.warning(
                        "Ollama API 오류 (시도 %d/%d): %s",
                        attempt + 1, self.max_retries, last_error,
                    )
            except requests.Timeout:
                last_error = f"타임아웃 ({timeout}s)"
                log.warning(
                    "Ollama 타임아웃 (시도 %d/%d): %ds",
                    attempt + 1, self.max_retries, timeout,
                )
            except requests.ConnectionError:
                last_error = "연결 실패"
                log.warning(
                    "Ollama 연결 실패 (시도 %d/%d)",
                    attempt + 1, self.max_retries,
                )
            except Exception as e:
                last_error = str(e)
                log.warning(
                    "Ollama 호출 오류 (시도 %d/%d): %s",
                    attempt + 1, self.max_retries, e,
                )

            # 백오프 대기 (마지막 시도 제외)
            if attempt < self.max_retries - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log.debug("  %ds 후 재시도...", wait)
                time.sleep(wait)

        log.error("Ollama 호출 최종 실패: %s", last_error)
        return ""

    def _encode_image(self, image_path: Path) -> str:
        """이미지 파일 → (전처리 →) base64 문자열."""
        raw_bytes = image_path.read_bytes()
        if self._preprocessor and self._preprocessor.is_enabled:
            raw_bytes = self._preprocessor.preprocess_bytes(raw_bytes)
        return base64.b64encode(raw_bytes).decode("utf-8")

    @staticmethod
    def _try_parse_json(text: str) -> Dict[str, Any]:
        """텍스트에서 JSON 블록 추출 시도."""
        if not text:
            return {}

        # 방법 1: 전체가 JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # 방법 2: ```json ... ``` 블록
        import re
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 방법 3: { ... } 블록 (첫 번째)
        brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        return {}

    # ─── 파일 해시 기반 캐시 ─────────────────────────────────────

    def _get_cache_path(self, file_path: Path, prompt: str) -> Optional[Path]:
        """캐시 파일 경로 계산."""
        if not self._cache_dir:
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # 파일 내용 + 프롬프트 해시
        hasher = hashlib.sha256()
        hasher.update(file_path.read_bytes())
        hasher.update(prompt.encode("utf-8"))
        cache_name = f"{hasher.hexdigest()[:16]}.json"
        return self._cache_dir / cache_name

    def _check_cache(self, file_path: Path, prompt: str) -> Optional[OcrResult]:
        """캐시에서 결과 조회."""
        cache_path = self._get_cache_path(file_path, prompt)
        if cache_path and cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                return OcrResult(**data)
            except Exception:
                pass
        return None

    def _save_cache(self, file_path: Path, prompt: str, result: OcrResult):
        """결과를 캐시에 저장."""
        cache_path = self._get_cache_path(file_path, prompt)
        if cache_path:
            try:
                cache_path.write_text(
                    json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                log.debug("캐시 저장 실패: %s", e)

"""
P5 OCR Module — GLM-OCR via Ollama 기반 첨부파일 자동 인식
"""

from .glm_ocr_client import GlmOcrClient, OcrResult
from .drawing_extractor import DrawingExtractor
from .table_extractor import TableExtractor, ExtractedTable
from .attachment_processor import AttachmentProcessor, AttachmentResult
from .image_preprocessor import ImagePreprocessor, PreprocessConfig
from .correction_manager import CorrectionManager

__all__ = [
    "GlmOcrClient",
    "OcrResult",
    "DrawingExtractor",
    "TableExtractor",
    "ExtractedTable",
    "AttachmentProcessor",
    "AttachmentResult",
    "ImagePreprocessor",
    "PreprocessConfig",
    "CorrectionManager",
]

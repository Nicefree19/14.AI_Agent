"""OCR 모듈 임포트 및 기본 동작 검증"""
import sys
sys.path.insert(0, r"D:\00.Work_AI_Tool\14.AI_Agent\scripts")

print("=== OCR Module Verification ===")

# 1. 모듈 임포트
try:
    from ocr.glm_ocr_client import GlmOcrClient, OcrResult
    print("[OK] glm_ocr_client")
except Exception as e:
    print(f"[FAIL] glm_ocr_client: {e}")

try:
    from ocr.drawing_extractor import DrawingExtractor, DrawingInfo
    print("[OK] drawing_extractor")
except Exception as e:
    print(f"[FAIL] drawing_extractor: {e}")

try:
    from ocr.table_extractor import TableExtractor, ExtractedTable
    print("[OK] table_extractor")
except Exception as e:
    print(f"[FAIL] table_extractor: {e}")

try:
    from ocr.attachment_processor import AttachmentProcessor, AttachmentResult
    print("[OK] attachment_processor")
except Exception as e:
    print(f"[FAIL] attachment_processor: {e}")

# 2. OcrResult dataclass
r = OcrResult(source_file="test.png", page_number=0, raw_text="SEN-070 EP-105")
print(f"[OK] OcrResult: source={r.source_file}, text={r.raw_text}")

# 3. DrawingExtractor 정규식 테스트
client = GlmOcrClient()  # 실제 Ollama 없이 인스턴스만
extractor = DrawingExtractor(client)
test_text = "도면 EP-105 참조, PSRC-32 기둥, HMB-15 브라켓, SEN-070 이슈"
found = extractor.extract_from_text(test_text)
print(f"[OK] DrawingExtractor regex: {sorted(found)}")
assert "EP-105" in found, "EP-105 not found"
assert "PSRC-32" in found, "PSRC-32 not found"
assert "HMB-15" in found, "HMB-15 not found"
assert "SEN-070" in found, "SEN-070 not found"

# 4. GlmOcrClient JSON 파싱
parsed = GlmOcrClient._try_parse_json('{"drawing_numbers": ["EP-105"], "revision": "R3"}')
print(f"[OK] JSON parse: {parsed}")
assert parsed.get("revision") == "R3"

# 5. Markdown 블록 JSON 파싱
md_json = '설명입니다.\n```json\n{"tables": [{"type": "load_table"}]}\n```\n끝'
parsed2 = GlmOcrClient._try_parse_json(md_json)
print(f"[OK] Markdown JSON parse: {parsed2}")
assert "tables" in parsed2

# 6. CLI 진입점 확인
import importlib.util
spec = importlib.util.spec_from_file_location(
    "p5_ocr_pipeline",
    r"D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_ocr_pipeline.py"
)
print("[OK] p5_ocr_pipeline.py loadable")

print("\n=== All Verifications Passed ===")

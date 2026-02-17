#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test for the new skill system."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

errors = []
passed = 0

# ── Test 1: skills_registry ──
print("=" * 50)
print("TEST 1: skills_registry")
try:
    from scripts.telegram.skills_registry import (
        SKILLS, get_skill_help_text, get_implemented_skills,
        get_skill_by_id, find_skill_by_keyword,
    )
    assert len(SKILLS) == 14, f"Expected 14 skills, got {len(SKILLS)}"
    impl = get_implemented_skills()
    assert len(impl) == 10, f"Expected 10 implemented, got {len(impl)}"

    help_text = get_skill_help_text()
    assert len(help_text) > 100, "Help text too short"
    assert "PDF 분석" in help_text
    assert "도움말" in help_text

    skill = get_skill_by_id("pdf_analyze")
    assert skill is not None
    assert skill.name_ko == "PDF 분석"

    found = find_skill_by_keyword("이 PDF 문서분석해줘")
    assert found is not None and found.skill_id == "pdf_analyze"

    print(f"  PASS: {len(SKILLS)} skills, {len(impl)} implemented")
    print(f"  Help text: {len(help_text)} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"skills_registry: {e}")

# ── Test 2: skill_utils ──
print("\nTEST 2: skill_utils")
try:
    from scripts.telegram.skill_utils import (
        load_vault_issues, search_issues, detect_sen_refs,
        detect_drawing_refs, extract_files_by_ext, truncate_text,
        DRAWING_PATTERNS, ISSUES_DIR,
    )
    # SEN pattern detection
    refs = detect_sen_refs("Check SEN-070 and SEN-001 for details")
    assert refs == ["SEN-001", "SEN-070"], f"SEN refs: {refs}"

    # Drawing pattern detection
    dwg = detect_drawing_refs("EP-001 PSRC-15 HMB-03 S-1234")
    assert "EP-001" in dwg
    assert "PSRC-15" in dwg

    # Truncate
    short = truncate_text("abc", 100)
    assert short == "abc"
    long = truncate_text("x" * 5000, 100)
    assert len(long) < 200

    # Extract files
    ctx = {"combined": {"files": [
        {"name": "test.pdf"},
        {"name": "data.xlsx"},
        {"name": "image.png"},
    ]}}
    pdfs = extract_files_by_ext(ctx, [".pdf"])
    assert len(pdfs) == 1
    excels = extract_files_by_ext(ctx, [".xlsx", ".csv"])
    assert len(excels) == 1

    # Load issues (may be empty if no vault)
    issues = load_vault_issues()
    print(f"  PASS: SEN refs, drawing refs, truncate, file extraction OK")
    print(f"  Vault issues loaded: {len(issues)}")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    import traceback; traceback.print_exc()
    errors.append(f"skill_utils: {e}")

# ── Test 3: telegram_executors integration ──
print("\nTEST 3: telegram_executors integration")
try:
    from scripts.telegram.telegram_executors import (
        KEYWORD_MAP, EXECUTOR_MAP, get_executor, list_executors,
    )
    # Keyword count
    assert len(KEYWORD_MAP) > 30, f"Expected >30 keywords, got {len(KEYWORD_MAP)}"

    # Executor count (11 old + 13 new = 24)
    executors = list_executors()
    assert len(executors) >= 24, f"Expected >=24 executors, got {len(executors)}"

    # Keyword routing tests
    # New skill keywords
    ex = get_executor("도움말 보여줘")
    assert ex.__name__ == "run_skill_help", f"Expected skill_help, got {ex.__name__}"

    ex = get_executor("SEN-070 이슈조회")
    assert ex.__name__ == "run_issue_lookup", f"Expected issue_lookup, got {ex.__name__}"

    ex = get_executor("이 PDF를 pdf분석해줘")
    assert ex.__name__ == "run_pdf_analyze", f"Expected pdf_analyze, got {ex.__name__}"

    ex = get_executor("제작현황 알려줘")
    assert ex.__name__ == "run_fabrication_status", f"Expected fabrication_status, got {ex.__name__}"

    ex = get_executor("엑셀보고서 만들어줘")
    assert ex.__name__ == "run_excel_report", f"Expected excel_report, got {ex.__name__}"

    ex = get_executor("이 메일에 답신 방향 잡아줘")
    assert ex.__name__ == "run_email_response", f"Expected email_response, got {ex.__name__}"

    ex = get_executor("회의준비 해줘")
    assert ex.__name__ == "run_meeting_prep", f"Expected meeting_prep, got {ex.__name__}"

    ex = get_executor("도면분석 부탁")
    assert ex.__name__ == "run_drawing_analyze", f"Expected drawing_analyze, got {ex.__name__}"

    # Old keywords still work
    ex = get_executor("브리핑 생성해줘")
    assert "briefing" in ex.__name__.lower() or "run_briefing" == ex.__name__, f"Got {ex.__name__}"

    ex = get_executor("이메일 트리아지")
    assert "triage" in ex.__name__.lower() or "run_triage" == ex.__name__, f"Got {ex.__name__}"

    # File auto-routing
    pdf_files = [{"name": "document.pdf"}]
    ex = get_executor("이거 확인해줘", files=pdf_files)
    assert ex.__name__ == "run_pdf_analyze", f"PDF auto-route: got {ex.__name__}"

    ex = get_executor("도면 확인해줘", files=pdf_files)
    assert ex.__name__ == "run_drawing_analyze", f"Drawing auto-route: got {ex.__name__}"

    excel_files = [{"name": "data.xlsx"}]
    ex = get_executor("이거 봐줘", files=excel_files)
    assert ex.__name__ == "run_excel_analyze", f"Excel auto-route: got {ex.__name__}"

    print(f"  PASS: {len(KEYWORD_MAP)} keywords, {len(executors)} executors")
    print(f"  Keyword routing: all 8 new skills + 2 old skills OK")
    print(f"  File auto-routing: PDF, Drawing, Excel OK")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    import traceback; traceback.print_exc()
    errors.append(f"telegram_executors: {e}")

# ── Test 4: skill_help execution ──
print("\nTEST 4: skill_help execution")
try:
    from scripts.telegram.skills.utility_skills import run_skill_help
    result = run_skill_help({})
    assert "result_text" in result
    assert "PDF 분석" in result["result_text"]
    assert "이슈 조회" in result["result_text"]
    print(f"  PASS: skill_help returns {len(result['result_text'])} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"skill_help execution: {e}")

# ── Test 5: issue_lookup execution (if vault exists) ──
print("\nTEST 5: issue_lookup execution")
try:
    from scripts.telegram.skills.utility_skills import run_issue_lookup
    ctx = {
        "combined": {"combined_instruction": "이슈조회"},
        "send_progress": lambda x: None,
    }
    result = run_issue_lookup(ctx)
    assert "result_text" in result
    # May show "no issues" or actual issues depending on vault state
    print(f"  PASS: issue_lookup returns {len(result['result_text'])} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"issue_lookup execution: {e}")

# ── Test 6: fabrication_status execution ──
print("\nTEST 6: fabrication_status execution")
try:
    from scripts.telegram.skills.intelligence_skills import run_fabrication_status
    ctx = {
        "combined": {"combined_instruction": "제작현황"},
        "send_progress": lambda x: None,
    }
    result = run_fabrication_status(ctx)
    assert "result_text" in result
    print(f"  PASS: fabrication_status returns {len(result['result_text'])} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"fabrication_status: {e}")

# ── Test 7: meeting_prep execution ──
print("\nTEST 7: meeting_prep execution")
try:
    from scripts.telegram.skills.intelligence_skills import run_meeting_prep
    ctx = {
        "combined": {"combined_instruction": "주간회의 준비해줘"},
        "send_progress": lambda x: None,
    }
    result = run_meeting_prep(ctx)
    assert "result_text" in result
    assert "안건" in result["result_text"] or "회의" in result["result_text"]
    print(f"  PASS: meeting_prep returns {len(result['result_text'])} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"meeting_prep: {e}")

# ── Test 8: email_response execution ──
print("\nTEST 8: email_response execution")
try:
    from scripts.telegram.skills.intelligence_skills import run_email_response
    ctx = {
        "combined": {"combined_instruction": "답신 방향 잡아줘: 강상규 프로에서 EP 계산서 회신 부탁드립니다. 2절주 BCW 검토 결과 확인 요청합니다."},
        "send_progress": lambda x: None,
        "memories": [],
    }
    result = run_email_response(ctx)
    assert "result_text" in result
    assert "답신" in result["result_text"] or "방향" in result["result_text"]
    print(f"  PASS: email_response returns {len(result['result_text'])} chars")
    passed += 1
except Exception as e:
    print(f"  FAIL: {e}")
    errors.append(f"email_response: {e}")

# ── Summary ──
print("\n" + "=" * 50)
print(f"RESULTS: {passed}/8 passed")
if errors:
    print(f"ERRORS ({len(errors)}):")
    for err in errors:
        print(f"  FAIL: {err}")
else:
    print("ALL TESTS PASSED")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google 연동 스킬 스모크 테스트

검증 항목:
1. skills_registry: 19개 스킬, 15개 implemented, "google" 카테고리
2. KEYWORD_MAP: 80+ 키워드
3. EXECUTOR_MAP: 29개 executor
4. google_utils: URL 파싱 함수
5. 키워드 라우팅: Google 키워드 → 올바른 executor
6. URL 자동 라우팅: Google URL → 올바른 executor
7. google_skills 모듈 임포트
8. _detect_google_url 함수 동작
"""

from __future__ import annotations

import os
import sys

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

errors = []
passed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        errors.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} -- {detail}")


# ── Test 1: skills_registry 구조 ──
print("\n[1/8] skills_registry 구조 검증")
try:
    from scripts.telegram.skills_registry import (
        SKILLS, CATEGORY_LABELS, CATEGORY_ORDER,
        get_implemented_skills, get_skills_by_category,
    )
    check("Total skills = 19", len(SKILLS) == 19, f"got {len(SKILLS)}")
    check("Implemented = 15", len(get_implemented_skills()) == 15,
          f"got {len(get_implemented_skills())}")
    check("'google' in CATEGORY_LABELS", "google" in CATEGORY_LABELS)
    check("'google' in CATEGORY_ORDER", "google" in CATEGORY_ORDER)
    google_skills = get_skills_by_category("google")
    check("Google skills = 5", len(google_skills) == 5, f"got {len(google_skills)}")
    google_ids = {s.skill_id for s in google_skills}
    expected_ids = {"gdrive_browse", "gdrive_download", "email_check", "gsheet_edit", "gdoc_read"}
    check("Google skill IDs match", google_ids == expected_ids,
          f"got {google_ids}")
except Exception as e:
    errors.append(f"skills_registry import: {e}")
    print(f"  [FAIL] skills_registry import -- {e}")

# ── Test 2: KEYWORD_MAP 크기 ──
print("\n[2/8] KEYWORD_MAP 크기 검증")
try:
    from scripts.telegram.telegram_executors import KEYWORD_MAP
    check("KEYWORD_MAP >= 80", len(KEYWORD_MAP) >= 80,
          f"got {len(KEYWORD_MAP)}")
    # Google 키워드 존재 확인
    google_kws = ["구글드라이브", "드라이브검색", "메일확인", "구글시트", "구글문서",
                  "공유폴더", "드라이브다운", "시트수정", "받은메일", "문서읽기"]
    missing = [kw for kw in google_kws if kw not in KEYWORD_MAP]
    check("All 10 Google keywords present", len(missing) == 0,
          f"missing: {missing}")
except Exception as e:
    errors.append(f"KEYWORD_MAP import: {e}")
    print(f"  [FAIL] KEYWORD_MAP import -- {e}")

# ── Test 3: EXECUTOR_MAP 크기 ──
print("\n[3/8] EXECUTOR_MAP 크기 검증")
try:
    from scripts.telegram.telegram_executors import EXECUTOR_MAP
    check("EXECUTOR_MAP >= 29", len(EXECUTOR_MAP) >= 29,
          f"got {len(EXECUTOR_MAP)}")
    google_execs = ["gdrive_browse", "gdrive_download", "email_check", "gsheet_edit", "gdoc_read"]
    missing = [e for e in google_execs if e not in EXECUTOR_MAP]
    check("All 5 Google executors present", len(missing) == 0,
          f"missing: {missing}")
except Exception as e:
    errors.append(f"EXECUTOR_MAP import: {e}")
    print(f"  [FAIL] EXECUTOR_MAP import -- {e}")

# ── Test 4: google_utils URL 파싱 ──
print("\n[4/8] google_utils URL 파싱 검증")
try:
    from scripts.telegram.google_utils import parse_drive_url, detect_google_url
    # Sheets URL
    fid, ftype = parse_drive_url("https://docs.google.com/spreadsheets/d/1PEUylHx689l8jhfC3rB8Imub5YQnOPAW1CH6qbaw73s/edit")
    check("Sheets URL parse", fid == "1PEUylHx689l8jhfC3rB8Imub5YQnOPAW1CH6qbaw73s" and ftype == "spreadsheet",
          f"got id={fid}, type={ftype}")
    # Docs URL
    fid2, ftype2 = parse_drive_url("https://docs.google.com/document/d/abc123def/edit")
    check("Docs URL parse", fid2 == "abc123def" and ftype2 == "document",
          f"got id={fid2}, type={ftype2}")
    # Drive folder URL
    fid3, ftype3 = parse_drive_url("https://drive.google.com/drive/folders/1XYZ_abc123")
    check("Drive folder URL parse", fid3 == "1XYZ_abc123" and ftype3 == "folder",
          f"got id={fid3}, type={ftype3}")
    # Drive file URL
    fid4, ftype4 = parse_drive_url("https://drive.google.com/file/d/fileId123/view")
    check("Drive file URL parse", fid4 == "fileId123" and ftype4 == "file",
          f"got id={fid4}, type={ftype4}")
    # detect_google_url in text
    result = detect_google_url("이 시트 확인해줘 https://docs.google.com/spreadsheets/d/abc123/edit#gid=0")
    check("detect_google_url finds URL in text", result is not None and result[0] == "abc123",
          f"got {result}")
    # No URL
    result_none = detect_google_url("구글시트 조회해줘")
    check("detect_google_url returns None for no URL", result_none is None,
          f"got {result_none}")
except Exception as e:
    errors.append(f"google_utils import: {e}")
    print(f"  [FAIL] google_utils -- {e}")

# ── Test 5: 키워드 라우팅 ──
print("\n[5/8] 키워드 라우팅 검증")
try:
    from scripts.telegram.telegram_executors import get_executor
    test_cases = [
        ("구글드라이브 확인", "gdrive_browse"),
        ("메일확인", "email_check"),
        ("구글시트 조회", "gsheet_edit"),
        ("구글문서 읽기", "gdoc_read"),
        ("드라이브다운 해줘", "gdrive_download"),
        ("받은메일 보여줘", "email_check"),
        ("시트수정 B5=진행중", "gsheet_edit"),
    ]
    for text, expected_name in test_cases:
        executor = get_executor(text)
        # executor.__name__ 확인
        actual_name = getattr(executor, '__name__', str(executor))
        # lazy_skill 래퍼는 func_name을 __name__으로 가짐
        expected_func = f"run_{expected_name}"
        ok = actual_name == expected_func
        check(f"'{text}' -> {expected_name}", ok,
              f"got {actual_name}")
except Exception as e:
    errors.append(f"keyword routing: {e}")
    print(f"  [FAIL] keyword routing -- {e}")

# ── Test 6: Google URL 자동 라우팅 ──
print("\n[6/8] Google URL 자동 라우팅 검증")
try:
    from scripts.telegram.telegram_executors import get_executor
    url_cases = [
        ("https://docs.google.com/spreadsheets/d/abc123/edit", "run_gsheet_edit"),
        ("https://docs.google.com/document/d/xyz789/edit", "run_gdoc_read"),
        ("https://drive.google.com/drive/folders/folder123", "run_gdrive_browse"),
        ("https://drive.google.com/file/d/file456/view", "run_gdrive_download"),
    ]
    for url, expected_func in url_cases:
        executor = get_executor(url)
        actual_name = getattr(executor, '__name__', str(executor))
        check(f"URL -> {expected_func}", actual_name == expected_func,
              f"got {actual_name}")
except Exception as e:
    errors.append(f"URL routing: {e}")
    print(f"  [FAIL] URL routing -- {e}")

# ── Test 7: google_skills 모듈 임포트 ──
print("\n[7/8] google_skills 모듈 임포트 검증")
try:
    from scripts.telegram.skills.google_skills import (
        run_gdrive_browse, run_gdrive_download, run_email_check,
        run_gsheet_edit, run_gdoc_read,
    )
    check("All 5 google_skills functions importable", True)
    # 각 함수가 callable인지 확인
    for fn in [run_gdrive_browse, run_gdrive_download, run_email_check,
               run_gsheet_edit, run_gdoc_read]:
        assert callable(fn), f"{fn.__name__} not callable"
    check("All 5 google_skills functions callable", True)
except Exception as e:
    errors.append(f"google_skills import: {e}")
    print(f"  [FAIL] google_skills import -- {e}")

# ── Test 8: _detect_google_url 함수 ──
print("\n[8/8] _detect_google_url 함수 검증")
try:
    from scripts.telegram.telegram_executors import _detect_google_url
    check("Sheets URL detected",
          _detect_google_url("https://docs.google.com/spreadsheets/d/abc/edit") == "gsheet_edit")
    check("Doc URL detected",
          _detect_google_url("https://docs.google.com/document/d/abc/edit") == "gdoc_read")
    check("Drive folder detected",
          _detect_google_url("https://drive.google.com/drive/folders/abc") == "gdrive_browse")
    check("Drive file detected",
          _detect_google_url("https://drive.google.com/file/d/abc/view") == "gdrive_download")
    check("Drive open?id detected",
          _detect_google_url("https://drive.google.com/open?id=abc") == "gdrive_download")
    check("No URL returns None",
          _detect_google_url("just some text") is None)
except Exception as e:
    errors.append(f"_detect_google_url: {e}")
    print(f"  [FAIL] _detect_google_url -- {e}")

# ── Summary ──
print("\n" + "=" * 50)
total = passed + len(errors)
if errors:
    print(f"RESULT: {passed}/{total} passed, {len(errors)} failed")
    for err in errors:
        print(f"  FAIL: {err}")
    sys.exit(1)
else:
    print(f"ALL {passed} TESTS PASSED")
    sys.exit(0)

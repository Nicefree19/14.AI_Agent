#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
이메일 강화 스킬 스모크 테스트

검증 항목:
1. skills_registry: 22개 스킬, 18개 implemented, "email" 카테고리
2. KEYWORD_MAP: 97+ 키워드 (기존 80 + 신규 19)
3. EXECUTOR_MAP: 32개 executor (기존 29 + 신규 3)
4. 키워드 라우팅: email 키워드 -> 올바른 executor
5. 기존 키워드 리매핑: "답장" -> email_reply, "메일답변" -> email_response
6. email_skills 모듈 임포트
7. OutlookAdapter 새 메서드 존재
8. 드래프트 관리 함수 동작
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
    check("Total skills = 22", len(SKILLS) == 22, f"got {len(SKILLS)}")
    check("Implemented = 18", len(get_implemented_skills()) == 18,
          f"got {len(get_implemented_skills())}")
    check("'email' in CATEGORY_LABELS", "email" in CATEGORY_LABELS)
    check("'email' in CATEGORY_ORDER", "email" in CATEGORY_ORDER)
    email_skills = get_skills_by_category("email")
    check("Email skills = 3", len(email_skills) == 3, f"got {len(email_skills)}")
    email_ids = {s.skill_id for s in email_skills}
    expected_ids = {"email_attachment", "email_send", "email_reply"}
    check("Email skill IDs match", email_ids == expected_ids,
          f"got {email_ids}")
    # Google 스킬도 여전히 존재
    google_skills = get_skills_by_category("google")
    check("Google skills still = 5", len(google_skills) == 5, f"got {len(google_skills)}")
except Exception as e:
    errors.append(f"skills_registry import: {e}")
    print(f"  [FAIL] skills_registry import -- {e}")

# ── Test 2: KEYWORD_MAP 크기 ──
print("\n[2/8] KEYWORD_MAP 크기 검증")
try:
    from scripts.telegram.telegram_executors import KEYWORD_MAP
    check("KEYWORD_MAP >= 97", len(KEYWORD_MAP) >= 97,
          f"got {len(KEYWORD_MAP)}")
    # 이메일 강화 키워드 존재 확인
    email_kws = [
        "첨부파일분석", "첨부확인", "첨부다운", "메일첨부분석",
        "메일발송", "메일보내", "메일전송", "메일작성",
        "메일회신", "메일답장", "전체회신",
    ]
    missing = [kw for kw in email_kws if kw not in KEYWORD_MAP]
    check("All 11 email keywords present", len(missing) == 0,
          f"missing: {missing}")
except Exception as e:
    errors.append(f"KEYWORD_MAP import: {e}")
    print(f"  [FAIL] KEYWORD_MAP import -- {e}")

# ── Test 3: EXECUTOR_MAP 크기 ──
print("\n[3/8] EXECUTOR_MAP 크기 검증")
try:
    from scripts.telegram.telegram_executors import EXECUTOR_MAP
    check("EXECUTOR_MAP >= 32", len(EXECUTOR_MAP) >= 32,
          f"got {len(EXECUTOR_MAP)}")
    email_execs = ["email_attachment", "email_send", "email_reply"]
    missing = [e for e in email_execs if e not in EXECUTOR_MAP]
    check("All 3 email executors present", len(missing) == 0,
          f"missing: {missing}")
    # 기존 Google executor도 존재
    google_execs = ["gdrive_browse", "gdrive_download", "email_check", "gsheet_edit", "gdoc_read"]
    missing_g = [e for e in google_execs if e not in EXECUTOR_MAP]
    check("All 5 Google executors still present", len(missing_g) == 0,
          f"missing: {missing_g}")
except Exception as e:
    errors.append(f"EXECUTOR_MAP import: {e}")
    print(f"  [FAIL] EXECUTOR_MAP import -- {e}")

# ── Test 4: 키워드 라우팅 ──
print("\n[4/8] 이메일 키워드 라우팅 검증")
try:
    from scripts.telegram.telegram_executors import get_executor
    test_cases = [
        ("첨부파일분석 해줘", "email_attachment"),
        ("메일첨부분석", "email_attachment"),
        ("메일발송 to:test@test.com", "email_send"),
        ("메일보내 김과장한테", "email_send"),
        ("메일회신 확인했습니다", "email_reply"),
        ("전체회신 일정조정", "email_reply"),
    ]
    for text, expected_name in test_cases:
        executor = get_executor(text)
        actual_name = getattr(executor, '__name__', str(executor))
        expected_func = f"run_{expected_name}"
        ok = actual_name == expected_func
        check(f"'{text}' -> {expected_name}", ok,
              f"got {actual_name}")
except Exception as e:
    errors.append(f"keyword routing: {e}")
    print(f"  [FAIL] keyword routing -- {e}")

# ── Test 5: 기존 키워드 리매핑 검증 ──
print("\n[5/8] 키워드 리매핑 검증 (답장->reply, 답변방향->response)")
try:
    from scripts.telegram.telegram_executors import get_executor, KEYWORD_MAP
    # 리매핑된 키워드
    check("'답장' -> email_reply", KEYWORD_MAP.get("답장") == "email_reply",
          f"got {KEYWORD_MAP.get('답장')}")
    check("'회신' -> email_reply", KEYWORD_MAP.get("회신") == "email_reply",
          f"got {KEYWORD_MAP.get('회신')}")
    check("'답신' -> email_reply", KEYWORD_MAP.get("답신") == "email_reply",
          f"got {KEYWORD_MAP.get('답신')}")
    # 유지된 키워드
    check("'메일답변' -> email_response", KEYWORD_MAP.get("메일답변") == "email_response",
          f"got {KEYWORD_MAP.get('메일답변')}")
    check("'답변방향' -> email_response", KEYWORD_MAP.get("답변방향") == "email_response",
          f"got {KEYWORD_MAP.get('답변방향')}")
    # executor 동작 확인
    executor_reply = get_executor("답장해줘")
    check("'답장해줘' routes to run_email_reply",
          getattr(executor_reply, '__name__', '') == "run_email_reply",
          f"got {getattr(executor_reply, '__name__', str(executor_reply))}")
    executor_response = get_executor("답변방향 잡아줘")
    check("'답변방향 잡아줘' routes to run_email_response",
          getattr(executor_response, '__name__', '') == "run_email_response",
          f"got {getattr(executor_response, '__name__', str(executor_response))}")
except Exception as e:
    errors.append(f"keyword remapping: {e}")
    print(f"  [FAIL] keyword remapping -- {e}")

# ── Test 6: email_skills 모듈 임포트 ──
print("\n[6/8] email_skills 모듈 임포트 검증")
try:
    from scripts.telegram.skills.email_skills import (
        run_email_attachment, run_email_send, run_email_reply,
    )
    check("All 3 email_skills functions importable", True)
    for fn in [run_email_attachment, run_email_send, run_email_reply]:
        assert callable(fn), f"{fn.__name__} not callable"
    check("All 3 email_skills functions callable", True)
    # 헬퍼 함수도 임포트 가능
    from scripts.telegram.skills.email_skills import (
        _save_draft, _load_latest_draft, _detect_confirmation,
        _parse_email_compose, _parse_reply_content, _resolve_recipient,
    )
    check("All helper functions importable", True)
except Exception as e:
    errors.append(f"email_skills import: {e}")
    print(f"  [FAIL] email_skills import -- {e}")

# ── Test 7: OutlookAdapter 새 메서드 존재 ──
print("\n[7/8] OutlookAdapter 새 메서드 검증")
try:
    from scripts.adapters.outlook_adapter import OutlookAdapter
    adapter_cls = OutlookAdapter
    check("search_emails method exists", hasattr(adapter_cls, 'search_emails'))
    check("send_email method exists", hasattr(adapter_cls, 'send_email'))
    check("reply_email method exists", hasattr(adapter_cls, 'reply_email'))
    # 기존 메서드도 여전히 존재
    check("fetch method still exists", hasattr(adapter_cls, 'fetch'))
    check("get_attachments method still exists", hasattr(adapter_cls, 'get_attachments'))
    check("mark_as_read method still exists", hasattr(adapter_cls, 'mark_as_read'))
except Exception as e:
    errors.append(f"OutlookAdapter methods: {e}")
    print(f"  [FAIL] OutlookAdapter methods -- {e}")

# ── Test 8: 드래프트 + 파싱 함수 동작 ──
print("\n[8/8] 드래프트 관리 + 파싱 함수 검증")
try:
    from scripts.telegram.skills.email_skills import (
        _save_draft, _load_latest_draft, _clear_old_drafts,
        _detect_confirmation, _parse_email_compose, _parse_reply_content,
    )

    # 확인 감지
    check("'보내줘' is confirmation", _detect_confirmation("보내줘"))
    check("'ok' is confirmation", _detect_confirmation("ok"))
    check("'발송' is confirmation", _detect_confirmation("발송"))
    check("Long text is NOT confirmation",
          not _detect_confirmation("이 메일 첨부파일을 분석해주세요"))

    # 이메일 작성 파싱
    parsed = _parse_email_compose("메일보내 to:test@example.com 제목:테스트 내용:안녕하세요")
    check("parse_email_compose to", parsed["to"] == "test@example.com",
          f"got {parsed['to']}")
    check("parse_email_compose subject", "테스트" in parsed["subject"],
          f"got {parsed['subject']}")

    # 회신 파싱
    search, body, reply_all = _parse_reply_content("SEN-070 메일 회신 - 검토중입니다")
    check("parse_reply search", len(search) > 0, f"got '{search}'")
    check("parse_reply body", "검토중" in body, f"got '{body}'")
    check("parse_reply not reply_all", not reply_all)

    search2, body2, reply_all2 = _parse_reply_content("전체회신 - 확인했습니다")
    check("parse_reply_all detected", reply_all2)

    # 드래프트 저장/로드
    import tempfile
    import scripts.telegram.skills.email_skills as em
    old_dir = em._DRAFT_DIR
    em._DRAFT_DIR = tempfile.mkdtemp()
    try:
        _save_draft({"type": "send", "to": "test@test.com", "subject": "test"})
        draft = _load_latest_draft("send")
        check("Draft save/load works", draft is not None and draft["to"] == "test@test.com",
              f"got {draft}")
        # 로드 후 삭제 확인
        draft2 = _load_latest_draft("send")
        check("Draft deleted after load", draft2 is None)
    finally:
        em._DRAFT_DIR = old_dir

except Exception as e:
    errors.append(f"draft/parse functions: {e}")
    print(f"  [FAIL] draft/parse functions -- {e}")

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
